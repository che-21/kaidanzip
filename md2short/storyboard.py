"""연출표 마크다운 파싱·검증 (AC-2, AC-3).

입력 형식 (sample.md):

    ## 장면 1 [0~4초] : 첫 3초 후킹
    - **나레이션:** ...
    - **자막 강조(빨간색):** 절대, 문을 열지 마세요
    - **화면 연출:** ...
    - **효과음(SFX):** ...
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel

from .errors import InputValidationError

SCENE_RE = re.compile(r"^##\s*장면\s*(\d+)\s*\[(\d+)\s*~\s*(\d+)\s*초\]\s*:\s*(.+?)\s*$")
FIELD_RE = re.compile(r"^\s*[-*]\s*\*\*(.+?)\s*:\s*\*\*\s*(.*)$")

FIELD_KEYS = {
    "나레이션": "narration",
    "자막 강조": "highlights",
    "자막 분할": "subtitle_manual",
    "화면 연출": "visual_direction",
    "효과음": "sfx_direction",
}

# 강조어 매칭 정규화에서 무시하는 문장부호 (공백류는 별도로 제거)
IGNORED_PUNCT = set(",.!?…·()-~“”‘’\"'")


class Scene(BaseModel):
    index: int
    target_start_s: int
    target_end_s: int
    title: str
    narration: str
    highlights: list[str]
    visual_direction: str = ""
    sfx_direction: str = ""
    # 나레이션 내부 원문 문자 범위 [start, end) — 강조어별
    highlight_ranges: list[tuple[int, int]] = []
    # 연출표의 "자막 분할" 원문 ("/"로 끊는 위치 지정). 비어 있으면 AI/규칙 분할
    subtitle_manual: str = ""
    subtitle_chunks: list[str] = []
    subtitle_source: str = ""


class Storyboard(BaseModel):
    title: str | None = None
    scenes: list[Scene]


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def norm_with_map(text: str) -> tuple[str, list[int]]:
    """공백·무시 문장부호를 제거한 문자열과, 정규화 index → 원문 index 매핑을 돌려준다."""
    out: list[str] = []
    index_map: list[int] = []
    for i, ch in enumerate(text):
        if ch.isspace() or ch in IGNORED_PUNCT:
            continue
        out.append(ch)
        index_map.append(i)
    return "".join(out), index_map


def norm(text: str) -> str:
    return norm_with_map(text)[0]


def find_highlight_range(narration: str, phrase: str) -> tuple[int, int] | None:
    """정규화 부분 문자열 매칭 후 원문 문자 범위 [start, end)를 돌려준다."""
    target = norm(phrase)
    if not target:
        return None
    hay, index_map = norm_with_map(narration)
    pos = hay.find(target)
    if pos < 0:
        return None
    start = index_map[pos]
    end = index_map[pos + len(target) - 1] + 1
    return start, end


def split_highlights(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def parse_storyboard(markdown: str) -> Storyboard:
    markdown = nfc(markdown)
    title = None
    scenes: list[dict] = []
    current: dict | None = None

    for line in markdown.splitlines():
        if title is None and line.startswith("# "):
            title = line[2:].strip()
            continue
        m = SCENE_RE.match(line)
        if m:
            current = {
                "index": int(m.group(1)),
                "target_start_s": int(m.group(2)),
                "target_end_s": int(m.group(3)),
                "title": m.group(4).strip(),
                "narration": "",
                "highlights_raw": "",
                "visual_direction": "",
                "sfx_direction": "",
                "subtitle_manual": "",
            }
            scenes.append(current)
            continue
        if current is None:
            continue
        f = FIELD_RE.match(line)
        if not f:
            continue
        label, value = f.group(1).strip(), f.group(2).strip()
        for prefix, key in FIELD_KEYS.items():
            if label.startswith(prefix):
                if key == "highlights":
                    current["highlights_raw"] = value
                else:
                    current[key] = value
                break

    return validate(title, scenes)


def validate(title: str | None, raw_scenes: list[dict]) -> Storyboard:
    if not raw_scenes:
        raise InputValidationError(
            "연출표에서 장면을 찾지 못했습니다. '## 장면 1 [0~4초] : 제목' 형식의 제목 줄이 필요합니다."
        )

    scenes: list[Scene] = []
    for expected, raw in enumerate(raw_scenes, start=1):
        idx = raw["index"]
        if idx != expected:
            raise InputValidationError(
                f"장면 번호가 1부터 연속해야 합니다. {expected}번이 와야 할 자리에 {idx}번이 있습니다.",
                scene=idx,
            )
        if not raw["narration"]:
            raise InputValidationError("나레이션이 비어 있습니다. '- **나레이션:** 문장' 줄을 채워 주세요.", scene=idx)

        highlights = split_highlights(raw["highlights_raw"])
        ranges: list[tuple[int, int]] = []
        for phrase in highlights:
            r = find_highlight_range(raw["narration"], phrase)
            if r is None:
                raise InputValidationError(
                    f"자막 강조어 '{phrase}'가 이 장면 나레이션에 없습니다. 나레이션 문구와 같게 고쳐 주세요.",
                    scene=idx,
                )
            ranges.append(r)

        if raw.get("subtitle_manual"):
            from .subtitles import check_chunks, parse_manual

            problem = check_chunks(raw["narration"], parse_manual(raw["subtitle_manual"]))
            if problem:
                raise InputValidationError(f"'자막 분할' 줄이 올바르지 않습니다: {problem}", scene=idx)

        scenes.append(
            Scene(
                index=idx,
                target_start_s=raw["target_start_s"],
                target_end_s=raw["target_end_s"],
                title=raw["title"],
                narration=raw["narration"],
                highlights=highlights,
                visual_direction=raw["visual_direction"],
                sfx_direction=raw["sfx_direction"],
                highlight_ranges=ranges,
                subtitle_manual=raw.get("subtitle_manual", ""),
            )
        )
    return Storyboard(title=title, scenes=scenes)
