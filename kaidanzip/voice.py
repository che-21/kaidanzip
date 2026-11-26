"""ElevenLabs TTS (with-timestamps) → narration.mp3 + words.json (AC-5).

words.json은 모든 시간의 단일 진실원이다. 단어 시간은 TTS 응답의 문자 alignment를
그대로 집계하고, 오디오 길이는 mp3 파일에서 잰다. 어떤 값도 추정하지 않는다.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import httpx
from mutagen.mp3 import MP3

from . import fake_tts
from ._retry import request_with_retry
from .errors import AlignmentMismatchError, ExternalApiError, InputValidationError, PreflightError
from .storyboard import Storyboard, nfc
from .timeutil import s_to_ms

DEFAULT_VOICE_ID = "nPczCjzI2devNBz1zQrb"  # docs/voice.md (premade Brian, 무료 요금제)
MODEL_ID = "eleven_multilingual_v2"
OUTPUT_FORMAT = "mp3_44100_128"
API_BASE = "https://api.elevenlabs.io"
SPEED_MIN, SPEED_MAX = 0.7, 1.2  # ElevenLabs voice_settings.speed 허용 범위


def voice_id() -> str:
    return os.environ.get("KAIDANZIP_VOICE_ID") or DEFAULT_VOICE_ID


def build_request_text(board: Storyboard) -> tuple[str, list[int]]:
    """장면 나레이션을 공백 1칸으로 이어 붙이고, 장면별 시작 문자 offset을 돌려준다."""
    parts: list[str] = []
    starts: list[int] = []
    pos = 0
    for scene in board.scenes:
        if parts:
            pos += 1  # 구분 공백
        starts.append(pos)
        text = nfc(scene.narration)
        parts.append(text)
        pos += len(text)
    return nfc(" ".join(parts)), starts


def validate_speed(speed: float) -> float:
    if not (SPEED_MIN <= speed <= SPEED_MAX):
        raise InputValidationError(f"말 속도(--speed)는 {SPEED_MIN}~{SPEED_MAX} 사이여야 합니다: {speed}")
    return speed


def request_body(text: str, speed: float) -> dict:
    body: dict = {"text": text, "model_id": MODEL_ID}
    if speed != 1.0:
        body["voice_settings"] = {"speed": speed}
    return body


def call_elevenlabs(text: str, vid: str, speed: float = 1.0) -> dict:
    if os.environ.get("KAIDANZIP_FAKE_TTS"):
        return fake_tts.fake_response(text, speed)
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise PreflightError("ELEVENLABS_API_KEY가 .env에 없습니다. 프로젝트 폴더의 .env 파일에 키를 넣어 주세요.")
    url = f"{API_BASE}/v1/text-to-speech/{vid}/with-timestamps"
    with httpx.Client(timeout=60.0) as client:
        try:
            resp = request_with_retry(
                lambda: client.post(
                    url,
                    params={"output_format": OUTPUT_FORMAT},
                    headers={"xi-api-key": key, "Content-Type": "application/json"},
                    json=request_body(text, speed),
                )
            )
        except httpx.HTTPError as exc:
            raise ExternalApiError(f"ElevenLabs에 연결하지 못했습니다(재시도 3회 실패): {exc}") from exc
    if resp.status_code == 401:
        raise ExternalApiError("ElevenLabs API 키가 올바르지 않습니다(401). .env의 ELEVENLABS_API_KEY를 확인해 주세요.")
    if resp.status_code == 402:
        raise ExternalApiError(
            f"ElevenLabs 요금제에서 이 voice({vid})를 API로 쓸 수 없습니다(402). "
            "유료 요금제로 올리거나, --voice-id 또는 .env의 KAIDANZIP_VOICE_ID로 계정에서 쓸 수 있는 기본(premade) voice를 지정해 주세요.\n"
            f"원문: {resp.text[:300]}"
        )
    if resp.status_code >= 400:
        raise ExternalApiError(f"ElevenLabs 요청이 실패했습니다(HTTP {resp.status_code}): {resp.text[:300]}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise ExternalApiError(f"ElevenLabs 응답이 JSON이 아닙니다: {resp.text[:200]}") from exc
    if "audio_base64" not in data:
        raise ExternalApiError("ElevenLabs 응답에 audio_base64가 없습니다.")
    return data


def aggregate_words(text: str, alignment: dict) -> list[dict]:
    chars = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]
    words: list[dict] = []
    i = 0
    n = len(chars)
    while i < n:
        if chars[i].isspace():
            i += 1
            continue
        j = i
        while j + 1 < n and not chars[j + 1].isspace():
            j += 1
        words.append(
            {
                "text": text[i : j + 1],
                "start": s_to_ms(starts[i]),
                "end": s_to_ms(ends[j]),
                "char_start": i,
                "char_end": j + 1,
            }
        )
        i = j + 1
    return words


def check_alignment(text: str, alignment: dict | None, diff_path: Path) -> None:
    if not alignment or "characters" not in alignment:
        raise AlignmentMismatchError("ElevenLabs 응답에 alignment가 없습니다.")
    got = "".join(alignment["characters"])
    if got != text:
        diff_path.write_text(f"REQUEST:\n{text}\n\nALIGNMENT:\n{got}\n", encoding="utf-8")
        raise AlignmentMismatchError(
            f"ElevenLabs alignment 문자열이 요청 텍스트와 다릅니다. 차이는 {diff_path}에 저장했습니다."
        )


def synthesize(board: Storyboard, job_dir: Path, speed: float = 1.0) -> dict:
    text, scene_starts = build_request_text(board)
    vid = voice_id()
    logs = job_dir / "logs"
    (logs / "tts_input.txt").write_text(text, encoding="utf-8")

    data = call_elevenlabs(text, vid, speed)

    raw = {k: v for k, v in data.items() if k != "audio_base64"}
    raw["_request"] = {"voice_id": vid, "model_id": MODEL_ID, "output_format": OUTPUT_FORMAT, "speed": speed, "chars": len(text)}
    (logs / "elevenlabs_tts_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    check_alignment(text, data.get("alignment"), logs / "alignment_diff.txt")

    audio_path = job_dir / "audio" / "narration.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(base64.b64decode(data["audio_base64"]))
    duration_ms = s_to_ms(MP3(audio_path).info.length)

    words_doc = {
        "language_code": "kor",
        "audio_duration_ms": duration_ms,
        "tts_speed": speed,
        "text": text,
        "scene_char_starts": scene_starts,
        "words": aggregate_words(text, data["alignment"]),
    }
    out = job_dir / "transcripts" / "words.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(words_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return words_doc
