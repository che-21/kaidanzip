# MD2Short 시스템 설계 (v1)

> 제품 요구(WHAT/WHY)는 [`PRD.md`](PRD.md), 작업 원칙은 [`../AGENTS.md`](../AGENTS.md)를 따른다. 이 문서는 HOW를 다룬다.
> v1 범위 밖의 이전 설계는 문서 끝 `v2-backlog` 절에만 남긴다.

## 1. 핵심 설계 원칙

### 1.1 레이어 분리

| 레이어 | 구성 | 입력 | 출력 | 금지 |
| --- | --- | --- | --- | --- |
| 계획 (Python) | `md2short` 패키지 | 연출표 md, 장면 이미지, `words.json` | `edl.json`, `props.json` | 렌더링 |
| 음성 | ElevenLabs TTS `with-timestamps` | 대본 텍스트 | `narration.mp3`, 문자 alignment → `words.json` | 시간 추정·편집 판단 |
| 비주얼 합성 | Remotion 4.x (`node …/@remotion/cli/remotion-cli.js render`) | `props.json`, job 내부 미디어 | `edit/final.mp4` (자막 포함) | 시간 계산·편집 판단·외부 API 호출 |

레이어 간 통신은 디스크의 JSON(`words.json`, `edl.json`, `props.json`)으로만 한다.

### 1.2 단일 진실원
- `transcripts/words.json`이 모든 시간의 기준이다. 연출표의 `[a~b초]`는 확인 표의 비교용으로만 쓴다.
- ms→frame 변환은 `md2short.timeutil.ms_to_frames` 하나뿐이다(역함수 없음). 초→ms는 `s_to_ms` 하나뿐이다.
- `props.json`의 모든 시간 필드는 frame 정수다. Remotion 코드에는 시간 단위 변환식이 없다.

### 1.3 결정론
같은 연출표·이미지·`words.json`·자막 분할이면 같은 `props.json`이 나온다(바이트 동일). 연출 cue는 키워드 사전 매칭으로만 만든다. 유일한 LLM 사용처는 자막 분할(선택)이며, 결과는 `storyboard.json`에 고정되고 규칙 검사를 통과한 경우에만 쓴다. 화면 흔들림·글리치는 Remotion `random(seed)`로 결정론적이다.

### 1.4 자막은 Remotion 단독 책임
FFmpeg `subtitles` filter, burn-in, overlay는 쓰지 않는다. `output/ret.mp4`는 `edit/final.mp4`를 그대로 복사한 것이다.

### 1.5 비싼 호출 전에 실패
pre-flight(키·Node·Remotion·ffprobe) → 연출표/이미지 검증이 모두 끝난 뒤에만 ElevenLabs를 호출한다.

## 2. 시스템 아키텍처

### 2.1 실행 흐름

```text
uv run md2short run sample.md --images emotion/ [--yes] [--speed 0.7~1.2]
  ├─ pre-flight: ELEVENLABS_API_KEY, node, remotion CLI js, ffprobe -version
  ├─ job 생성: jobs/sf_YYYYMMDD_<6hex>/status.json (created)
  ├─ [parse]  storyboard.parse_storyboard + assets.copy_scene_images
  │           + subtitles.split_scenes (수동 "/" > AI(검증) > 규칙) → logs/subtitles.json
  │           → inputs/source.md, inputs/storyboard.json, inputs/images/scene_NN.png, logs/parse.json   (parsed)
  ├─ [voice]  voice.synthesize: 장면 나레이션을 공백으로 join → ElevenLabs with-timestamps (mp3_44100_128, speed≠1.0이면 voice_settings.speed)
  │           → alignment 문자열 == 요청 텍스트 hard assert → audio/narration.mp3, transcripts/words.json
  │           → logs/tts_input.txt, logs/elevenlabs_tts_raw.json                                     (voice_generated)
  ├─ [plan]   plan.build_plan: 장면 구간·자막 chunk·강조 span·cue → edit/edl.json, edit/props.json
  │           → logs/plan.json, logs/warnings.json, inputs/audio_assets/                             (planned)
  ├─ [confirm] confirm.confirm: 타이밍 비교 표 + y/n (--yes 생략)                                    (confirmed | aborted)
  ├─ [render] render.render: jobs/<id>/render_public/ staging → Remotion render → edit/final.mp4   (final_rendered)
  ├─ copy     edit/final.mp4 → output/ret.mp4
  └─ [qc]     qc.evaluate → qc_report.json                                                          (qc_passed | qc_failed)

uv run md2short render <job_id> [--yes]   # TTS 없이 confirm → render → qc 재실행
uv run md2short subtitles sample.md      # TTS 없이 자막 분할 미리보기
uv run md2short status <job_id>
```

