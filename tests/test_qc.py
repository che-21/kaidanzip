import pytest

from md2short import qc
from md2short.timeutil import ms_to_frames


def _words(audio_ms, last_end):
    return {"audio_duration_ms": audio_ms, "text": "가나다", "words": [{"text": "가나다", "start": 0, "end": last_end}]}


def _eval(tmp_path, video_s=50.0, audio_ms=50_000, last_end=49_500, w=1080, h=1920, fps="30/1", frames=None):
    stream = {"width": w, "height": h, "r_frame_rate": fps, "duration": str(video_s)}
    props = {"durationInFrames": frames if frames is not None else ms_to_frames(audio_ms)}
    return qc.evaluate(stream, _words(audio_ms, last_end), props, tmp_path)


def test_exactly_six_checks(tmp_path):
    assert list(_eval(tmp_path)["checks"]) == ["resolution", "fps", "duration", "tail_sync", "render_length", "artifacts"]


@pytest.mark.parametrize("video_s,ok", [(44.9, False), (45.0, True), (58.0, True), (58.1, False)])
def test_duration_bounds(tmp_path, video_s, ok):
    r = _eval(tmp_path, video_s=video_s, audio_ms=int(video_s * 1000), last_end=int(video_s * 1000) - 200)
    assert r["checks"]["duration"]["passed"] is ok


@pytest.mark.parametrize("gap,ok", [(1000, True), (1001, False)])
def test_tail_sync(tmp_path, gap, ok):
    r = _eval(tmp_path, last_end=50_000 - gap)
    assert r["checks"]["tail_sync"]["passed"] is ok


def test_render_length_tolerance(tmp_path):
    assert _eval(tmp_path, frames=1500 + 3)["checks"]["render_length"]["passed"]
    assert not _eval(tmp_path, frames=1500 + 4)["checks"]["render_length"]["passed"]


def test_resolution_and_fps(tmp_path):
    r = _eval(tmp_path, w=1920, h=1080, fps="25/1")
    assert not r["checks"]["resolution"]["passed"]
    assert not r["checks"]["fps"]["passed"]


def test_artifacts_missing_fails_overall(tmp_path):
    r = _eval(tmp_path)
    assert not r["checks"]["artifacts"]["passed"]
    assert not r["passed"]
    assert "output/ret.mp4" in r["checks"]["artifacts"]["value"]
