"""자막 덩어리(subtitle_chunks) 분할.

우선순위: 연출표의 수동 분할("자막 분할" 필드, "/" 구분) > AI 분할 > 규칙 기반 분할.
어느 방식이든 결과는 장면 나레이션의 어절(공백 기준 토큰)을 순서 그대로 나눈 것이어야 한다.

규칙 (우선순위 순)
1. 문장 끝(. ? !)에서는 반드시 끊는다.
2. 쉼표(,)와 큰따옴표 대사(“ ”)의 시작·끝에서 우선 끊는다.
3. 붙어야 뜻이 통하는 말(꾸밈말+꾸밈받는 말, 동사 덩어리, 숫자+단위, 이름+호칭)은 가르지 않는다.
4. 한 자막은 3~5어절 목표. 문장 끝 때문에 2어절, 덩어리 보호로 6어절 이상은 허용. 1어절만 홀로 남지 않게 한다.
5. 자막은 장면 경계를 넘지 않는다 (장면 단위로만 분할하므로 항상 성립).
"""

from __future__ import annotations

import json
import os
import re

import httpx

from ._retry import request_with_retry

TARGET_MIN, TARGET_MAX = 3, 5

OPEN_DIALOGUE = ("“", '"')
CLOSE_DIALOGUE = ("”", '"')
TRAILING = "”’\"')]」』"
SENTENCE_END = (".", "?", "!", "…")

DETERMINERS = {
    "이", "그", "저", "이런", "그런", "저런", "어느", "무슨", "모든", "온", "새", "각", "몇",
    "한", "두", "세", "네", "여러", "어떤", "아무", "다른",
}
# 다음 어절이 이것으로 시작하면 앞 어절과 묶는다 (보조용언·의존명사·가벼운 동사)
AUX_PREFIXES = (
    "있", "없", "말았", "말고", "말아", "마세", "마라", "시작", "내어", "내다", "냈", "내고", "내며",
    "버리", "버렸", "주었", "주어", "줘", "줬", "보았", "봤", "않", "못하", "싶",
    "때문", "것", "듯", "뿐", "채",
)
# 동사를 꾸미는 부사: 뒤 어절과 묶는다 ("깊이 잠들어", "똑같이 흉내 내어", "거칠게 긁기")
ADVERBS = {"깊이", "높이", "같이", "똑같이", "천천히", "가만히", "몰래", "멀리", "살짝", "갑자기", "조용히", "다시", "바로", "그대로", "더"}
ADVERB_ENDINGS = ("히", "게", "같이", "없이")
TITLES = {"씨", "님", "선생", "선생님", "군", "양", "할머니", "할아버지", "아저씨", "아주머니"}
UNIT_RE = re.compile(r"^[0-9０-９]+$|^(한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|백|천|만)$")
# 이 어미/조사로 끝나면 끊기 좋은 자리
GOOD_BREAK_ENDINGS = (
    "은", "는", "을", "를", "에", "에서", "에게", "고", "며", "서", "어", "아", "여", "면", "는데", "니", "도", "로", "으로", "와", "과",
)
# 꾸밈말로 보지 않는 끝 글자(조사)
NOT_ADNOMINAL_ENDINGS = ("은", "는", "을", "를", "른", "란", "선", "만", "운")


def core(token: str) -> str:
    """앞뒤 따옴표·괄호·문장부호를 뗀 어절 본체."""
    return token.strip("“”‘’\"'()[]「」『』,.?!…·-~")


def is_sentence_end(token: str) -> bool:
    return token.rstrip(TRAILING).endswith(SENTENCE_END)


def ends_with_comma(token: str) -> bool:
    return token.rstrip(TRAILING).endswith(",")


def _final_consonant(ch: str) -> int:
    code = ord(ch) - 0xAC00
    if 0 <= code < 11172:
        return code % 28
    return -1


def _is_adnominal(word: str) -> bool:
    if not word:
        return False
    if word.endswith("의") or word.endswith("던"):
        return True
    if word.endswith(NOT_ADNOMINAL_ENDINGS):
        return False
    jong = _final_consonant(word[-1])
    return len(word) >= 2 and jong in (4, 8)  # ㄴ, ㄹ 받침: 새하얀, 다급한, 할


def binds(token: str, nxt: str) -> bool:
    """token과 다음 어절을 한 덩어리로 묶어야 하는가 (규칙 3)."""
    if ends_with_comma(token) or is_sentence_end(token):
        return False
    if nxt.startswith(OPEN_DIALOGUE) or token.endswith(CLOSE_DIALOGUE):
        return False
    a, b = core(token), core(nxt)
    if not a or not b:
        return False
    if a in DETERMINERS:
        return True
    if b.startswith(AUX_PREFIXES):
        return True
    if a in ADVERBS or (len(a) >= 2 and a.endswith(ADVERB_ENDINGS)):
        return True
    if b in TITLES or (UNIT_RE.match(a) and len(b) <= 3):
        return True
    return _is_adnominal(a)