### 2.2 Python 모듈 구성

| 모듈 | 역할 |
| --- | --- |
| `md2short.cli` | Typer `run` / `render` / `status`, 오류 → 종료 코드 |
| `md2short.pipeline` | job 오케스트레이션, pre-flight, 재렌더(attempt 보관) |
| `md2short.storyboard` | 연출표 파싱, NFC 정규화, 강조어 정규화 매칭(원문 offset 역매핑) |
| `md2short.assets` | 이미지 번호순 매칭·복사·sha256·해상도, BGM/SFX 탐색 |
| `md2short.voice` | ElevenLabs 호출, alignment 검사, 문자→단어 집계, mutagen 길이 측정 |
| `md2short.fake_tts` | `MD2SHORT_FAKE_TTS`(synth 또는 응답 JSON 경로) — 테스트·무료 리허설 |
| `md2short._retry` | 429/5xx/timeout 3회 재시도, 0.5/1.0/2.0s backoff |
| `md2short.subtitles` | 자막 덩어리 분할: 수동(`자막 분할` 필드) > OpenAI(규칙 검증) > 규칙 기반. 규칙 1~5 |
| `md2short.image_gen` | 장면 이미지: 업로드 복사 또는 OpenAI 이미지 생성(`gpt-image-2`, 1024×1536, 공통 화풍 + 장면 연출), 장면별 재생성, `MD2SHORT_FAKE_IMAGES` |
| `md2short.github_auth` | 웹 화면 GitHub OAuth 로그인: HMAC 서명 state(10분), 코드→토큰 교환, `/user` 조회, 허용 목록(기본 거부). 토큰 미저장 |
| `webapp/app.py` | Streamlit 로컬 웹 화면: 대본 확인 → 이미지 확인 → 음성·타이밍 → 영상 (pipeline 단계 함수 `start_job` / `voice_and_plan` / `finish` / `rerender` 호출) |
| `md2short.cues` | 화면 연출·효과음 키워드 사전 |
| `md2short.plan` | 장면 frame 구간, subtitle_chunks → 단어 대응·표시 구간, 강조 span, props/edl 생성 |
| `md2short.confirm` | 렌더 전 확인 표와 y/n, 길이 규격 이탈 시 `--speed` 제안(목표 50초, 반비례 근사) |
| `md2short.state` | `status.json` 상태 머신, rerender 전이 |
| `md2short.tools` | node 직접 실행으로 Remotion CLI·ffprobe 해석(`.cmd` 비경유) |
| `md2short.render` | staging, Remotion subprocess, `logs/remotion.log` |
| `md2short.qc` | QC 6개 체크 + 비용 정보 |
| `md2short.timeutil` | `FPS=30`, `ms_to_frames`, `s_to_ms`, 표시용 `format_seconds` |

### 2.3 Remotion 구성 (`remotion/src/`)

| 파일 | 책임 |
| --- | --- |
| `index.ts` | `registerRoot` |
| `Root.tsx` | composition `HorrorShort`, 1080×1920, 30fps, `calculateMetadata`가 `props.durationInFrames`를 그대로 사용 |
| `HorrorShort.tsx` | SceneLayer + Captions + AudioLayer |
| `SceneLayer.tsx` | 장면별 `<Sequence>`, `<Img objectFit=cover>`, motion(zoomIn/pan/fadeOut), effect(shake/glitch), 전 장면 비네팅 |
| `Captions.tsx` | chunk별 `<Sequence>`, 흰 굵은 글씨 + 검은 외곽선, 강조 span `#E5141B`, 하단 22%, 좌 8% / 우 15% 여백 |
| `AudioLayer.tsx` | 내레이션, BGM(loop, 0.18, silence duck), SFX `<Sequence>` |
| `types.ts` | props 계약 |

버전: `remotion`, `@remotion/cli` = `4.0.543` (exact pin, `npm ci`). 렌더는 job별 `--public-dir`를 써서 `remotion/public`에 아무것도 쌓지 않는다.

## 3. Job 상태 머신

```text
created → parsed → voice_generated → planned → confirmed → final_rendered → qc_passed | qc_failed
non-terminal → failed (failed_stage ∈ parse | voice | plan | confirm | render | qc)
planned → aborted
terminal(run 기준) = {qc_passed, qc_failed, failed, aborted}
rerender: {planned, confirmed, aborted, qc_passed, qc_failed, failed[confirm|render|qc]} → planned  (history.via = "rerender")
```

