import base64

import pytest
from mutagen.mp3 import MP3

from md2short import fake_tts, voice
from md2short.errors import AlignmentMismatchError


def test_request_text_joins_with_single_space(board):
    text, starts = voice.build_request_text(board)
    assert starts[0] == 0
    for scene, start in zip(board.scenes, starts):
        assert text[start : start + len(scene.narration)] == scene.narration
    assert "\n" not in text


def test_aggregate_words_char_offsets():
    text = "밤에 가족  목소리가"
    al = {
        "characters": list(text),
        "character_start_times_seconds": [i * 0.1 for i in range(len(text))],
        "character_end_times_seconds": [i * 0.1 + 0.1 for i in range(len(text))],
    }
    words = voice.aggregate_words(text, al)
    assert [w["text"] for w in words] == ["밤에", "가족", "목소리가"]
    assert [(w["char_start"], w["char_end"]) for w in words] == [(0, 2), (3, 5), (7, 11)]
    assert words[0]["start"] == 0 and words[0]["end"] == 200
    assert words[2]["start"] == 700 and words[2]["end"] == 1100


def test_alignment_mismatch_hard_fails(tmp_path):
    al = {"characters": list("다른 문장")}
    with pytest.raises(AlignmentMismatchError):
        voice.check_alignment("원래 문장", al, tmp_path / "diff.txt")
    assert (tmp_path / "diff.txt").is_file()


def test_silent_mp3_duration_is_measurable(tmp_path):
    p = tmp_path / "a.mp3"
    p.write_bytes(fake_tts.silent_mp3_bytes(10.0))
    assert abs(MP3(p).info.length - 10.0) < 0.05


def test_synthesize_writes_words_json(board, tmp_path, monkeypatch):
    monkeypatch.setenv("MD2SHORT_FAKE_TTS", "synth")
    (tmp_path / "logs").mkdir()
    doc = voice.synthesize(board, tmp_path)
    assert (tmp_path / "audio" / "narration.mp3").is_file()
    assert (tmp_path / "transcripts" / "words.json").is_file()
    raw = (tmp_path / "logs" / "elevenlabs_tts_raw.json").read_text(encoding="utf-8")
    assert "audio_base64" not in raw
    assert doc["words"][-1]["end"] <= doc["audio_duration_ms"]
    assert doc["scene_char_starts"][0] == 0


def test_speed_validation_and_body():
    from md2short.errors import InputValidationError

    assert voice.request_body("가", 1.0) == {"text": "가", "model_id": voice.MODEL_ID}
    assert voice.request_body("가", 0.9)["voice_settings"] == {"speed": 0.9}
    for bad in (0.69, 1.21):
        with pytest.raises(InputValidationError):
            voice.validate_speed(bad)


def test_speed_sent_to_elevenlabs(monkeypatch, tmp_path, board):
    import httpx

    sent = {}

    class Resp:
        status_code = 200
        text = ""

        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    def fake_post(self, url, params=None, headers=None, json=None):
        sent.update(url=url, params=params, json=json)
        return Resp(fake_tts.synth_response(json["text"]))

    monkeypatch.delenv("MD2SHORT_FAKE_TTS", raising=False)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    (tmp_path / "logs").mkdir()
    doc = voice.synthesize(board, tmp_path, speed=0.9)
    assert sent["json"]["voice_settings"] == {"speed": 0.9}
    assert sent["params"] == {"output_format": "mp3_44100_128"}
    assert "/with-timestamps" in sent["url"]
    assert doc["tts_speed"] == 0.9
    raw = (tmp_path / "logs" / "elevenlabs_tts_raw.json").read_text(encoding="utf-8")
    assert "test-key" not in raw
