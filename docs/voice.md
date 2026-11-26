# Voice 설정

## 기본 Voice ID

v1 한국어 기본 voice는 ElevenLabs premade voice **Brian**이다.

```text
nPczCjzI2devNBz1zQrb
```

- 코드 기준: `md2short/voice.py` `DEFAULT_VOICE_ID` (실행 시 `--voice-id` 또는 `MD2SHORT_VOICE_ID`로 변경 가능)
- 모델: `eleven_multilingual_v2` (한국어 읽기)

## 요금제 제약

- 현재 계정은 **무료 요금제**다. 무료 요금제에서는 Voice Library 음성을 API로 쓸 수 없다(HTTP 402 `paid_plan_required`).
  - 확인된 거절 사례(2026-11-26): `jB1Cifc2UQbq1gR3wnb0`, `v1jVu1Ky28piIPEJqRrm`
- premade voice(모든 계정에 기본 제공)만 쓸 수 있다. Brian으로 `sample.md` 실제 렌더를 확인했다(`jobs/sf_20261126_4a4e8c`, 44.7초).
- 현재 API 키는 음성 목록 조회(`GET /v1/voices`) 권한이 없어 401을 받는다. voice를 바꿀 때는 ElevenLabs 웹에서 premade voice ID를 확인해 지정한다.
- 유료 요금제로 올리면 Voice Library 음성 ID로 위 기본값을 바꿀 수 있다.