- `status.json`: `job_id`, `status`, `attempt`, `failed_stage`, `error`, append-only `history[{status, at, via?}]`, `config`.
- 재렌더 전 이전 결과(`edit/final.mp4`, `qc_report.json`, `output/ret.mp4`)를 `edit/attempt_<n>/`으로 옮긴다.
- `--skip-render`는 `confirmed`(non-terminal)에서 exit 0으로 끝나는 테스트 모드다.

### 3.1 Job ID와 경로
Job ID는 `sf_<YYYYMMDD>_<6 hex>`다. 모든 산출물은 `jobs/<job_id>/` 기준 상대 경로다.

### 3.2 단계별 필수 산출물

| status | 필수 파일 |
| --- | --- |
| parsed | `inputs/source.md`, `inputs/storyboard.json`, `inputs/images/`, `logs/parse.json` |
| voice_generated | `audio/narration.mp3`, `transcripts/words.json`, `logs/tts_input.txt`, `logs/elevenlabs_tts_raw.json` |
| planned | `edit/edl.json`, `edit/props.json`, `logs/plan.json`, `logs/warnings.json` |
| confirmed / aborted | `logs/confirm.json` |
| final_rendered | `edit/final.mp4`, `logs/remotion.log` |
| qc_* | `output/ret.mp4`, `qc_report.json` |

### 3.3 종료 코드
`0` 성공(qc_passed 또는 --skip-render) · `1` 입력·pre-flight·상태 오류 · `2` QC 실패(영상은 저장) · `3` 사용자가 n · `4` 외부 API·alignment·렌더 실패.

## 4. 데이터 모델

### 4.1 연출표 입력

```markdown
## 장면 N [a~b초] : 제목
- **나레이션:** 문장
- **자막 강조(빨간색):** 강조어1, 강조어2
- **화면 연출:** 설명
- **효과음(SFX):** 설명 + 설명
```

강조어는 `,`로 나누고, 공백과 `,.!?…·()-~“”‘’"'`를 지운 뒤 나레이션의 부분 문자열이어야 한다. 강조 색은 일치한 글자에만 칠한다(조사 제외).

### 4.2 `words.json`

```json
{
  "language_code": "kor",
  "audio_duration_ms": 48230,
  "tts_speed": 1.0,
  "text": "밤에 가족 목소리가 들려도, …",
  "scene_char_starts": [0, 27, 102, 170, 231, 300],
  "words": [{"text": "밤에", "start": 0, "end": 340, "char_start": 0, "char_end": 2}]
}
```

`audio_duration_ms`는 mp3 실측(mutagen)이다.

### 4.3 `props.json` (`jobs/<id>/edit/props.json`, 모든 시간은 frame)

```json
{
  "durationInFrames": 1447,
  "narration": "narration.mp3",
  "bgm": {"file": "bgm.mp3", "volume": 0.18, "ducks": [{"fromFrame": 612, "durationInFrames": 30}]},
  "scenes": [{"index": 1, "image": "scene_01.png", "fromFrame": 0, "durationInFrames": 114, "motion": "zoomIn", "effects": []}],
  "captions": [{"fromFrame": 0, "durationInFrames": 40, "spans": [{"text": "절대", "highlight": true}]}],
  "sfx": [{"file": "sfx_knock.mp3", "fromFrame": 0}]
}
```

자막 구간: 각 `subtitle_chunks` 덩어리의 첫 어절 `start` ~ 마지막 어절 `end` (frame 변환 후 장면 안으로 제한). 덩어리 사이 쉼에는 자막이 없다.

장면 구간: 장면 k는 그 장면 첫 단어의 `start`부터 다음 장면 첫 단어 `start`까지다(장면 1은 0부터, 마지막 장면은 오디오 끝까지). `Σ scenes.durationInFrames == durationInFrames`.

### 4.4 cue 사전 (`md2short/cues.py`)

| 종류 | key | 정규식 |
| --- | --- | --- |
| base motion (1개, 우선순위 순) | fadeOut / pan / zoomIn(기본) | `페이드\s?아웃\|어두워` / `패닝` / `줌인\|확대` |
| effect (겹침) | shake / glitch | `흔들` / `글리치\|노이즈` |
| SFX (장면 시작 frame) | knock, wind, heartbeat, scratch, breath, drone | `노크\|두드리`, `바람`, `심장`, `긁`, `숨소리`, `저음\|울림\|울리` |
| BGM duck | silence | `정적\|끊김` (BGM 있을 때만, 30 frames) |

