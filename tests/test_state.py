import re

import pytest

from kaidanzip.errors import StateError
from kaidanzip.state import JobState, new_job_id, validate_transition


def test_job_id_format():
    assert re.fullmatch(r"sf_\d{8}_[0-9a-f]{6}", new_job_id())


def test_happy_path_and_history(tmp_path):
    st = JobState.create(tmp_path / "j", "sf_20261126_abcdef", {})
    for s in ["parsed", "voice_generated", "planned", "confirmed", "final_rendered", "qc_passed"]:
        st.transition(s)
    assert [h["status"] for h in st.data["history"]] == [
        "created", "parsed", "voice_generated", "planned", "confirmed", "final_rendered", "qc_passed"]


def test_skip_and_terminal_blocked(tmp_path):
    st = JobState.create(tmp_path / "j", "x", {})
    with pytest.raises(StateError):
        st.transition("planned")
    st.transition("failed", failed_stage="parse")
    with pytest.raises(StateError):
        st.transition("parsed")


@pytest.mark.parametrize("current,stage,ok", [
    ("qc_passed", None, True), ("qc_failed", None, True), ("aborted", None, True), ("planned", None, True),
    ("failed", "render", True), ("failed", "confirm", True), ("failed", "qc", True),
    ("failed", "voice", False), ("failed", "parse", False), ("created", None, False),
])
def test_rerender_transition(current, stage, ok):
    if ok:
        validate_transition(current, "planned", via="rerender", failed_stage=stage)
    else:
        with pytest.raises(StateError):
            validate_transition(current, "planned", via="rerender", failed_stage=stage)
