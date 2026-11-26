# 괴담모음집 (kaidanzip)

장면별 연출표 마크다운으로 괴담 쇼츠(9:16 MP4, 1080×1920, 30fps)를 만드는 도구입니다. 웹 화면과 명령줄(CLI)로 쓸 수 있습니다.
ElevenLabs가 내레이션을 만들고, Remotion이 이미지 움직임·자막·배경음·효과음을 합성합니다. 장면 이미지는 직접 올리거나 AI로 만듭니다.

> 명령어와 Python 패키지 이름은 `kaidanzip`입니다.
> 각자 자기 PC에서 자기 API 키(ElevenLabs·OpenAI)로 실행하는 방식이라, 비용은 실행한 사람에게 청구됩니다.

- 설계: [`docs/architecture.md`](docs/architecture.md) · 제품 요구: [`docs/PRD.md`](docs/PRD.md) · 작업 원칙: [`AGENTS.md`](AGENTS.md)

## 설치 (Windows 기준, 처음 한 번)

1. **Node.js** 18 이상 (확인: `node --version`)
2. **uv** (Python 패키지 관리자)
   ```bash
   python -m pip install --user uv
   ```
3. Python 의존성 (uv가 Python 3.12를 자동으로 받습니다)
   ```bash
   python -m uv sync
   ```
4. Remotion과 렌더용 브라우저
   ```bash
   cd remotion
   npm ci
   npx remotion browser ensure
   cd ..
   ```
5. `.env` 파일 (프로젝트 폴더, git에 올라가지 않음)
   ```text
   ELEVENLABS_API_KEY=여기에_키
   OPENAI_API_KEY=여기에_키   # 선택: 자막 AI 분할. 없으면 규칙 분할
   ```

FFmpeg는 따로 설치하지 않아도 됩니다(Remotion에 들어 있는 ffprobe를 씁니다).

## 웹 화면 (권장)

`run_web.bat`을 더블클릭하거나:

```bash
python -m uv run streamlit run webapp/app.py
```

브라우저에서 http://localhost:8501 이 열립니다 (이 컴퓨터에서만 접속 가능).

1. **대본 확인** — 연출표 md를 올리면 장면·강조어·자막 분할을 보여 줍니다. 자막 끊는 위치는 `/`로 고칩니다. 장면마다 이미지를 직접 올리거나 "AI로 만들기"를 고릅니다 (공통 화풍 + 장면 설명).
2. **이미지 확인** — [대본·이미지 확정]을 누르면 AI 이미지를 만들고, 마음에 안 드는 장면만 다시 만듭니다.
3. **음성·타이밍** — [음성 만들기] 후 내레이션을 듣고 목표/실제 시간 표와 길이 경고를 확인합니다.
4. **영상** — [영상 만들기] → 진행률 → 재생·다운로드·QC. 왼쪽 "이전 작업"에서 다시 렌더할 수 있습니다.

### GitHub 로그인 (선택, 웹 화면 보호)

웹 화면은 ElevenLabs·OpenAI 키로 과금되므로, 다른 사람이 접속할 수 있는 곳에 띄울 때는 GitHub 로그인을 켜세요. 허용한 GitHub ID만 들어올 수 있고, 각자 자기 작업만 보입니다.

1. GitHub → Settings → Developer settings → **OAuth Apps** → **New OAuth App**
   - Homepage URL: `http://localhost:8501`
   - Authorization callback URL: `http://localhost:8501` (다른 주소로 띄우면 그 주소)
2. 만든 앱의 **Client ID**와 **Generate a new client secret** 값을 `.env`에 넣습니다 (`.env.example` 참고).
   ```text
   GITHUB_CLIENT_ID=...
   GITHUB_CLIENT_SECRET=...
   KAIDANZIP_ALLOWED_GITHUB_USERS=내GitHubID,동료ID
   KAIDANZIP_PUBLIC_URL=http://localhost:8501
   ```
