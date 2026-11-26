"""장면 이미지 매칭·복사, BGM/SFX 파일 탐색."""

from __future__ import annotations

import hashlib
import re
import shutil
import struct
from pathlib import Path

from pydantic import BaseModel

from .errors import InputValidationError

IMAGE_RE = re.compile(r"^(\d+)_.*\.(png|jpg|jpeg)$", re.IGNORECASE)
AUDIO_EXTS = (".mp3", ".wav")


class SceneImage(BaseModel):
    scene: int
    original_name: str
    job_name: str  # inputs/images/ 아래 ASCII 파일명
    sha256: str
    width: int | None = None
    height: int | None = None
    source: str = "upload"  # upload | ai
    prompt: str | None = None


def list_images(folder: Path) -> list[tuple[int, Path]]:
    if not folder.is_dir():
        raise InputValidationError(f"이미지 폴더를 찾을 수 없습니다: {folder}")
    found: list[tuple[int, Path]] = []
    for p in folder.iterdir():
        m = IMAGE_RE.match(p.name)
        if p.is_file() and m:
            found.append((int(m.group(1)), p))
    found.sort(key=lambda t: t[0])
    seen: set[int] = set()
    for num, p in found:
        if num in seen:
            raise InputValidationError(f"이미지 번호 {num}이(가) 중복됩니다: {p.name}")
        seen.add(num)
    return found


def image_size(path: Path) -> tuple[int, int] | None:
    """PNG/JPEG 헤더에서 (width, height)를 읽는다. 실패하면 None."""
    with path.open("rb") as f:
        head = f.read(26)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", head[16:24])
            return w, h
        if head[:2] != b"\xff\xd8":
            return None
        f.seek(2)
        while True:
            marker = f.read(2)
            if len(marker) < 2 or marker[0] != 0xFF:
                return None
            code = marker[1]
            if code in (0xD8, 0x01) or 0xD0 <= code <= 0xD7:
                continue
            seg_len = struct.unpack(">H", f.read(2))[0]
            if code in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                f.read(1)
                h, w = struct.unpack(">HH", f.read(4))
                return w, h
            f.seek(seg_len - 2, 1)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def provided_from_folder(folder: Path, scene_count: int) -> dict[int, Path]:
    """'번호_이름' 이미지를 번호 순서대로 장면 1..N에 대응시킨다 (개수가 같아야 함)."""
    images = list_images(folder)
    if len(images) != scene_count:
        raise InputValidationError(
            f"장면 수({scene_count})와 이미지 수({len(images)})가 다릅니다. "
            f"'{folder}' 폴더에 '번호_이름.png' 이미지를 장면 수만큼 넣거나, --ai-images로 AI 이미지를 만들어 주세요.",
            scene=min(scene_count, len(images)) + 1,
        )
    return {n: p for n, (_, p) in enumerate(images, start=1)}


def copy_scene_images(folder: Path, scene_count: int, dest: Path) -> list[SceneImage]:
    images = list_images(folder)
    if len(images) != scene_count:
        raise InputValidationError(
            f"장면 수({scene_count})와 이미지 수({len(images)})가 다릅니다. "
            f"'{folder}' 폴더에 '번호_이름.png' 이미지를 장면 수만큼 넣어 주세요.",
            scene=min(scene_count, len(images)) + 1,
        )
    dest.mkdir(parents=True, exist_ok=True)
    result: list[SceneImage] = []
    for scene_no, (_, src) in enumerate(images, start=1):
        job_name = f"scene_{scene_no:02d}{src.suffix.lower()}"
        target = dest / job_name
        shutil.copy2(src, target)
        size = image_size(target)
        result.append(
            SceneImage(
                scene=scene_no,
                original_name=src.name,
                job_name=job_name,
                sha256=sha256_of(target),
                width=size[0] if size else None,
                height=size[1] if size else None,
            )
        )
    return result


def find_sfx(assets: Path, key: str) -> Path | None:
    folder = assets / "sfx"
    if not folder.is_dir():
        return None
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS and p.stem.lower().startswith(key):
            return p
    return None


def find_bgm(assets: Path) -> Path | None:
    folder = assets / "bgm"
    if not folder.is_dir():
        return None
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.suffix.lower() == ".mp3":
            return p
    return None
