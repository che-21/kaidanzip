import io
import json

import pytest
from rich.console import Console

from md2short.confirm import confirm
from md2short.errors import EXIT_ABORTED, EXIT_INPUT, ConfirmAborted, InputValidationError

EDL = {
    "audio_duration_ms": 48_000,
    "scenes": [
        {"index": 1, "target_s": [0, 4], "start_ms": 0, "end_ms": 4000, "motion": "zoomIn", "effects": [],
         "image": {"original_name": "0_a.png", "width": 941, "height": 1672},
         "sfx": [{"key": "knock", "file": None, "applied": False}]},
    ],
}


def _run(tmp_path, text, yes=False):
    (tmp_path / "logs").mkdir(exist_ok=True)
    confirm(EDL, tmp_path, assume_yes=yes, stdin=io.StringIO(text), console=Console(file=io.StringIO()))
    return json.loads((tmp_path / "logs" / "confirm.json").read_text(encoding="utf-8"))


def test_yes_answer_proceeds(tmp_path):
    assert _run(tmp_path, "y\n")["answer"] == "y"


def test_no_answer_aborts_with_exit_3(tmp_path):
    with pytest.raises(ConfirmAborted) as exc:
        _run(tmp_path, "n\n")
    assert exc.value.exit_code == EXIT_ABORTED == 3


def test_eof_is_error_exit_1(tmp_path):
    with pytest.raises(InputValidationError) as exc:
        _run(tmp_path, "")
    assert exc.value.exit_code == EXIT_INPUT == 1
    assert json.loads((tmp_path / "logs" / "confirm.json").read_text(encoding="utf-8"))["answer"] == "EOF"


def test_assume_yes_skips_input(tmp_path):
    assert _run(tmp_path, "", yes=True)["answer"] == "yes(--yes)"


def test_suggest_speed():
    from md2short.confirm import suggest_speed

    assert suggest_speed(48_000) is None
    assert suggest_speed(44_722) == 0.89          # 짧으면 느리게
    assert suggest_speed(62_000) == 1.2           # 길면 빠르게(상한)
    assert suggest_speed(30_000) == 0.7           # 하한 clamp
    assert suggest_speed(44_000, current_speed=0.9) == 0.79