3. 웹 화면을 다시 시작하면 "GitHub로 로그인" 버튼이 나옵니다. 요청 권한은 읽기 전용 프로필(`read:user`)뿐이고 토큰은 저장하지 않습니다.

로그인이 켜져 있으면 명령줄(CLI)로 만든 작업은 소유자가 없어 웹 목록에 나오지 않습니다. 새로고침하면 다시 로그인해야 합니다(GitHub가 이미 승인했으면 버튼 한 번).

비용: 음성(ElevenLabs) 1회 + AI 이미지(OpenAI, 장당) + AI 자막 분할(소액). 다시 렌더는 무료입니다.

## 실행 (명령줄)

```bash
python -m uv run kaidanzip run sample.md --images emotion/
```

1. 연출표와 이미지를 검사합니다. 문제가 있으면 음성을 만들기 전에 `[장면 N]` 오류로 멈춥니다.
2. ElevenLabs로 내레이션을 만듭니다 (실행할 때마다 소액 과금).
3. 장면별 목표 시간과 실제 시간을 표로 보여 주고 `y/n`을 묻습니다. 자동 실행은 `--yes`.
4. 렌더가 끝나면 `jobs/<job_id>/output/ret.mp4`와 `jobs/<job_id>/qc_report.json`이 생깁니다.

| 명령 | 설명 |
| --- | --- |
| `kaidanzip run <연출표.md> --images <폴더> [--yes] [--voice-id ID] [--speed 0.7~1.2]` | 새 영상 만들기 |
| `kaidanzip run <연출표.md> --ai-images [--yes]` | 모든 장면 이미지를 AI로 만들어 영상 만들기 |
| `kaidanzip regen-image <job_id> --scene N [--prompt "..."]` | 장면 이미지 1장 다시 만들기 → 이어서 `render` |
| `kaidanzip render <job_id> [--yes]` | 음성은 그대로 두고 다시 렌더 (TTS 호출 없음) |
| `kaidanzip subtitles <연출표.md>` | 음성을 만들기 전에 자막이 어떻게 나뉘는지 미리 보기 (TTS 호출 없음) |
| `kaidanzip status <job_id>` | job 상태 보기 |

### 길이가 45~58초를 벗어날 때

확인 단계에서 빨간 경고와 함께 `--speed` 제안 값이 나옵니다. `n`을 누르고 그 값으로 다시 실행하세요. 낮을수록 천천히 읽어 영상이 길어집니다 (예: 44.7초 → `--speed 0.9`). 음성을 다시 만들기 때문에 소액 과금됩니다.

종료 코드: `0` 성공 · `1` 입력/설정 오류 · `2` 영상은 만들었지만 QC 실패 · `3` 확인에서 n · `4` 외부 API/렌더 실패.

### 무료 리허설 (음성 없이)

```bash
KAIDANZIP_FAKE_TTS=synth python -m uv run kaidanzip run sample.md --images emotion/ --yes
```

무음 내레이션으로 자막·장면 전환·렌더 흐름만 확인합니다. 비용이 들지 않습니다.

## 입력 형식

### 연출표 (`sample.md` 참고)

```markdown
## 장면 1 [0~4초] : 첫 3초 후킹
- **나레이션:** 밤에 가족 목소리가 들려도, 절대 문을 열지 마세요.
- **자막 강조(빨간색):** 절대, 문을 열지 마세요
- **화면 연출:** 어두운 복도 끝, 닫힌 현관문으로 천천히 확대(줌인)되는 느낌.
- **효과음(SFX):** 낮게 깔리는 기괴한 배경음 시작 + 문 두드리는 소리(똑, 똑, 똑)
```

- 장면 번호는 1부터 빠짐없이 이어져야 합니다.
- 자막 강조어는 쉼표로 나누고, 각 강조어가 그 장면 나레이션에 그대로 들어 있어야 합니다 (띄어쓰기·문장부호는 무시).
- `[0~4초]`는 확인 표 비교용입니다. 실제 장면 길이는 음성 길이로 정해집니다.

