"""시간 단위 변환 — 프로젝트 전체에서 유일한 변환 지점 (AGENTS.md §4.2).

- ``ms_to_frames``: ms → frame. 역함수(frame → ms)는 의도적으로 두지 않는다.
  비교가 필요하면 ms 값을 frame으로 바꿔 frame끼리 비교한다.
- ``s_to_ms``: 초(float, API/ffprobe/mutagen 응답) → 정수 ms.
"""

FPS = 30


def ms_to_frames(ms: int) -> int:
    """정수 ms를 가장 가까운 frame으로 변환한다 (half-up, 정수 연산)."""
    if ms < 0:
        raise ValueError(f"음수 시간은 변환할 수 없습니다: {ms}ms")
    return (int(ms) * FPS + 500) // 1000


def s_to_ms(sec: float) -> int:
    """초 단위 실수를 정수 ms로 변환한다."""
    return int(round(float(sec) * 1000))


def format_seconds(ms: int) -> str:
    """사람이 읽는 표시 전용 문자열 (예: 49.3). 계산에 쓰지 않는다."""
    return f"{ms / 1000:.1f}"
