"""화면 연출·효과음 문구 → cue 키워드 매칭 (AC-4). LLM 해석 없음, 결정론."""

from __future__ import annotations

import re

# base motion: 장면당 1개. 앞쪽일수록 우선순위가 높다. 아무것도 안 맞으면 zoomIn.
BASE_MOTIONS: list[tuple[str, re.Pattern]] = [
    ("fadeOut", re.compile(r"페이드\s?아웃|어두워")),
    ("pan", re.compile(r"패닝")),
    ("zoomIn", re.compile(r"줌인|확대")),
]
DEFAULT_MOTION = "zoomIn"

# effect: 0개 이상, 겹쳐 적용.
EFFECTS: list[tuple[str, re.Pattern]] = [
    ("shake", re.compile(r"흔들")),
    ("glitch", re.compile(r"글리치|노이즈")),
]

# SFX: 0개 이상, 사전 순서대로. silence는 파일이 아니라 BGM duck.
SFX_KEYS: list[tuple[str, re.Pattern]] = [
    ("knock", re.compile(r"노크|두드리")),
    ("wind", re.compile(r"바람")),
    ("heartbeat", re.compile(r"심장")),
    ("scratch", re.compile(r"긁")),
    ("breath", re.compile(r"숨소리")),
    ("drone", re.compile(r"저음|울림|울리")),
    ("silence", re.compile(r"정적|끊김")),
]
SILENCE_KEY = "silence"
SILENCE_DUCK_FRAMES = 30


def match_motion(visual: str) -> tuple[str, list[str], dict]:
    base = DEFAULT_MOTION
    reason: dict = {"base": "default"}
    for name, pat in BASE_MOTIONS:
        m = pat.search(visual)
        if m:
            base = name
            reason["base"] = m.group(0)
            break
    effects = []
    for name, pat in EFFECTS:
        m = pat.search(visual)
        if m:
            effects.append(name)
            reason[name] = m.group(0)
    return base, effects, reason


def match_sfx(sfx_text: str) -> tuple[list[str], dict, list[str]]:
    keys: list[str] = []
    reason: dict = {}
    for name, pat in SFX_KEYS:
        m = pat.search(sfx_text)
        if m:
            keys.append(name)
            reason[name] = m.group(0)
    unmatched = []
    for segment in re.split(r"\s*\+\s*", sfx_text):
        seg = segment.strip()
        if seg and not any(pat.search(seg) for _, pat in SFX_KEYS):
            unmatched.append(seg)
    return keys, reason, unmatched
