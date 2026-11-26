import pytest

from md2short.timeutil import FPS, ms_to_frames, s_to_ms


def test_fps_is_30():
    assert FPS == 30


@pytest.mark.parametrize(
    "ms,frames",
    [(0, 0), (16, 0), (17, 1), (33, 1), (50, 2), (1000, 30), (49_983, 1499), (50_000, 1500)],
)
def test_ms_to_frames_half_up(ms, frames):
    assert ms_to_frames(ms) == frames


def test_ms_to_frames_rejects_negative():
    with pytest.raises(ValueError):
        ms_to_frames(-1)


def test_s_to_ms():
    assert s_to_ms(1.2345) == 1234 or s_to_ms(1.2345) == 1235
    assert s_to_ms(0.0) == 0
    assert s_to_ms(49.98) == 49980
