"""자동 QC (AC-10). 체크는 정확히 6개, 비용은 정보 필드."""

from __future__ import annotations

import json
import os
from fractions import Fraction
from pathlib import Path

from .timeutil import FPS, ms_to_frames, s_to_ms

WIDTH, HEIGHT = 1080, 1920
MIN_MS, MAX_MS = 45_000, 58_000
TAIL_TOLERANCE_MS = 1000
RENDER_TOLERANCE_FRAMES = 3  # ≈100ms @30fps

REQUIRED_FILES = [
    "inputs/source.md", "inputs/storyboard.json", "logs/parse.json",
    "audio/narration.mp3", "transcripts/words.json", "logs/tts_input.txt", "logs/elevenlabs_tts_raw.json",
    "edit/edl.json", "edit/props.json", "logs/plan.json", "logs/warnings.json",
    "logs/confirm.json",
    "edit/final.mp4", "logs/remotion.log",
    "output/ret.mp4",
]


def _check(passed: bool, value, threshold) -> dict:
    return {"passed": bool(passed), "value": value, "threshold": threshold}


def evaluate(stream: dict, words_doc: dict, props: dict, job_dir: Path) -> dict:
    width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
    fps = Fraction(stream.get("r_frame_rate", "0/1"))
    video_ms = s_to_ms(float(stream.get("duration", 0)))
    audio_ms = words_doc["audio_duration_ms"]
    last_end = words_doc["words"][-1]["end"] if words_doc["words"] else 0
    missing = [f for f in REQUIRED_FILES if not (job_dir / f).is_file()]

    checks = {
        "resolution": _check((width, height) == (WIDTH, HEIGHT), f"{width}x{height}", f"{WIDTH}x{HEIGHT}"),
        "fps": _check(fps == FPS, str(fps), FPS),
        "duration": _check(MIN_MS <= video_ms <= MAX_MS, video_ms, [MIN_MS, MAX_MS]),
        "tail_sync": _check(abs(last_end - audio_ms) <= TAIL_TOLERANCE_MS, abs(last_end - audio_ms), TAIL_TOLERANCE_MS),
        "render_length": _check(
            abs(ms_to_frames(video_ms) - props["durationInFrames"]) <= RENDER_TOLERANCE_FRAMES,
            abs(ms_to_frames(video_ms) - props["durationInFrames"]),
            RENDER_TOLERANCE_FRAMES,
        ),
        "artifacts": _check(not missing, missing, "all required files present"),
    }
    chars = len(words_doc.get("text", ""))
    rate = os.environ.get("MD2SHORT_EL_COST_PER_CHAR")
    cost = {"tts_chars": chars, "usd_per_char": float(rate) if rate else None,
            "usd_estimate": round(chars * float(rate), 4) if rate else None}
    return {
        "passed": all(c["passed"] for c in checks.values()),
        "checks": checks,
        "video_duration_ms": video_ms,
        "audio_duration_ms": audio_ms,
        "cost": cost,
    }


def write_report(job_dir: Path, report: dict) -> Path:
    path = job_dir / "qc_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
