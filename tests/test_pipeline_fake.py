"""가짜 TTS + --skip-render로 렌더 직전까지 E2E (Node 불필요)."""

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from kaidanzip.cli import app
from kaidanzip.qc import REQUIRED_FILES

from .conftest import SAMPLE

runner = CliRunner()


def _only_job(isolated) -> Path:
    jobs = list((isolated / "jobs").iterdir())
    assert len(jobs) == 1
    return jobs[0]


def _status(job: Path) -> dict:
    return json.loads((job / "status.json").read_text(encoding="utf-8"))


def test_skip_render_reaches_confirmed_with_all_artifacts(isolated, images_dir, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("ElevenLabs HTTP must not be called in fake mode")

    monkeypatch.setattr(httpx.Client, "post", boom)
    res = runner.invoke(app, ["run", str(SAMPLE), "--images", str(images_dir), "--yes", "--skip-render"])
    assert res.exit_code == 0, res.output
    job = _only_job(isolated)
    st = _status(job)
    assert st["status"] == "confirmed"
    assert [h["status"] for h in st["history"]] == ["created", "parsed", "voice_generated", "planned", "confirmed"]
    pre_render = [f for f in REQUIRED_FILES if f not in ("edit/final.mp4", "logs/remotion.log", "output/ret.mp4")]
    missing = [f for f in pre_render if not (job / f).is_file()]
    assert missing == []
    assert sorted(p.name for p in (job / "inputs" / "images").iterdir()) == [f"scene_{i:02d}.png" for i in range(1, 7)]
    board = json.loads((job / "inputs" / "storyboard.json").read_text(encoding="utf-8"))
    assert [i["original_name"][0] for i in board["images"]] == list("012345")


@pytest.mark.parametrize("case", ["highlight", "narration", "images", "order"])
def test_defects_stop_before_tts(isolated, images_dir, monkeypatch, case):
    monkeypatch.delenv("KAIDANZIP_FAKE_TTS")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "dummy-not-used")
    calls = []
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: calls.append(1))

    text = SAMPLE.read_text(encoding="utf-8")
    if case == "highlight":
        text = text.replace("장산범, 사람 목소리, 사냥감", "장산범, 사람 목소리, 늑대")
        scene = 2
    elif case == "narration":
        text = text.replace("- **나레이션:** 그 순간,", "- **나레이션:** \n- **메모:** 그 순간,")
        scene = 5
    elif case == "order":
        text = text.replace("## 장면 6 [42~50초]", "## 장면 7 [42~50초]")
        scene = 7
    else:
        next(images_dir.glob("5_*")).unlink()
        scene = 6
    md = isolated / "bad.md"
    md.write_text(text, encoding="utf-8")

    res = runner.invoke(app, ["run", str(md), "--images", str(images_dir), "--yes", "--skip-render"])
    assert res.exit_code == 1, res.output
    assert f"장면 {scene}" in res.output
    assert calls == []
    job = _only_job(isolated)
    assert not (job / "logs" / "elevenlabs_tts_raw.json").exists()
    st = _status(job)
    assert st["status"] == "failed" and st["failed_stage"] == "parse"


def test_answer_n_aborts_exit_3(isolated, images_dir):
    res = runner.invoke(app, ["run", str(SAMPLE), "--images", str(images_dir), "--skip-render"], input="n\n")
    assert res.exit_code == 3, res.output
    job = _only_job(isolated)
    assert _status(job)["status"] == "aborted"
    assert not (job / "edit" / "final.mp4").exists()


def test_missing_key_is_clear_error(isolated, images_dir, monkeypatch):
    monkeypatch.delenv("KAIDANZIP_FAKE_TTS")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr("kaidanzip.pipeline.load_dotenv", lambda *a, **k: None)
    res = runner.invoke(app, ["run", str(SAMPLE), "--images", str(images_dir), "--yes", "--skip-render"])
    assert res.exit_code == 1
    assert "ELEVENLABS_API_KEY" in res.output
    assert not (isolated / "jobs").exists()


def test_rerender_refuses_voice_failure(isolated, images_dir, monkeypatch):
    from kaidanzip.state import JobState

    job = isolated / "jobs" / "sf_20261126_000000"
    st = JobState.create(job, "sf_20261126_000000", {})
    st.transition("parsed")
    st.transition("failed", failed_stage="voice")
    res = runner.invoke(app, ["render", "sf_20261126_000000", "--yes"])
    assert res.exit_code == 1
    assert "다시 렌더할 수 없습니다" in res.output


def test_unexpected_error_marks_job_failed(isolated, images_dir, monkeypatch):
    def broken(*a, **k):
        raise KeyError("boom")

    monkeypatch.setattr("kaidanzip.voice.synthesize", broken)
    res = runner.invoke(app, ["run", str(SAMPLE), "--images", str(images_dir), "--yes", "--skip-render"])
    assert res.exit_code == 4
    assert "예상하지 못한 오류" in res.output
    st = _status(_only_job(isolated))
    assert st["status"] == "failed" and st["failed_stage"] == "voice"
    assert "KeyError" in st["error"]
