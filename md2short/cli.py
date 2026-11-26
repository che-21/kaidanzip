"""md2short CLI: run / render / status."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console

from . import pipeline
from .errors import EXIT_EXTERNAL, Md2ShortError

app = typer.Typer(add_completion=False, help="연출표 마크다운 + 장면 이미지 → 9:16 숏폼 MP4")
err = Console(stderr=True)


def _guard(fn, *args, **kwargs) -> None:
    try:
        code = fn(*args, **kwargs)
    except Md2ShortError as exc:
        err.print(f"[bold red]오류:[/bold red] {exc.message}")
        raise typer.Exit(exc.exit_code)
    except Exception as exc:  # 예상하지 못한 오류: job은 pipeline에서 failed로 기록됨
        err.print(f"[bold red]예상하지 못한 오류:[/bold red] {type(exc).__name__}: {exc}\n"
                  "job 폴더의 status.json과 logs/를 확인해 주세요.")
        raise typer.Exit(EXIT_EXTERNAL)
    raise typer.Exit(code)


@app.command()
def run(
    markdown: Path = typer.Argument(..., help="연출표 마크다운 (예: sample.md)"),
    images: Path | None = typer.Option(None, "--images", help="'번호_이름.png' 장면 이미지 폴더"),
    ai_images: bool = typer.Option(False, "--ai-images", help="모든 장면 이미지를 OpenAI로 생성 (장당 과금)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="렌더 전 확인 생략"),
    voice_id: str | None = typer.Option(None, "--voice-id", help="ElevenLabs voice_id (기본: docs/voice.md)"),
    skip_render: bool = typer.Option(False, "--skip-render", help="확인 단계까지만 실행 (테스트용)"),
    keep_staging: bool = typer.Option(False, "--keep-staging", help="render_public 폴더 유지"),
    speed: float = typer.Option(1.0, "--speed", help="말 속도 0.7~1.2 (1.0 기본, 낮을수록 느림·영상 길어짐)"),
    subtitle_split: str | None = typer.Option(None, "--subtitle-split", help="자막 분할 방식 auto|ai|rule (기본 auto: OpenAI 키가 있으면 AI)"),
) -> None:
    """새 job을 만들어 음성 생성부터 렌더·QC까지 실행한다."""
    _guard(pipeline.run, markdown, images, yes=yes, voice_id=voice_id, skip_render=skip_render, keep_staging=keep_staging, speed=speed, subtitle_split=subtitle_split, ai_images=ai_images)


@app.command()
def render(
    job_id: str = typer.Argument(..., help="다시 렌더할 job_id"),
    yes: bool = typer.Option(False, "--yes", "-y", help="렌더 전 확인 생략"),
    keep_staging: bool = typer.Option(False, "--keep-staging"),
) -> None:
    """기존 job의 음성·계획을 그대로 써서 다시 렌더한다 (TTS 호출 없음)."""
    _guard(pipeline.rerender, job_id, yes=yes, keep_staging=keep_staging)


@app.command("regen-image")
def regen_image(
    job_id: str = typer.Argument(..., help="job_id"),
    scene: int = typer.Option(..., "--scene", help="다시 만들 장면 번호"),
    prompt: str | None = typer.Option(None, "--prompt", help="새 프롬프트 (없으면 기존 프롬프트)"),
) -> None:
    """장면 이미지 1장을 AI로 다시 만든다. 이후 'md2short render <job_id>'로 다시 렌더한다."""
    _guard(pipeline.regen_image, job_id, scene, prompt)


@app.command()
def subtitles(
    markdown: Path = typer.Argument(..., help="연출표 마크다운"),
    subtitle_split: str | None = typer.Option(None, "--subtitle-split", help="auto|ai|rule"),
) -> None:
    """음성을 만들기 전에 자막이 어떻게 나뉘는지 미리 본다 (TTS 호출 없음)."""
    _guard(pipeline.preview_subtitles, markdown, subtitle_split)


@app.command()
def status(job_id: str = typer.Argument(...)) -> None:
    """job 상태를 출력한다."""
    try:
        data = pipeline.show_status(job_id)
    except Md2ShortError as exc:
        err.print(f"[bold red]오류:[/bold red] {exc.message}")
        raise typer.Exit(exc.exit_code)
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    app()
