"""실제 Remotion 렌더 E2E (가짜 TTS). `pytest -m node`로 실행."""

import json

import httpx
import pytest
from typer.testing import CliRunner

from kaidanzip.cli import app
from kaidanzip.tools import probe_video

from .conftest import SAMPLE

pytestmark = pytest.mark.node
runner = CliRunner()


def test_full_render_then_rerender(isolated, images_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: calls.append(1))

    res = runner.invoke(app, ["run", str(SAMPLE), "--images", str(images_dir), "--yes"])
    assert res.exit_code in (0, 2), res.output
    job = next((isolated / "jobs").iterdir())
    ret = job / "output" / "ret.mp4"
    assert ret.is_file()
    stream = probe_video(ret)
    assert (stream["width"], stream["height"], stream["r_frame_rate"]) == (1080, 1920, "30/1")

    report = json.loads((job / "qc_report.json").read_text(encoding="utf-8"))
    assert len(report["checks"]) == 6
    assert report["checks"]["artifacts"]["passed"], report["checks"]["artifacts"]
    warnings = json.loads((job / "logs" / "warnings.json").read_text(encoding="utf-8"))
    assert len([w for w in warnings if w["type"] == "missing_sfx"]) == 6
    assert len([w for w in warnings if w["type"] == "missing_bgm"]) == 1
    assert not (job / "render_public").exists()

    res2 = runner.invoke(app, ["render", job.name, "--yes"])
    assert res2.exit_code in (0, 2), res2.output
    st = json.loads((job / "status.json").read_text(encoding="utf-8"))
    assert any(h.get("via") == "rerender" for h in st["history"])
    assert st["attempt"] == 2
    assert (job / "edit" / "attempt_1" / "final.mp4").is_file()
    assert (job / "output" / "ret.mp4").is_file()
    assert calls == []
