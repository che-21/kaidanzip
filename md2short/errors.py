"""한국어 오류 타입과 종료 코드 매핑."""

EXIT_OK = 0
EXIT_INPUT = 1
EXIT_QC_FAILED = 2
EXIT_ABORTED = 3
EXIT_EXTERNAL = 4


class Md2ShortError(Exception):
    exit_code = EXIT_EXTERNAL
    stage = "unknown"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InputValidationError(Md2ShortError):
    """연출표·이미지·사용자 입력 문제. TTS 호출 전에 발생한다."""

    exit_code = EXIT_INPUT
    stage = "parse"

    def __init__(self, message: str, scene: int | None = None):
        prefix = f"[장면 {scene}] " if scene is not None else ""
        super().__init__(prefix + message)
        self.scene = scene


class PreflightError(Md2ShortError):
    exit_code = EXIT_INPUT
    stage = "preflight"


class ConfirmAborted(Md2ShortError):
    exit_code = EXIT_ABORTED
    stage = "confirm"


class ExternalApiError(Md2ShortError):
    exit_code = EXIT_EXTERNAL
    stage = "voice"


class AlignmentMismatchError(Md2ShortError):
    exit_code = EXIT_EXTERNAL
    stage = "voice"


class RenderError(Md2ShortError):
    exit_code = EXIT_EXTERNAL
    stage = "render"


class StateError(Md2ShortError):
    exit_code = EXIT_INPUT
    stage = "state"