def _good_break(token: str) -> bool:
    return core(token).endswith(GOOD_BREAK_ENDINGS)


def _segments(tokens: list[str]) -> list[list[int]]:
    """규칙 1·2(대사): 문장 끝, 대사 시작·끝에서 반드시 끊는다."""
    segs: list[list[int]] = []
    cur: list[int] = []
    for i, tok in enumerate(tokens):
        if cur and tok.startswith(OPEN_DIALOGUE):
            segs.append(cur)
            cur = []
        cur.append(i)
        if is_sentence_end(tok) or tok.endswith(CLOSE_DIALOGUE):
            segs.append(cur)
            cur = []
    if cur:
        segs.append(cur)
    return segs


def _clauses(seg: list[int], tokens: list[str]) -> list[list[int]]:
    """규칙 2: 쉼표에서 우선 끊되, 1어절 조각은 이웃과 합친다."""
    parts: list[list[int]] = []
    cur: list[int] = []
    for i in seg:
        cur.append(i)
        if ends_with_comma(tokens[i]):
            parts.append(cur)
            cur = []
    if cur:
        parts.append(cur)
    merged: list[list[int]] = []
    for p in parts:
        if merged and len(merged[-1]) == 1:
            merged[-1] = merged[-1] + p
        elif len(p) == 1 and merged:
            merged[-1] = merged[-1] + p
        else:
            merged.append(p)
    return merged


def _units(clause: list[int], tokens: list[str]) -> list[list[int]]:
    units: list[list[int]] = []
    for i in clause:
        if units and binds(tokens[units[-1][-1]], tokens[i]):
            units[-1].append(i)
        else:
            units.append([i])
    return units


def _pack(clause: list[int], tokens: list[str]) -> list[list[int]]:
    """규칙 4: 덩어리(unit)를 3~5어절 목표로 묶는다."""
    units = _units(clause, tokens)
    chunks: list[list[list[int]]] = []  # chunk = unit 목록
    cur: list[list[int]] = []

    def size(c):
        return sum(len(u) for u in c)

    for k, u in enumerate(units):
        if cur and size(cur) + len(u) > TARGET_MAX and size(cur) >= 2:
            chunks.append(cur)
            cur = []
        cur = cur + [u]
        remaining = sum(len(x) for x in units[k + 1 :])
        if size(cur) >= TARGET_MIN and _good_break(tokens[cur[-1][-1]]) and remaining >= 2:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    # 1어절만 홀로 남으면: 앞 덩어리의 마지막 unit을 넘겨도 앞이 3어절 이상이면 넘기고, 아니면 합친다.
    if len(chunks) >= 2 and size(chunks[-1]) == 1:
        prev = chunks[-2]
        if len(prev) >= 2 and size(prev[:-1]) >= TARGET_MIN:
            chunks[-1] = [prev[-1]] + chunks[-1]
            chunks[-2] = prev[:-1]
        else:
            chunks[-2] = prev + chunks[-1]
            chunks.pop()
    return [[i for u in c for i in u] for c in chunks]


def rule_split(narration: str) -> list[str]:
    tokens = narration.split()
    out: list[str] = []
    for seg in _segments(tokens):
        for clause in _clauses(seg, tokens):
            for chunk in _pack(clause, tokens):
                out.append(" ".join(tokens[i] for i in chunk))
    return out


# ---------- 검증 (수동·AI 결과 공용) ----------

def check_chunks(narration: str, chunks: list[str], strict: bool = False) -> str | None:
    """문제가 있으면 한국어 사유, 없으면 None.

    strict=True(AI 결과): 규칙 3(덩어리 가르기 금지)·규칙 4(1어절 홀로 금지)까지 검사한다.
    수동 분할은 사용자의 결정이므로 글자 일치와 규칙 1만 검사한다.
    """
    if not chunks or any(not c.strip() for c in chunks):
        return "빈 자막 덩어리가 있습니다."
    flat = [t for c in chunks for t in c.split()]
    if flat != narration.split():
        return "자막 덩어리를 이어 붙인 결과가 나레이션과 다릅니다(어절 단위로만 나눌 수 있습니다)."
    for c in chunks:
        toks = c.split()
        for t in toks[:-1]:
            if is_sentence_end(t):
                return f"한 자막에 두 문장이 섞였습니다: '{c}'"
    if strict:
        if len(flat) > 1 and any(len(c.split()) == 1 for c in chunks):
            return "1어절만 홀로 남은 자막이 있습니다: " + ", ".join(f"'{c}'" for c in chunks if len(c.split()) == 1)
        for left, right in zip(chunks, chunks[1:]):
            a, b = left.split()[-1], right.split()[0]
            if binds(a, b):
                return f"붙어야 할 말이 갈라졌습니다: '{a} / {b}'"
    return None


