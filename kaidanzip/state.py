"""파일 기반 Job 상태 머신 (status.json)."""

from __future__ import annotations

import json
import secrets
from datetime import date, datetime, timezone
from pathlib import Path

from .errors import StateError

FLOW = {
    "created": {"parsed"},
    "parsed": {"voice_generated"},
    "voice_generated": {"planned"},
    "planned": {"confirmed", "aborted"},
    "confirmed": {"final_rendered"},
    "final_rendered": {"qc_passed", "qc_failed"},
}
TERMINAL = {"qc_passed", "qc_failed", "failed", "aborted"}
NON_TERMINAL = set(FLOW)
RERENDER_FROM = {"planned", "confirmed", "aborted", "qc_passed", "qc_failed"}
RERENDER_FAILED_STAGES = {"confirm", "render", "qc"}


def new_job_id(today: date | None = None) -> str:
    d = today or date.today()
    return f"sf_{d:%Y%m%d}_{secrets.token_hex(3)}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_transition(current: str, target: str, via: str | None = None, failed_stage: str | None = None) -> None:
    if via == "rerender":
        ok = target == "planned" and (
            current in RERENDER_FROM or (current == "failed" and failed_stage in RERENDER_FAILED_STAGES)
        )
    elif target == "failed":
        ok = current in NON_TERMINAL
    else:
        ok = target in FLOW.get(current, set())
    if not ok:
        raise StateError(f"허용되지 않은 상태 전이입니다: {current} → {target}" + (f" (via {via})" if via else ""))


class JobState:
    def __init__(self, job_dir: Path):
        self.path = job_dir / "status.json"
        self.data = json.loads(self.path.read_text(encoding="utf-8"))

    @classmethod
    def create(cls, job_dir: Path, job_id: str, extra: dict) -> "JobState":
        job_dir.mkdir(parents=True, exist_ok=False)
        now = _now()
        data = {"job_id": job_id, "status": "created", "attempt": 1, "started_at": now, "updated_at": now,
                "history": [{"status": "created", "at": now}], **extra}
        (job_dir / "status.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return cls(job_dir)

    @property
    def status(self) -> str:
        return self.data["status"]

    def transition(self, target: str, via: str | None = None, failed_stage: str | None = None, **fields) -> None:
        validate_transition(self.status, target, via=via, failed_stage=self.data.get("failed_stage"))
        now = _now()
        entry = {"status": target, "at": now}
        if via:
            entry["via"] = via
        self.data["history"].append(entry)
        self.data["status"] = target
        self.data["updated_at"] = now
        if target == "failed":
            self.data["failed_stage"] = failed_stage
        elif via == "rerender":
            self.data.pop("failed_stage", None)
            self.data.pop("error", None)
        self.data.update(fields)
        self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