### 자막 분할

자막은 단어 개수가 아니라 뜻 덩어리로 나눕니다. 규칙(우선순위 순):

1. 문장 끝(. ? !)에서 반드시 끊고, 두 문장을 한 자막에 섞지 않습니다.
2. 쉼표와 큰따옴표 대사(“ ”)의 시작·끝에서 우선 끊습니다.
3. "이 괴물은", "새하얀 털의", "흉내 내어", "얼어붙고 말았습니다", "깊이 잠들어" 같은 덩어리는 가르지 않습니다.
4. 한 자막은 3~5어절 목표 (문장 끝 때문에 2어절, 덩어리 보호로 6어절은 허용, 1어절 홀로는 피함).
5. 장면 경계를 넘지 않습니다.

분할 방식(`--subtitle-split`): `auto`(기본, OpenAI 키가 있으면 AI) · `ai` · `rule`. AI 결과가 규칙을 어기거나 실패하면 그 장면은 규칙 분할로 자동 대체됩니다.

끊는 위치를 직접 정하려면 장면에 `자막 분할` 줄을 넣고 `/`로 나눕니다 (글자는 나레이션과 같아야 함):

```markdown
- **자막 분할:** 부산 장산의 전설 속 괴물, / ‘장산범’ 때문입니다. / 새하얀 털의 이 괴물은 / 사람 목소리를 똑같이 흉내 내어 / 사냥감을 부릅니다.
```

`kaidanzip subtitles sample.md`가 장면마다 붙여 넣을 수 있는 줄을 출력합니다. 자막은 각 덩어리의 첫 어절 시작부터 마지막 어절 끝까지 표시됩니다.

### 장면 이미지

폴더 안에 `번호_이름.png`(또는 `.jpg`)로 장면 수만큼 넣습니다. 번호 순서대로 장면 1, 2, …에 붙습니다. 예: `0_아파트_현관문.png` → 장면 1. 9:16(예: 1080×1920)을 권장하며, 다른 비율은 가운데를 잘라 씁니다.

### 화면 연출 키워드

| 연출표에 쓰는 말 | 효과 |
| --- | --- |
| 줌인, 확대 (기본값) | 천천히 확대 |
| 패닝 | 좌우 이동 |
| 페이드 아웃, 어두워 | 장면 끝에서 어두워짐 |
| 흔들 | 화면 흔들림 (겹쳐 적용) |
| 글리치, 노이즈 | 글리치 (겹쳐 적용) |

### 배경음·효과음 (선택)

라이선스를 확인한 파일을 넣으면 자동으로 쓰고, 없으면 경고만 내고 계속합니다.

- 배경음악: `assets/bgm/*.mp3` 중 이름순 첫 파일 (볼륨 18%)
- 효과음: `assets/sfx/<key>…mp3` 또는 `.wav` — 연출표의 효과음 문구에 아래 말이 있으면 그 장면 시작에 재생

| key (파일 이름 앞부분) | 연출표에 쓰는 말 |
| --- | --- |
| `knock` | 노크, 두드리 |
| `wind` | 바람 |
| `heartbeat` | 심장 |
| `scratch` | 긁 |
| `breath` | 숨소리 |
| `drone` | 저음, 울림, 울리 |
| (파일 없음) | 정적, 끊김 → 배경음악을 1초 끊음 |

예: `assets/sfx/knock_door.mp3`, `assets/sfx/heartbeat.wav`

## 테스트

```bash
python -m uv run pytest -q -m "not node"   # Node 없이 (가짜 TTS)
python -m uv run pytest -q -m node         # 실제 Remotion 렌더 (몇 분)
```

## 산출물 (`jobs/<job_id>/`)

`status.json` · `inputs/`(원본 사본, 이미지) · `audio/narration.mp3` · `transcripts/words.json` · `edit/`(edl, props, final.mp4) · `output/ret.mp4` · `logs/` · `qc_report.json`