def parse_manual(raw: str) -> list[str]:
    return [p.strip() for p in raw.split("/") if p.strip()]


# ---------- AI 분할 ----------

AI_MODEL_DEFAULT = "gpt-5-mini"

AI_INSTRUCTIONS = """너는 한국어 숏폼 자막 편집자다. 각 장면 나레이션을 자막 덩어리로 나눈다.
규칙(우선순위 순):
1. 문장 끝(. ? !)에서는 반드시 끊는다. 한 덩어리에 두 문장을 섞지 않는다.
2. 쉼표(,)와 큰따옴표 대사의 시작·끝에서 우선 끊는다.
3. 붙어야 뜻이 통하는 말은 절대 가르지 않는다: 꾸밈말+꾸밈받는 말("이 괴물은", "새하얀 털의", "그 순간", "다정했던 목소리가"), 동사 덩어리("흉내 내어", "얼어붙고 말았습니다", "잠들어 있었기", "긁기 시작했습니다"), 숫자+단위, 이름+호칭.
4. 한 덩어리는 3~5어절 목표. 문장 끝 때문에 2어절, 덩어리 보호를 위해 6어절은 괜찮다. 1어절만 홀로 남기지 않는다.
5. 장면을 넘지 않는다.
나레이션의 글자·띄어쓰기·문장부호를 절대 바꾸지 말고 공백 위치에서만 나눠라.
JSON만 출력: {"scenes": [{"index": 1, "chunks": ["...", "..."]}]}"""


def ai_split(narrations: dict[int, str]) -> tuple[dict[int, list[str]], dict]:
    """OpenAI로 분할. (장면별 결과, 로그) — 실패하면 빈 dict와 사유."""
    key = os.environ.get("OPENAI_API_KEY")
    log: dict = {"model": os.environ.get("MD2SHORT_OPENAI_MODEL", AI_MODEL_DEFAULT)}
    if not key:
        log["error"] = "OPENAI_API_KEY 없음"
        return {}, log
    payload = {
        "model": log["model"],
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": AI_INSTRUCTIONS},
            {"role": "user", "content": json.dumps(
                {"scenes": [{"index": i, "narration": n} for i, n in narrations.items()]}, ensure_ascii=False)},
        ],
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = request_with_retry(lambda: client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"}, json=payload))
        log["status"] = resp.status_code
        if resp.status_code >= 400:
            log["error"] = resp.text[:300]
            return {}, log
        content = resp.json()["choices"][0]["message"]["content"]
        log["raw"] = content
        data = json.loads(content)
        return {int(s["index"]): [str(c) for c in s["chunks"]] for s in data.get("scenes", [])}, log
    except Exception as exc:  # 어떤 실패든 규칙 기반으로 대체
        log["error"] = f"{type(exc).__name__}: {exc}"
        return {}, log


def split_scenes(scenes: list, mode: str = "auto") -> tuple[dict[int, list[str]], dict[int, str], dict]:
    """장면별 subtitle_chunks와 출처(manual|ai|rule), 로그.

    mode: auto(키가 있으면 AI) | ai | rule
    수동 분할 오류는 호출자가 미리 검증한다(storyboard.validate).
    """
    result: dict[int, list[str]] = {}
    source: dict[int, str] = {}
    log: dict = {"mode": mode, "fallbacks": {}}

    pending = {}
    for s in scenes:
        if s.subtitle_manual:
            result[s.index] = parse_manual(s.subtitle_manual)
            source[s.index] = "manual"
        else:
            pending[s.index] = s.narration

    use_ai = mode == "ai" or (mode == "auto" and os.environ.get("OPENAI_API_KEY"))
    ai: dict[int, list[str]] = {}
    if pending and use_ai:
        ai, log["ai"] = ai_split(pending)

    for idx, narration in pending.items():
        chunks = ai.get(idx)
        reason = check_chunks(narration, chunks, strict=True) if chunks is not None else ("AI 미사용" if not use_ai else "AI 결과 없음")
        if chunks is not None and reason is None:
            result[idx], source[idx] = chunks, "ai"
        else:
            result[idx], source[idx] = rule_split(narration), "rule"
            if use_ai:
                log["fallbacks"][idx] = reason
    return result, source, log
