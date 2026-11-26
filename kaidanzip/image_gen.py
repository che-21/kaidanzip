"""장면 이미지 준비: 사용자 업로드 + OpenAI 이미지 생성.

- 모든 장면 프롬프트에 같은 공통 화풍(style)을 붙여 그림체를 맞춘다.
- 생성 이미지는 job의 ``inputs/images/scene_NN.png``에 저장하고 sha256을 storyboard.json에 기록한다.
- ``KAIDANZIP_FAKE_IMAGES=1``이면 API 대신 어두운 단색 PNG를 만든다 (테스트·무료 리허설).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import struct
import zlib
from pathlib import Path

import httpx

from ._retry import request_with_retry
from .assets import SceneImage, image_size, sha256_of
from .errors import ExternalApiError, InputValidationError, PreflightError
from .storyboard import Scene

IMAGE_MODEL_DEFAULT = "gpt-image-2"
IMAGE_SIZE = "1024x1536"  # 세로 2:3 — Remotion에서 9:16 cover 크롭
IMAGE_QUALITY_DEFAULT = "medium"

DEFAULT_STYLE = (
    "Dark, eerie Korean horror illustration with a cinematic, realistic painterly look. "
    "Muted desaturated colors, deep shadows, cold moonlight, subtle film grain, heavy vignette. "
    "Vertical portrait composition with the main subject in the center. "
    "Keep exactly the same art style, color palette and lighting in every scene of this video. "
    "No text, no letters, no captions, no watermark, no gore, no blood."
)


def image_model() -> str:
    return os.environ.get("KAIDANZIP_IMAGE_MODEL", IMAGE_MODEL_DEFAULT)


def fake_mode() -> bool:
    return bool(os.environ.get("KAIDANZIP_FAKE_IMAGES"))


def build_prompt(scene: Scene, style: str = DEFAULT_STYLE) -> str:
    """공통 화풍 + 장면 화면 연출로 프롬프트를 만든다."""
    direction = scene.visual_direction or scene.narration
    return f"{style}\n\nScene {scene.index} — {scene.title}.\nVisual direction (Korean): {direction}"


def check_ready(need: bool) -> None:
    if need and not fake_mode() and not os.environ.get("OPENAI_API_KEY"):
        raise PreflightError("AI 이미지를 만들려면 .env에 OPENAI_API_KEY가 필요합니다.")


# ---------- 가짜 이미지 (의존성 없는 PNG) ----------

def _png_bytes(width: int, height: int, seed: str) -> bytes:
    h = hashlib.sha256(seed.encode("utf-8")).digest()
    base = (h[0] % 40 + 10, h[1] % 40 + 10, h[2] % 50 + 20)
    rows = bytearray()
    for y in range(height):
        k = y / max(1, height - 1)
        px = bytes(int(c * (1.2 - 0.8 * k)) for c in base)
        rows += b"\x00" + px * width
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b"")


# ---------- OpenAI ----------

def generate_image(prompt: str, out_path: Path, scene_no: int) -> dict:
    """이미지 1장을 만들어 out_path(PNG)에 저장하고 메타를 돌려준다."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if fake_mode():
        out_path.write_bytes(_png_bytes(216, 384, prompt))
        return {"model": "fake", "size": "216x384"}
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise PreflightError("AI 이미지를 만들려면 .env에 OPENAI_API_KEY가 필요합니다.")
    payload = {"model": image_model(), "prompt": prompt, "size": IMAGE_SIZE, "n": 1,
               "quality": os.environ.get("KAIDANZIP_IMAGE_QUALITY", IMAGE_QUALITY_DEFAULT)}
    try:
        with httpx.Client(timeout=240.0) as client:
            resp = request_with_retry(lambda: client.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {key}"}, json=payload))
    except httpx.HTTPError as exc:
        raise ExternalApiError(f"[장면 {scene_no}] OpenAI 이미지 API에 연결하지 못했습니다: {exc}") from exc
    if resp.status_code >= 400:
        text = resp.text[:400]
        if "moderation" in text or "safety" in text:
            raise ExternalApiError(
                f"[장면 {scene_no}] 이미지 요청이 OpenAI 안전 정책에 걸렸습니다. 화면 연출 문구를 덜 자극적으로 고쳐 다시 만들어 주세요.\n원문: {text}")
        raise ExternalApiError(f"[장면 {scene_no}] OpenAI 이미지 생성 실패(HTTP {resp.status_code}): {text}")
    data = resp.json()
    item = (data.get("data") or [{}])[0]
    if item.get("b64_json"):
        out_path.write_bytes(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        out_path.write_bytes(httpx.get(item["url"], timeout=120).content)
    else:
        raise ExternalApiError(f"[장면 {scene_no}] OpenAI 응답에 이미지가 없습니다.")
    return {"model": payload["model"], "size": IMAGE_SIZE, "quality": payload["quality"],
            "revised_prompt": item.get("revised_prompt"), "usage": data.get("usage")}


# ---------- 장면 이미지 확정 ----------

def materialize_images(
    scenes: list[Scene],
    dest: Path,
    provided: dict[int, Path],
    ai_missing: bool,
    style: str = DEFAULT_STYLE,
    prompts: dict[int, str] | None = None,
    on_progress=None,
) -> tuple[list[SceneImage], list[dict]]:
    """장면마다 업로드 이미지를 복사하거나 AI로 만든다. (SceneImage 목록, 생성 로그)"""
    prompts = prompts or {}
    missing = [s.index for s in scenes if s.index not in provided]
    if missing and not ai_missing:
        raise InputValidationError(
            f"이미지가 없는 장면이 있습니다: {', '.join(map(str, missing))}. 이미지를 올리거나 AI 이미지 생성을 켜 주세요.",
            scene=missing[0],
        )
    dest.mkdir(parents=True, exist_ok=True)
    result: list[SceneImage] = []
    log: list[dict] = []
    for n, scene in enumerate(scenes, start=1):
        if scene.index in provided:
            src = provided[scene.index]
            job_name = f"scene_{scene.index:02d}{src.suffix.lower()}"
            shutil.copy2(src, dest / job_name)
            source, prompt, meta = "upload", None, None
            original = src.name
        else:
            prompt = prompts.get(scene.index) or build_prompt(scene, style)
            job_name = f"scene_{scene.index:02d}.png"
            if on_progress:
                on_progress(n, len(scenes), scene.index)
            meta = generate_image(prompt, dest / job_name, scene.index)
            source, original = "ai", f"AI 생성 (장면 {scene.index})"
            log.append({"scene": scene.index, "prompt": prompt, **meta})
        size = image_size(dest / job_name)
        result.append(SceneImage(
            scene=scene.index, original_name=original, job_name=job_name, sha256=sha256_of(dest / job_name),
            width=size[0] if size else None, height=size[1] if size else None, source=source, prompt=prompt,
        ))
    return result, log


def regenerate_scene_image(job_dir: Path, scene_no: int, prompt: str | None = None) -> SceneImage:
    """job의 장면 이미지 1장을 AI로 다시 만들고 storyboard/edl/props의 참조를 갱신한다."""
    sb_path = job_dir / "inputs" / "storyboard.json"
    board = json.loads(sb_path.read_text(encoding="utf-8"))
    scene = next((s for s in board["scenes"] if s["index"] == scene_no), None)
    if scene is None:
        raise InputValidationError("그런 장면이 없습니다.", scene=scene_no)
    images = board["images"]
    entry = next(i for i in images if i["scene"] == scene_no)
    final_prompt = prompt or entry.get("prompt") or build_prompt(Scene(**scene))
    dest = job_dir / "inputs" / "images"
    new_name = f"scene_{scene_no:02d}.png"
    old_name = entry["job_name"]
    meta = generate_image(final_prompt, dest / new_name, scene_no)
    if old_name != new_name and (dest / old_name).exists():
        (dest / old_name).unlink()
    size = image_size(dest / new_name)
    updated = SceneImage(scene=scene_no, original_name=f"AI 생성 (장면 {scene_no})", job_name=new_name,
                         sha256=sha256_of(dest / new_name), width=size[0] if size else None,
                         height=size[1] if size else None, source="ai", prompt=final_prompt)
    images[images.index(entry)] = updated.model_dump()
    sb_path.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")

    for rel, key in (("edit/props.json", "image"), ("edit/edl.json", None)):
        path = job_dir / rel
        if not path.is_file():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        for s in doc.get("scenes", []):
            if s.get("index") == scene_no:
                if key:
                    s[key] = new_name
                else:
                    s["image"] = {"job_name": new_name, "original_name": updated.original_name,
                                  "width": updated.width, "height": updated.height}
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    log_path = job_dir / "logs" / "images.json"
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.is_file() else []
    log.append({"scene": scene_no, "prompt": final_prompt, "regenerated": True, **meta})
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return updated