파일: `assets/sfx/<key>*.mp3|wav`, `assets/bgm/*.mp3`(이름순 첫 파일). 없으면 고유 key당 경고 1건(`logs/warnings.json`).

### 4.5 산출물 구조

```text
jobs/sf_<YYYYMMDD>_<hex>/
├── status.json
├── inputs/  source.md · storyboard.json · images/scene_NN.png · audio_assets/
├── audio/narration.mp3
├── transcripts/words.json
├── edit/  edl.json · props.json · final.mp4 · attempt_<n>/
├── output/ret.mp4
├── logs/  parse.json · tts_input.txt · elevenlabs_tts_raw.json · plan.json · warnings.json · confirm.json · remotion.log
└── qc_report.json
```

## 5. QC (`qc_report.json.checks`, 정확히 6개)

| check | 기준 |
| --- | --- |
| resolution | 1080×1920 (`ffprobe -select_streams v:0`) |
| fps | 30 |
| duration | 45.0~58.0초 (video stream) |
| tail_sync | \|마지막 단어 end − audio_duration_ms\| ≤ 1000ms |
| render_length | \|ms_to_frames(video_ms) − durationInFrames\| ≤ 3 frames |
| artifacts | §3.2 필수 파일 모두 존재 |

`cost`는 정보 필드다(`MD2SHORT_EL_COST_PER_CHAR`가 있으면 추정액 계산). ffprobe는 PATH에 있으면 그것을, 없으면 Remotion 번들 ffprobe를 쓴다.

## 6. 환경 변수

| 변수 | 용도 |
| --- | --- |
| `ELEVENLABS_API_KEY` | 필수(가짜 TTS 제외) |
| `MD2SHORT_VOICE_ID` | 기본 voice 대신 사용 (기본은 [`voice.md`](voice.md)) |
| `MD2SHORT_FAKE_TTS` | `synth` 또는 응답 JSON 경로 — ElevenLabs 대신 사용 |
| `MD2SHORT_JOBS_DIR`, `MD2SHORT_ASSETS_DIR`, `MD2SHORT_REMOTION_DIR` | 경로 변경(테스트용) |
| `MD2SHORT_EL_COST_PER_CHAR` | 비용 추정 단가 |
| `OPENAI_API_KEY` | 선택: 자막 AI 분할 |
| `MD2SHORT_SUBTITLE_SPLIT` | `auto`(기본) / `ai` / `rule` |
| `MD2SHORT_OPENAI_MODEL` | 자막 분할 모델 (기본 `gpt-5-mini`) |
| `MD2SHORT_IMAGE_MODEL`, `MD2SHORT_IMAGE_QUALITY` | AI 이미지 모델(기본 `gpt-image-2`)·품질(기본 `medium`) |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | 웹 GitHub 로그인 (둘 다 있으면 켜짐) |
| `MD2SHORT_ALLOWED_GITHUB_USERS` | 허용 GitHub ID (쉼표 구분, 비면 전원 거부) |
| `MD2SHORT_PUBLIC_URL` | OAuth callback URL (기본 `http://localhost:8501`) |
| `MD2SHORT_FAKE_IMAGES` | `1`이면 API 대신 단색 PNG (테스트·리허설) |

<!-- v2-backlog -->

## v2-backlog (v1 범위 밖)

이전 설계 문서에 있던 아래 기능은 v1에서 제외했다. 필요해지면 별도 설계로 다시 다룬다.

- OpenAI 대본 생성 엔진(`script_engine`, gpt-5-mini)과 주제 입력 모드
- ElevenLabs Scribe(`scribe_v1`) 전사 기반 타임스탬프 — v1은 TTS alignment 사용
- 숫자·약어 표시 보정(`numeric_display`), 숫자 모션 그래픽(`data_extract`, NumberCard)
- 호랑이 emoticon 비주얼 모드, 실사 이미지 moderation 재시도 체인(원본 → sanitised → 추상)
- 회사 로고 overlay, 상단 BrandHeader/하단 BottomBar, Opening/Outro CTA, composition `TechExplainer`
- Edge-TTS 무료 테스트 모드, 엑셀 일괄 제작, 유튜브 업로드, 다국어 (웹 화면·AI 이미지는 v1.1에서 구현됨)
- webp 이미지, 자막 폰트 라이선스 확정
