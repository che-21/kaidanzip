"""외부 도구 경로 해석 (Remotion CLI, ffprobe).

Windows의 ``npx.cmd``/``.cmd`` 배치 파일을 거치지 않도록 node로 Remotion CLI 진입 js를 직접 실행한다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .errors import PreflightError, RenderError
from .paths import remotion_dir


def resolve_node() -> str:
    node = shutil.which("node")
    if not node:
        raise PreflightError("Node.js를 찾을 수 없습니다. https://nodejs.org 에서 LTS 버전을 설치해 주세요.")
    return node


def remotion_cli_js() -> Path:
    pkg = remotion_dir() / "node_modules" / "@remotion" / "cli"
    manifest = pkg / "package.json"
    if not manifest.is_file():
        raise PreflightError(
            "Remotion이 설치되어 있지 않습니다. 'cd remotion && npm ci'를 먼저 실행해 주세요."
        )
    bin_field = json.loads(manifest.read_text(encoding="utf-8")).get("bin", {})
    rel = bin_field.get("remotion") if isinstance(bin_field, dict) else bin_field
    entry = pkg / (rel or "remotion-cli.js")
    if not entry.is_file():
        raise PreflightError(f"Remotion CLI 진입 파일을 찾지 못했습니다: {entry}")
    return entry


def resolve_remotion() -> list[str]:
    return [resolve_node(), str(remotion_cli_js())]


def resolve_ffprobe() -> list[str]:
    system = shutil.which("ffprobe")
    if system:
        return [system]
    return resolve_remotion() + ["ffprobe"]


def probe_video(path: Path) -> dict:
    cmd = resolve_ffprobe() + [
        "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,duration",
        "-of", "json", str(path),
    ]
    proc = subprocess.run(cmd, cwd=remotion_dir(), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if proc.returncode != 0:
        raise RenderError(f"ffprobe 실행에 실패했습니다: {proc.stderr.strip()[:300]}")
    out = proc.stdout
    start = out.find("{")
    if start < 0:
        raise RenderError(f"ffprobe 출력이 JSON이 아닙니다: {out[:200]}")
    data = json.loads(out[start:])
    streams = data.get("streams") or []
    if not streams:
        raise RenderError("영상 스트림을 찾지 못했습니다.")
    return streams[0]
