"""ElevenLabs 응답을 흉내 내는 가짜 TTS (테스트·무료 리허설용).

``KAIDANZIP_FAKE_TTS``
- ``synth``: 요청 텍스트로 alignment를 합성하고 무음 mp3를 만든다.
- 그 밖의 값: ElevenLabs ``with-timestamps`` 응답 JSON 파일 경로로 보고 그대로 읽는다.

시간은 ElevenLabs 응답과 같은 초(float) 단위로만 다룬다.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

# MPEG-1 Layer III, 128kbps, 44.1kHz, no padding, stereo. 프레임 크기 417 bytes, 1152 samples.
_FRAME_HEADER = bytes([0xFF, 0xFB, 0x90, 0x00])
_FRAME_SIZE = 417
_FRAME_S = 1152 / 44100


def silent_mp3_bytes(duration_s: float) -> bytes:
    frames = max(1, int(round(duration_s / _FRAME_S)))
    frame = _FRAME_HEADER + bytes(_FRAME_SIZE - len(_FRAME_HEADER))
    return frame * frames


def synth_response(text: str, char_s: float | None = None, space_s: float | None = None) -> dict:
    char_s = char_s if char_s is not None else float(os.environ.get("KAIDANZIP_FAKE_CHAR_S", "0.17"))
    space_s = space_s if space_s is not None else float(os.environ.get("KAIDANZIP_FAKE_SPACE_S", "0.06"))
    starts: list[float] = []
    ends: list[float] = []
    t = 0.0
    for ch in text:
        dur = space_s if ch.isspace() else char_s
        starts.append(round(t, 3))
        ends.append(round(t + dur, 3))
        t += dur
    total_s = t + 0.3  # 끝 무음 여유
    return {
        "audio_base64": base64.b64encode(silent_mp3_bytes(total_s)).decode("ascii"),
        "alignment": {
            "characters": list(text),
            "character_start_times_seconds": starts,
            "character_end_times_seconds": ends,
        },
        "normalized_alignment": None,
    }


def fake_response(text: str, speed: float = 1.0) -> dict:
    mode = os.environ.get("KAIDANZIP_FAKE_TTS", "")
    if mode == "synth":
        char_s = float(os.environ.get("KAIDANZIP_FAKE_CHAR_S", "0.17")) / speed
        space_s = float(os.environ.get("KAIDANZIP_FAKE_SPACE_S", "0.06")) / speed
        return synth_response(text, char_s=char_s, space_s=space_s)
    return json.loads(Path(mode).read_text(encoding="utf-8"))
