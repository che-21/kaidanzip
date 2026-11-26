"""Remotion 렌더 subprocess (AC-7, AC-8). 자막·합성은 전부 Remotion이 한다."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from .assets import sha256_of
from .errors import InputValidationError, RenderError
from .paths import remotion_dir
from .tools import resolve_remotion

COMPOSITION = "HorrorShort"
RENDER_TIMEOUT_S = 900


def verify_job_images(job_dir: Path) -> None:
    board = json.loads((job_dir / "inputs" / "storyboard.json").read_text(encoding="utf-8"))
    for img in board["images"]:
        path = job_dir / "inputs" / "images" / img["job_name"]
        if not path.is_file() or sha256_of(path) != img["sha256"]:
            raise InputValidationError(
                f"job 내부 이미지가 바뀌었거나 없습니다: {path.name}. 새 job으로 다시 만들어 주세요.",
                scene=img["scene"],
            )


def stage(job_dir: Path) -> Path:
    public = job_dir / "render_public"
    if public.exists():
        shutil.rmtree(public)
    public.mkdir(parents=True)
    shutil.copy2(job_dir / "audio" / "narration.mp3", public / "narration.mp3")
    for p in (job_dir / "inputs" / "images").iterdir():
        shutil.copy2(p, public / p.name)
    audio_assets = job_dir / "inputs" / "audio_assets"
    if audio_assets.is_dir():
        for p in audio_assets.iterdir():
            shutil.copy2(p, public / p.name)
    shutil.copy2(job_dir / "edit" / "props.json", public / "props.json")
    return public


PROGRESS_RE = re.compile(r"(Rendered|Encoded)\s+(\d+)/(\d+)")


def render(job_dir: Path, keep_staging: bool = False, on_progress=None) -> Path:
    """Remotion 렌더. on_progress(stage, done, total)로 진행률을 알린다."""
    public = stage(job_dir)
    out = (job_dir / "edit" / "final.mp4").resolve()
    cmd = resolve_remotion() + [
        "render", "src/index.ts", COMPOSITION, str(out),
        f"--props={(public / 'props.json').resolve()}",
        f"--public-dir={public.resolve()}",
        "--log=info",
    ]
    log_path = job_dir / "logs" / "remotion.log"
    lines: list[str] = []
    started = time.monotonic()
    proc = subprocess.Popen(
        cmd, cwd=remotion_dir(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    timed_out = False
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line)
        m = PROGRESS_RE.search(line)
        if m and on_progress:
            on_progress(m.group(1), int(m.group(2)), int(m.group(3)))
        if time.monotonic() - started > RENDER_TIMEOUT_S:
            proc.kill()
            timed_out = True
            break
    proc.wait()
    header = "CMD: " + " ".join(cmd) + f"\nEXIT: {proc.returncode}\n\n"
    log_path.write_text(header + "".join(lines), encoding="utf-8")
    if timed_out:
        raise RenderError(f"Remotion 렌더가 {RENDER_TIMEOUT_S}초 안에 끝나지 않았습니다. logs/remotion.log를 확인해 주세요.")
    if proc.returncode != 0 or not out.is_file():
        tail = "".join(lines).strip().splitlines()[-5:]
        raise RenderError("Remotion 렌더에 실패했습니다. logs/remotion.log를 확인해 주세요.\n" + "\n".join(tail))
    if not keep_staging:
        shutil.rmtree(public, ignore_errors=True)
    return out
