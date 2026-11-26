import json

import httpx
import pytest

from kaidanzip import subtitles
from kaidanzip.errors import InputValidationError
from kaidanzip.storyboard import parse_storyboard
from kaidanzip.subtitles import binds, check_chunks, rule_split, split_scenes

SCENE2_EXPECTED = [
    "부산 장산의 전설 속 괴물,",
    "‘장산범’ 때문입니다.",
    "새하얀 털의 이 괴물은",
    "사람 목소리를 똑같이 흉내 내어",
    "사냥감을 부릅니다.",
]


def test_scene2_matches_requested_result(board):
    assert rule_split(board.scenes[1].narration) == SCENE2_EXPECTED


def test_all_sample_scenes_follow_rules(board):
    for s in board.scenes:
        chunks = rule_split(s.narration)
        assert check_chunks(s.narration, chunks) is None, s.index
        assert all(len(c.split()) >= 2 for c in chunks), (s.index, chunks)   # 1어절 홀로 금지
        assert all(len(c.split()) <= 6 for c in chunks), (s.index, chunks)


@pytest.mark.parametrize("a,b", [
    ("이", "괴물은"), ("새하얀", "털의"), ("털의", "이"), ("그", "순간,"), ("다정했던", "목소리가"),
    ("흉내", "내어"), ("얼어붙고", "말았습니다."), ("잠들어", "있었기"), ("긁기", "시작했습니다."),
    ("3", "년"), ("김", "씨"), ("깊이", "잠들어"),
])
def test_bound_pairs_never_split(a, b):
    assert binds(a, b)


@pytest.mark.parametrize("a,b", [("괴물,", "‘장산범’"), ("때문입니다.", "새하얀"), ("깼습니다.", "“아들아,"), ("열어줘.”", "다음")])
def test_hard_breaks(a, b):
    assert not binds(a, b)


def test_sentence_never_mixed():
    out = rule_split("짧다. 아주 짧은 다음 문장이 이어진다. 끝.")
    assert out[0] == "짧다." or out[0].endswith("짧다.")
    for c in out:
        toks = c.split()
        assert not any(t.endswith(".") for t in toks[:-1])


def test_dialogue_is_its_own_chunk(board):
    chunks = rule_split(board.scenes[2].narration)
    assert chunks[-1] == "“아들아, 문 좀 열어줘.”"


def test_check_chunks_rejects_changed_text_and_mixed_sentences():
    n = "가 나 다. 라 마."
    assert check_chunks(n, ["가 나 다.", "라 마."]) is None
    assert check_chunks(n, ["가 나", "다. 라 마."]) is not None      # 두 문장 섞임
    assert check_chunks(n, ["가 나 다.", "라 바."]) is not None       # 글자 변경
    assert check_chunks(n, ["가나 다.", "라 마."]) is not None        # 어절 변경


def test_manual_split_overrides(sample_text):
    md = sample_text.replace(
        "- **자막 강조(빨간색):** 장산범, 사람 목소리, 사냥감",
        "- **자막 강조(빨간색):** 장산범, 사람 목소리, 사냥감\n- **자막 분할:** 부산 장산의 / 전설 속 괴물, ‘장산범’ 때문입니다. / 새하얀 털의 이 괴물은 사람 목소리를 / 똑같이 흉내 내어 사냥감을 부릅니다.",
    )
    b = parse_storyboard(md)
    chunks, source, _ = split_scenes(b.scenes, "rule")
    assert source[2] == "manual"
    assert chunks[2][0] == "부산 장산의"
    assert source[1] == "rule"


def test_manual_split_invalid_is_scene_error(sample_text):
    md = sample_text.replace(
        "- **자막 강조(빨간색):** 장산범, 사람 목소리, 사냥감",
        "- **자막 강조(빨간색):** 장산범, 사람 목소리, 사냥감\n- **자막 분할:** 부산 장산의 / 다른 문장입니다.",
    )
    with pytest.raises(InputValidationError) as exc:
        parse_storyboard(md)
    assert exc.value.scene == 2


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body


def _ai(monkeypatch, scenes_payload):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    body = {"choices": [{"message": {"content": json.dumps({"scenes": scenes_payload}, ensure_ascii=False)}}]}
    monkeypatch.setattr(httpx.Client, "post", lambda self, url, headers=None, json=None: _Resp(200, body))


def test_ai_result_used_when_valid(board, monkeypatch):
    n2 = board.scenes[1].narration
    _ai(monkeypatch, [{"index": 2, "chunks": ["부산 장산의 전설 속 괴물,", "‘장산범’ 때문입니다.", n2.split("때문입니다. ")[1]]}])
    chunks, source, log = split_scenes(board.scenes, "ai")
    assert source[2] == "ai"
    assert source[1] == "rule" and log["fallbacks"][1] == "AI 결과 없음"


def test_ai_invalid_falls_back_to_rule(board, monkeypatch):
    _ai(monkeypatch, [{"index": 2, "chunks": ["부산 장산의 전설 속 괴물, ‘장산범’ 때문입니다. 새하얀", "털의 이 괴물은 사람 목소리를 똑같이 흉내 내어 사냥감을 부릅니다."]}])
    chunks, source, log = split_scenes(board.scenes, "ai")
    assert source[2] == "rule"
    assert chunks[2] == SCENE2_EXPECTED
    assert "두 문장" in log["fallbacks"][2]


def test_ai_http_error_falls_back(board, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(httpx.Client, "post", lambda self, url, headers=None, json=None: _Resp(401, {"error": "x"}))
    chunks, source, log = split_scenes(board.scenes, "ai")
    assert set(source.values()) == {"rule"}
    assert log["ai"]["status"] == 401


def test_auto_without_key_uses_rule(board, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _, source, _ = split_scenes(board.scenes, "auto")
    assert set(source.values()) == {"rule"}


def test_ai_breaking_bound_pair_or_orphan_is_rejected(board, monkeypatch):
    _ai(monkeypatch, [
        {"index": 2, "chunks": ["부산 장산의 전설 속 괴물,", "‘장산범’ 때문입니다.", "새하얀 털의 이 괴물은", "사람 목소리를 똑같이", "흉내 내어 사냥감을 부릅니다."]},
        {"index": 3, "chunks": ["어느 새벽,", "산 아래 살던 남성은", "현관 밖 어머니의 다급한 목소리에 깼습니다.", "“아들아,", "문 좀 열어줘.”"]},
    ])
    chunks, source, log = split_scenes(board.scenes, "ai")
    assert source[2] == "rule" and "똑같이 / 흉내" in log["fallbacks"][2]
    assert chunks[2] == SCENE2_EXPECTED
    assert source[3] == "rule" and "1어절" in log["fallbacks"][3]


def test_manual_split_is_not_strict():
    assert check_chunks("가 나 다 라.", ["가", "나 다 라."]) is None
