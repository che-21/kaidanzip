"""웹 화면 흐름 (Streamlit AppTest, 가짜 TTS·가짜 이미지, Node 불필요)."""

import hashlib
import json

import pytest
from streamlit.testing.v1 import AppTest

from .conftest import ROOT, SAMPLE

APP = str(ROOT / "webapp" / "app.py")


@pytest.fixture
def web_env(isolated, monkeypatch):
    monkeypatch.setenv("MD2SHORT_FAKE_IMAGES", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "")       # .env의 실제 키로 AI 분할 호출 금지
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    return isolated


def _button(at, prefix):
    return next(b for b in at.button if b.label.startswith(prefix))


def _start(at):
    text = SAMPLE.read_text(encoding="utf-8")
    at.session_state["md_text"] = text
    at.session_state["md_hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    at.session_state["md_name"] = "sample.md"


def test_web_flow_script_images_voice_timing(web_env):
    at = AppTest.from_file(APP, default_timeout=120)
    _start(at)
    at.run()
    assert not at.exception, at.exception
    # 장면 2 자막 분할이 규칙 결과로 표시된다
    assert at.text_input(key="chunks_2").value == (
        "부산 장산의 전설 속 괴물, / ‘장산범’ 때문입니다. / 새하얀 털의 이 괴물은 / 사람 목소리를 똑같이 흉내 내어 / 사냥감을 부릅니다.")

    # "/" 수정 → 수동으로 기록된다
    at.text_input(key="chunks_1").set_value("밤에 가족 목소리가 / 들려도, 절대 문을 열지 마세요.")
    at.run()
    _button(at, "✅ 대본·이미지 확정").click()
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["step"] == "images"
    job = web_env / "jobs" / at.session_state["job_id"]
    sb = json.loads((job / "inputs" / "storyboard.json").read_text(encoding="utf-8"))
    assert [i["source"] for i in sb["images"]] == ["ai"] * 6
    assert sb["scenes"][0]["subtitle_source"] == "manual"
    assert sb["scenes"][0]["subtitle_chunks"] == ["밤에 가족 목소리가", "들려도, 절대 문을 열지 마세요."]
    assert sb["scenes"][1]["subtitle_source"] == "rule"

    _button(at, "🎙️ 음성 만들기").click()
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["step"] == "timing"
    st = json.loads((job / "status.json").read_text(encoding="utf-8"))
    assert st["status"] == "planned"
    props = json.loads((job / "edit" / "props.json").read_text(encoding="utf-8"))
    first = "".join(sp["text"] for sp in props["captions"][0]["spans"])
    assert first == "밤에 가족 목소리가"


def test_web_shows_parse_error(web_env):
    at = AppTest.from_file(APP, default_timeout=60)
    text = SAMPLE.read_text(encoding="utf-8").replace("장산범, 사람 목소리, 사냥감", "장산범, 늑대")
    at.session_state["md_text"] = text
    at.session_state["md_hash"] = "x"
    at.session_state["md_name"] = "bad.md"
    at.run()
    assert any("장면 2" in e.value for e in at.error)
