"""Job 오케스트레이션: run(새 job) / rerender(기존 job 재렌더)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TextIO

from dotenv import load_dotenv
from rich.console import Console

from . import confirm as confirm_mod
from . import qc, render, voice
from .assets import provided_from_folder
from . import image_gen
from .errors import (
    EXIT_ABORTED, EXIT_OK, EXIT_QC_FAILED, ConfirmAborted, InputValidationError, Md2ShortError, PreflightError,
    StateError,
)
from .paths import PROJECT_ROOT, assets_dir, jobs_dir, remotion_dir
from .plan import build_plan
from .state import JobState, new_job_id, validate_transition
from .storyboard import Storyboard, parse_storyboard
from . import subtitles
from .tools import probe_video, resolve_ffprobe, resolve_remotion

console = Console()


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def preflight(need_key: bool, need_render: bool) -> None:
    if need_key and not os.environ.get("ELEVENLABS_API_KEY"):
        raise PreflightError("ELEVENLABS_API_KEY가 .env에 없습니다. 프로젝트 폴더의 .env 파일에 키를 넣어 주세요.")
    if need_render:
        resolve_remotion()
        cmd = resolve_ffprobe() + ["-version"]
        proc = subprocess.run(cmd, cwd=remotion_dir(), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        if proc.returncode != 0:
            raise PreflightError("ffprobe를 실행하지 못했습니다. 'cd remotion && npm ci'를 다시 실행해 주세요.\n" + proc.stderr[:300])


def _finish(job_dir: Path, state: JobState, edl: dict, words_doc: dict, props: dict,
            yes: bool, stdin: TextIO | None, keep_staging: bool, skip_render: bool, on_progress=None) -> int:
    """planned 상태에서 확인 → 렌더 → 복사 → QC."""
    try:
        confirm_mod.confirm(edl, job_dir, assume_yes=yes, stdin=stdin, console=console)
    except ConfirmAborted as exc:
        state.transition("aborted")
        console.print(f"[yellow]{exc.message}[/yellow]")
        return EXIT_ABORTED
    state.transition("confirmed")
    if skip_render:
        console.print(f"[cyan]--skip-render: 렌더 없이 종료합니다. job: {state.data['job_id']}[/cyan]")
        return EXIT_OK

    console.print("Remotion 렌더 중... (첫 실행은 브라우저 다운로드로 몇 분 걸릴 수 있습니다)")
    final = render.render(job_dir, keep_staging=keep_staging, on_progress=on_progress)
    state.transition("final_rendered")

    out = job_dir / "output" / "ret.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(final, out)

    report = qc.evaluate(probe_video(out), words_doc, props, job_dir)
    qc.write_report(job_dir, report)
    if report["passed"]:
        state.transition("qc_passed", qc_report="qc_report.json")
        console.print(f"[bold green]완료: {out}[/bold green]")
        return EXIT_OK
    state.transition("qc_failed", qc_report="qc_report.json")
    failed = [k for k, c in report["checks"].items() if not c["passed"]]
    console.print(f"[bold yellow]영상은 저장했지만 QC를 통과하지 못했습니다: {', '.join(failed)}[/bold yellow]\n{out}")
    return EXIT_QC_FAILED


def subtitle_mode(mode: str | None) -> str:
    mode = mode or os.environ.get("MD2SHORT_SUBTITLE_SPLIT", "auto")
    if mode not in ("auto", "ai", "rule"):
        raise PreflightError(f"--subtitle-split 값은 auto, ai, rule 중 하나여야 합니다: {mode}")
    return mode


def apply_subtitles(board: Storyboard, mode: str) -> dict:
    """장면마다 subtitle_chunks를 채우고 로그를 돌려준다 (대본 확정 단계, TTS 전)."""
    chunks, source, log = subtitles.split_scenes(board.scenes, mode)
    for s in board.scenes:
        s.subtitle_chunks = chunks[s.index]
        s.subtitle_source = source[s.index]
    log["result"] = {s.index: {"source": s.subtitle_source, "chunks": s.subtitle_chunks} for s in board.scenes}
    return log


def print_subtitles(board: Storyboard) -> None:
    label = {"manual": "수동", "ai": "AI", "rule": "규칙"}
    console.print("[bold]자막 분할[/bold] (고치려면 연출표 장면에 '- **자막 분할:** … / …' 줄을 넣으세요)")
    for s in board.scenes:
        console.print(f"  장면 {s.index} [{label.get(s.subtitle_source, s.subtitle_source)}]: " + " / ".join(s.subtitle_chunks))


def preview_subtitles(markdown: Path, mode: str | None = None) -> int:
    """음성 생성 전에 자막 분할만 확인한다 (TTS 호출 없음)."""
    load_dotenv(PROJECT_ROOT / ".env")
    if not markdown.is_file():
        raise PreflightError(f"연출표 파일을 찾을 수 없습니다: {markdown}")
    board = parse_storyboard(markdown.read_text(encoding="utf-8"))
    log = apply_subtitles(board, subtitle_mode(mode))
    print_subtitles(board)
    for idx, reason in log.get("fallbacks", {}).items():
        console.print(f"[yellow]장면 {idx}: AI 분할을 쓰지 못해 규칙 분할로 대신했습니다 ({reason})[/yellow]")
    console.print()
    console.print("연출표에 붙여 넣을 수 있는 형식:")
    for s in board.scenes:
        console.print(f"  장면 {s.index}: - **자막 분할:** " + " / ".join(s.subtitle_chunks), markup=False)
    return EXIT_OK


def _print_warnings(warnings: list[dict]) -> None:
    for w in warnings:
        msg = w.get("message") or f"[장면 {w.get('scene')}] 연출 문구를 cue로 바꾸지 못했습니다: {w.get('text')}"
        console.print(f"[yellow]경고: {msg}[/yellow]")


def apply_chunk_overrides(board: Storyboard, overrides: dict[int, tuple[list[str], str]]) -> None:
    """웹 화면 등에서 확정한 자막 덩어리를 장면에 적용한다 (수정한 장면은 source='manual')."""
    for s in board.scenes:
        if s.index in overrides:
            chunks, source = overrides[s.index]
            problem = subtitles.check_chunks(s.narration, chunks)
            if problem:
                raise InputValidationError(f"자막 분할이 올바르지 않습니다: {problem}", scene=s.index)
            s.subtitle_chunks, s.subtitle_source = list(chunks), source


def start_job(markdown_text: str, images: Path | None, split_mode: str, config: dict,
              overrides: dict[int, tuple[list[str], str]] | None = None,
              markdown_input: str = "", images_input: str = "",
              provided: dict[int, Path] | None = None, ai_images: bool = False,
              style: str = image_gen.DEFAULT_STYLE, prompts: dict[int, str] | None = None,
              on_image_progress=None, owner: str | None = None) -> tuple[Path, JobState, Storyboard, list]:
    """job을 만들고 대본 확정(parse + 자막 분할)까지 진행한다. 상태: parsed."""
    job_id = new_job_id()
    job_dir = jobs_dir() / job_id
    state = JobState.create(job_dir, job_id, {
        "markdown_input": markdown_input, "images_input": images_input, "config": config,
        **({"owner": owner} if owner else {}),
    })
    try:
        (job_dir / "inputs").mkdir(parents=True, exist_ok=True)
        (job_dir / "inputs" / "source.md").write_text(markdown_text, encoding="utf-8")
        board = parse_storyboard(markdown_text)
        if provided is None:
            provided = provided_from_folder(images, len(board.scenes)) if images is not None else {}
        imgs, image_log = image_gen.materialize_images(
            board.scenes, job_dir / "inputs" / "images", provided, ai_missing=ai_images,
            style=style, prompts=prompts, on_progress=on_image_progress)
        _dump(job_dir / "logs" / "images.json", image_log)
        overrides = overrides or {}
        apply_chunk_overrides(board, overrides)
        rest = Storyboard(title=board.title, scenes=[s for s in board.scenes if s.index not in overrides])
        log = apply_subtitles(rest, split_mode) if rest.scenes else {"mode": split_mode, "fallbacks": {}}
        log["result"] = {s.index: {"source": s.subtitle_source, "chunks": s.subtitle_chunks} for s in board.scenes}
        _dump(job_dir / "logs" / "subtitles.json", log)
        _dump(job_dir / "inputs" / "storyboard.json", {**board.model_dump(), "images": [i.model_dump() for i in imgs]})
        _dump(job_dir / "logs" / "parse.json",
              {"markdown": markdown_input, "images": images_input, "scenes": len(board.scenes), "valid": True})
        state.transition("parsed")
        return job_dir, state, board, imgs
    except Exception as exc:
        _mark_failed(state, "parse", exc)
        raise


def voice_and_plan(job_dir: Path, state: JobState, board: Storyboard, imgs: list, speed: float) -> tuple[dict, dict, dict, list]:
    """parsed → voice_generated → planned. (edl, words_doc, props, warnings)"""
    stage = "voice"
    try:
        words_doc = voice.synthesize(board, job_dir, speed)
        state.transition("voice_generated", script_chars=len(words_doc["text"]))
        stage = "plan"
        edl, props, warnings = build_plan(board, imgs, words_doc, job_dir, assets_dir())
        state.transition("planned")
        return edl, words_doc, props, warnings
    except Exception as exc:
        _mark_failed(state, stage, exc)
        raise


def finish(job_dir: Path, state: JobState, yes: bool = True, stdin: TextIO | None = None,
           keep_staging: bool = False, skip_render: bool = False, on_progress=None) -> int:
    """planned 상태 job을 확인 → 렌더 → QC까지 진행한다."""
    edl = _load(job_dir / "edit" / "edl.json")
    props = _load(job_dir / "edit" / "props.json")
    words_doc = _load(job_dir / "transcripts" / "words.json")
    try:
        return _finish(job_dir, state, edl, words_doc, props, yes, stdin, keep_staging, skip_render, on_progress)
    except Exception as exc:
        _mark_failed(state, _stage_for("render", state.status), exc)
        raise


def job_config(speed: float, fake: bool) -> dict:
    return {"voice_id": voice.voice_id(), "model_id": voice.MODEL_ID, "speed": speed, "fps": 30,
            "size": "1080x1920", "fake_tts": fake}


def run(markdown: Path, images: Path | None, yes: bool = False, voice_id: str | None = None,
        skip_render: bool = False, keep_staging: bool = False, stdin: TextIO | None = None,
        speed: float = 1.0, subtitle_split: str | None = None, ai_images: bool = False) -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    voice.validate_speed(speed)
    split_mode = subtitle_mode(subtitle_split)
    if voice_id:
        os.environ["MD2SHORT_VOICE_ID"] = voice_id
    fake = bool(os.environ.get("MD2SHORT_FAKE_TTS"))
    preflight(need_key=not fake, need_render=not skip_render)
    if images is None and not ai_images:
        raise PreflightError("--images 폴더를 지정하거나 --ai-images로 AI 이미지를 만들어 주세요.")
    if images is not None and ai_images:
        raise PreflightError("--images와 --ai-images는 함께 쓸 수 없습니다. 장면별로 섞으려면 웹 화면을 쓰세요.")
    image_gen.check_ready(ai_images)

    if not markdown.is_file():
        raise PreflightError(f"연출표 파일을 찾을 수 없습니다: {markdown}")

    job_dir, state, board, imgs = _start_with_echo(markdown, images, split_mode, job_config(speed, fake), ai_images)
    print_subtitles(board)
    console.print("ElevenLabs 음성 생성 중..." if not fake else "가짜 TTS(MD2SHORT_FAKE_TTS)로 음성 생성 중...")
    _, _, _, warnings = voice_and_plan(job_dir, state, board, imgs, speed)
    _print_warnings(warnings)
    return finish(job_dir, state, yes=yes, stdin=stdin, keep_staging=keep_staging, skip_render=skip_render)


def _start_with_echo(markdown: Path, images: Path | None, split_mode: str, config: dict, ai_images: bool = False):
    text = markdown.read_text(encoding="utf-8")

    def progress(n, total, scene):
        console.print(f"AI 이미지 생성 중... ({n}/{total}, 장면 {scene})")

    result = start_job(text, images, split_mode, config,
                       markdown_input=str(markdown.resolve()),
                       images_input=str(images.resolve()) if images else "AI",
                       ai_images=ai_images, on_image_progress=progress)
    console.print(f"job: [bold]{result[0].name}[/bold] → {result[0]}")
    return result


NON_TERMINAL = ("created", "parsed", "voice_generated", "planned", "confirmed", "final_rendered")


def _mark_failed(state: JobState, failed_stage: str, exc: Exception) -> None:
    """어떤 예외든 job을 failed(terminal)로 남긴다. 상태 기록 자체가 실패해도 원래 예외를 가리지 않는다."""
    if state.status not in NON_TERMINAL:
        return
    message = exc.message if isinstance(exc, Md2ShortError) else f"{type(exc).__name__}: {exc}"
    try:
        state.transition("failed", failed_stage=failed_stage, error=message)
    except Exception:
        pass


def _stage_for(stage: str, status: str) -> str:
    if stage != "render":
        return stage
    return {"planned": "confirm", "confirmed": "render", "final_rendered": "qc"}.get(status, "render")


def rerender(job_id: str, yes: bool = False, keep_staging: bool = False, stdin: TextIO | None = None,
             on_progress=None) -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    job_dir = jobs_dir() / job_id
    if not (job_dir / "status.json").is_file():
        raise StateError(f"job을 찾을 수 없습니다: {job_id}")
    state = JobState(job_dir)
    try:
        validate_transition(state.status, "planned", via="rerender", failed_stage=state.data.get("failed_stage"))
    except StateError:
        raise StateError(
            f"이 job({state.status}, 실패 단계: {state.data.get('failed_stage')})은 다시 렌더할 수 없습니다. "
            "음성 생성 이전 단계에서 실패한 job은 'md2short run'으로 새로 만들어 주세요."
        )
    preflight(need_key=False, need_render=True)
    render.verify_job_images(job_dir)

    attempt = int(state.data.get("attempt", 1))
    archive = job_dir / "edit" / f"attempt_{attempt}"
    for rel in ("edit/final.mp4", "qc_report.json", "output/ret.mp4"):
        src = job_dir / rel
        if src.is_file():
            archive.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(archive / Path(rel).name))
    state.transition("planned", via="rerender", attempt=attempt + 1)

    return finish(job_dir, state, yes=yes, stdin=stdin, keep_staging=keep_staging, on_progress=on_progress)


def regen_image(job_id: str, scene: int, prompt: str | None = None) -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    job_dir = jobs_dir() / job_id
    if not (job_dir / "inputs" / "storyboard.json").is_file():
        raise StateError(f"job을 찾을 수 없거나 대본 확정 전입니다: {job_id}")
    image_gen.check_ready(True)
    img = image_gen.regenerate_scene_image(job_dir, scene, prompt)
    console.print(f"장면 {scene} 이미지를 다시 만들었습니다: {job_dir / 'inputs' / 'images' / img.job_name}")
    console.print(f"다시 렌더하려면: md2short render {job_id}")
    return EXIT_OK


def show_status(job_id: str) -> dict:
    path = jobs_dir() / job_id / "status.json"
    if not path.is_file():
        raise StateError(f"job을 찾을 수 없습니다: {job_id}")
    return _load(path)


if sys.platform == "win32":  # 한글 콘솔 출력
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
