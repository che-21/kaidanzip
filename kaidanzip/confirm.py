"""렌더 전 사람 확인 단계 (AC-9)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TextIO

from rich.console import Console
from rich.table import Table

from .errors import ConfirmAborted, InputValidationError
from .timeutil import format_seconds as _sec

MIN_MS = 45_000
MAX_MS = 58_000
TARGET_MS = 50_000
SPEED_MIN, SPEED_MAX = 0.7, 1.2


def suggest_speed(total_ms: int, current_speed: float = 1.0) -> float | None:
    """규격을 벗어난 길이를 목표(50초)에 맞추는 --speed 값. 범위 안이면 None.

    말 속도와 길이가 반비례한다는 근사다. 정확한 길이는 다시 만든 음성으로 확인한다.
    """
    if MIN_MS <= total_ms <= MAX_MS or total_ms <= 0:
        return None
    s = round(current_speed * total_ms / TARGET_MS, 2)
    return min(SPEED_MAX, max(SPEED_MIN, s))


def build_table(edl: dict) -> Table:
    table = Table(title="렌더 전 확인 — 장면 타이밍 비교", show_lines=False)
    for col in ("장면", "이미지", "해상도", "목표(연출표)", "실제(음성 기준)", "모션", "효과음"):
        table.add_column(col)
    for s in edl["scenes"]:
        img = s["image"]
        res = f"{img['width']}×{img['height']}" if img.get("width") else "?"
        sfx = ", ".join(f"{x['key']}({'O' if x['applied'] else '없음'})" for x in s["sfx"]) or "-"
        motion = s["motion"] + ("+" + "+".join(s["effects"]) if s["effects"] else "")
        table.add_row(
            str(s["index"]), img["original_name"], res,
            f"{s['target_s'][0]}~{s['target_s'][1]}초",
            f"{_sec(s['start_ms'])}~{_sec(s['end_ms'])}초",
            motion, sfx,
        )
    return table


def confirm(edl: dict, job_dir: Path, assume_yes: bool, stdin: TextIO | None = None, console: Console | None = None) -> None:
    console = console or Console()
    stdin = stdin or sys.stdin
    total_ms = edl["audio_duration_ms"]
    console.print(build_table(edl))
    for s in edl["scenes"]:
        if s.get("subtitle_chunks"):
            console.print(f"  장면 {s['index']} 자막 [{s.get('subtitle_source', 'rule')}]: " + " / ".join(s["subtitle_chunks"]), markup=False)
    in_range = MIN_MS <= total_ms <= MAX_MS
    style = "green" if in_range else "bold red"
    note = "" if in_range else " — 규격을 벗어납니다. 렌더하면 QC 실패로 기록됩니다."
    console.print(f"[{style}]총 길이 {_sec(total_ms)}초 (규격 {_sec(MIN_MS)}~{_sec(MAX_MS)}초){note}[/{style}]")
    hint = suggest_speed(total_ms, edl.get("tts_speed", 1.0))
    if hint is not None:
        console.print(f"[yellow]제안: n을 누르고 --speed {hint} 로 다시 실행하면 약 {_sec(TARGET_MS)}초에 가까워집니다 (음성 재생성, 소액 과금).[/yellow]")

    record = {"total_ms": total_ms, "in_range": in_range, "suggested_speed": hint, "assume_yes": assume_yes, "answer": None}
    log = job_dir / "logs" / "confirm.json"
    try:
        if assume_yes:
            record["answer"] = "yes(--yes)"
            return
        console.print("이대로 렌더할까요? [y/n]: ", end="")
        line = stdin.readline()
        if line == "":
            record["answer"] = "EOF"
            raise InputValidationError("확인 입력을 받지 못했습니다(EOF). 자동 실행이라면 --yes 옵션을 붙여 주세요.")
        answer = line.strip().lower()
        record["answer"] = answer
        if answer in ("y", "yes"):
            return
        if answer in ("n", "no"):
            raise ConfirmAborted("사용자가 렌더를 취소했습니다. 'kaidanzip render <job_id>'로 나중에 렌더할 수 있습니다.")
        raise InputValidationError(f"'{answer}'는 올바른 응답이 아닙니다. y 또는 n을 입력해 주세요.")
    finally:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
