import shutil
from pathlib import Path

import pytest

from kaidanzip import fake_tts, voice
from kaidanzip.storyboard import parse_storyboard

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample.md"
EMOTION = ROOT / "emotion"


@pytest.fixture
def sample_text() -> str:
    return SAMPLE.read_text(encoding="utf-8")


@pytest.fixture
def board(sample_text):
    return parse_storyboard(sample_text)


@pytest.fixture
def words_doc(board):
    """sample.md로 합성한 words.json (네트워크·mp3 없이)."""
    text, starts = voice.build_request_text(board)
    resp = fake_tts.synth_response(text, char_s=0.17, space_s=0.06)
    words = voice.aggregate_words(text, resp["alignment"])
    return {
        "language_code": "kor",
        "audio_duration_ms": words[-1]["end"] + 300,
        "text": text,
        "scene_char_starts": starts,
        "words": words,
    }


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """jobs/assets 위치를 tmp로 격리하고 가짜 TTS를 켠다."""
    monkeypatch.setenv("KAIDANZIP_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("KAIDANZIP_ASSETS_DIR", str(tmp_path / "assets"))
    monkeypatch.setenv("KAIDANZIP_FAKE_TTS", "synth")
    monkeypatch.setenv("KAIDANZIP_SUBTITLE_SPLIT", "rule")  # 테스트에서 OpenAI 호출 금지
    monkeypatch.delenv("KAIDANZIP_VOICE_ID", raising=False)
    return tmp_path


@pytest.fixture
def images_dir(tmp_path):
    dest = tmp_path / "images"
    shutil.copytree(EMOTION, dest)
    return dest
