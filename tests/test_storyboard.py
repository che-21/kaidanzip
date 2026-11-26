import pytest

from kaidanzip.errors import InputValidationError
from kaidanzip.storyboard import find_highlight_range, norm, parse_storyboard

EXPECTED_HIGHLIGHTS = {
    1: ["절대", "문을 열지 마세요"],
    2: ["장산범", "사람 목소리", "사냥감"],
    3: ["새벽", "어머니의 다급한 목소리"],
    4: ["얼어붙고", "어머니가 깊이 잠들어"],
    5: ["짐승의 울음", "거칠게 긁기"],
    6: ["절대 먼저 열지 마세요", "구독"],
}


def test_sample_parses_six_scenes(board):
    assert board.title == "장면별 세부 연출표 (6개 장면)"
    assert [s.index for s in board.scenes] == [1, 2, 3, 4, 5, 6]
    assert [(s.target_start_s, s.target_end_s) for s in board.scenes] == [
        (0, 4), (4, 14), (14, 23), (23, 33), (33, 42), (42, 50)
    ]
    assert board.scenes[0].narration == "밤에 가족 목소리가 들려도, 절대 문을 열지 마세요."
    assert board.scenes[3].visual_direction.startswith("문고리에 손을 올린")
    assert board.scenes[4].sfx_direction.startswith("날카로운 손톱으로")


def test_sample_highlights_all_13_match(board):
    assert {s.index: s.highlights for s in board.scenes} == EXPECTED_HIGHLIGHTS
    total = 0
    for s in board.scenes:
        for phrase, (a, b) in zip(s.highlights, s.highlight_ranges):
            assert norm(s.narration[a:b]) == norm(phrase)
            assert norm(s.narration).count(norm(phrase)) == 1
            total += 1
    assert total == 13


def test_highlight_range_maps_back_to_original_chars():
    narr = "부산 장산의 전설 속 괴물, ‘장산범’ 때문입니다."
    a, b = find_highlight_range(narr, "장산범")
    assert narr[a:b] == "장산범"
    a, b = find_highlight_range("얼어붙고 말았습니다", "얼어붙고")
    assert (a, b) == (0, 4)


def _mutate(text, old, new):
    assert old in text
    return text.replace(old, new, 1)


@pytest.mark.parametrize(
    "mutation,scene",
    [
        (("## 장면 3 [14~23초]", "## 장면 4 [14~23초]"), 4),
        (("- **나레이션:** 어느 새벽, 산 아래 살던 남성은 현관 밖 어머니의 다급한 목소리에 깼습니다. “아들아, 문 좀 열어줘.”", "- **나레이션:** "), 3),
        (("장산범, 사람 목소리, 사냥감", "장산범, 사람 목소리, 늑대"), 2),
    ],
)
def test_defects_raise_with_scene_number(sample_text, mutation, scene):
    bad = _mutate(sample_text, *mutation)
    with pytest.raises(InputValidationError) as exc:
        parse_storyboard(bad)
    assert exc.value.scene == scene
    assert f"장면 {scene}" in exc.value.message


def test_no_scenes():
    with pytest.raises(InputValidationError) as exc:
        parse_storyboard("# 제목만 있음\n본문")
    assert "장면" in exc.value.message
