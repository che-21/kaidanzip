"""프로젝트 경로 해석. 테스트는 환경 변수로 위치를 바꿀 수 있다."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def jobs_dir() -> Path:
    return Path(os.environ.get("KAIDANZIP_JOBS_DIR", PROJECT_ROOT / "jobs")).resolve()


def assets_dir() -> Path:
    return Path(os.environ.get("KAIDANZIP_ASSETS_DIR", PROJECT_ROOT / "assets")).resolve()


def remotion_dir() -> Path:
    return Path(os.environ.get("KAIDANZIP_REMOTION_DIR", PROJECT_ROOT / "remotion")).resolve()
