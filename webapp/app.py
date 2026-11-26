"""MD2Short 웹 화면 (로컬 전용).

실행: python -m uv run streamlit run webapp/app.py

흐름
  1. 대본 확인   — 연출표 md 업로드 → 장면·자막 분할 확인("/" 수정) → 장면 이미지(업로드 또는 AI)
  2. 이미지 확인 — [대본·이미지 확정]으로 job 생성, AI 이미지 생성 → 장면별 다시 만들기
  3. 음성·타이밍 — [음성 만들기] → 목표 vs 실제 시간 표, 길이 경고, 내레이션 듣기
  4. 영상       — [영상 만들기] → 렌더 진행률 → 재생·다운로드·QC
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from md2short import github_auth, image_gen, pipeline, subtitles, voice  # noqa: E402
from md2short.confirm import MAX_MS, MIN_MS, suggest_speed  # noqa: E402
from md2short.errors import Md2ShortError  # noqa: E402
from md2short.paths import jobs_dir  # noqa: E402
from md2short.state import JobState  # noqa: E402
from md2short.storyboard import Storyboard, parse_storyboard  # noqa: E402
from md2short.timeutil import format_seconds  # noqa: E402

load_dotenv(ROOT / ".env")
st.set_page_config(page_title="MD2Short", page_icon="🎬", layout="wide")

STATUS_KO = {
    "created": "생성됨", "parsed": "대본 확정", "voice_generated": "음성 완료", "planned": "타이밍 확인 대기",
    "confirmed": "렌더 대기", "final_rendered": "렌더 완료", "qc_passed": "완료(QC 통과)",
    "qc_failed": "완료(QC 실패)", "failed": "실패", "aborted": "취소",
}
SOURCE_KO = {"manual": "수동", "ai": "AI", "rule": "규칙", "upload": "업로드"}
IMG_NAME_RE = re.compile(r"^(\d+)")


# ---------------- 상태 ----------------

def ss():
    return st.session_state


def init_state():
    defaults = {
        "step": "script", "md_text": None, "md_hash": None, "md_name": None,
        "split": {}, "split_log": {}, "chunk_text": {}, "image_choice": {}, "uploads": {},
        "prompts": {}, "upload_dir": None, "job_id": None, "view_job": None,
    }
    for k, v in defaults.items():
        ss().setdefault(k, v)
    if ss()["upload_dir"] is None:
        d = jobs_dir() / "_uploads" / uuid.uuid4().hex[:8]
        d.mkdir(parents=True, exist_ok=True)
        ss()["upload_dir"] = str(d)


def reset_draft():
    for k in ("md_text", "md_hash", "md_name", "job_id"):
        ss()[k] = None
    for k in ("split", "split_log", "chunk_text", "image_choice", "uploads", "prompts"):
        ss()[k] = {}
    ss()["step"] = "script"


def show_error(exc: Exception):
    if isinstance(exc, Md2ShortError):
        st.error(exc.message)
    else:
        st.error(f"예상하지 못한 오류: {type(exc).__name__}: {exc}")


# ---------------- 로그인 ----------------

def auth_gate() -> dict | None:
    """GitHub 로그인이 켜져 있으면 로그인한 사용자 dict, 꺼져 있으면 None. 로그인 전이면 화면을 멈춘다."""
    cfg = github_auth.load_config()
    if not cfg.enabled:
        return None
    if ss().get("user"):
        return ss()["user"]
    qp = st.query_params
    if "code" in qp and "state" in qp:
        code, state = qp["code"], qp["state"]
        st.query_params.clear()
        try:
            ss()["user"] = github_auth.complete_login(cfg, code, state)
            st.rerun()
        except github_auth.AuthError as exc:
            st.error(str(exc))
    elif "error" in qp:
        st.error(f"GitHub 로그인이 취소되었거나 실패했습니다: {qp.get('error_description') or qp['error']}")
        st.query_params.clear()

    st.title("🎬 MD2Short")
    st.write("연출표 마크다운으로 9:16 숏폼 영상을 만듭니다. 계속하려면 GitHub로 로그인하세요.")
    if not cfg.allowed:
        st.warning("허용된 GitHub 계정이 없습니다. 관리자는 .env의 MD2SHORT_ALLOWED_GITHUB_USERS에 GitHub ID를 넣어 주세요.")
    url = github_auth.authorize_url(cfg, github_auth.make_state(cfg.client_secret))
    st.markdown(
        f'<a href="{url}" target="_self" style="display:inline-block;padding:0.6em 1.2em;border-radius:8px;'
        'background:#24292f;color:#fff;text-decoration:none;font-weight:600">GitHub로 로그인</a>',
        unsafe_allow_html=True,
    )
    st.caption("읽기 전용 프로필 권한(read:user)만 요청합니다. 토큰은 저장하지 않습니다.")
    st.stop()


def current_owner() -> str | None:
    user = ss().get("user")
    return user["login"] if user else None


# ---------------- 사이드바 ----------------

def sidebar():
    st.sidebar.title("🎬 MD2Short")
    st.sidebar.caption("연출표 마크다운 → 9:16 숏폼 영상")
    user = ss().get("user")
    if user:
        c1, c2 = st.sidebar.columns([1, 3])
        if user.get("avatar_url"):
            c1.image(user["avatar_url"], width=40)
        c2.markdown(f"**{user['name']}**  \n@{user['login']}")
        if st.sidebar.button("로그아웃", width="stretch"):
            ss().clear()
            st.rerun()
    else:
        st.sidebar.caption("🔓 로그인 꺼짐 — 이 컴퓨터(localhost)에서만 쓰세요")
    el = bool(os.environ.get("ELEVENLABS_API_KEY")) or bool(os.environ.get("MD2SHORT_FAKE_TTS"))
    oa = bool(os.environ.get("OPENAI_API_KEY")) or bool(os.environ.get("MD2SHORT_FAKE_IMAGES"))
    st.sidebar.write(("✅" if el else "❌") + " ElevenLabs 키 (음성)")
    st.sidebar.write(("✅" if oa else "⚠️") + " OpenAI 키 (AI 자막 분할·AI 이미지)")

    st.sidebar.subheader("설정")
    st.sidebar.text_input("Voice ID", value=voice.voice_id(), key="voice_id",
                          help="무료 요금제는 premade voice만 가능 (기본 Brian)")
    st.sidebar.slider("말 속도", 0.7, 1.2, 0.9, 0.01, key="speed",
                      help="낮을수록 천천히 읽어 영상이 길어집니다. 규격 45~58초")
    st.sidebar.selectbox("자막 분할", ["auto", "ai", "rule"], key="split_mode",
                         format_func=lambda m: {"auto": "자동(키 있으면 AI)", "ai": "AI", "rule": "규칙"}[m])

    if st.sidebar.button("➕ 새 영상 만들기", width="stretch"):
        reset_draft()
        ss()["view_job"] = None
        st.rerun()

    st.sidebar.subheader("이전 작업")
    for job in list_jobs()[:20]:
        label = f"{job['job_id']} · {STATUS_KO.get(job['status'], job['status'])}"
        if st.sidebar.button(label, key=f"job_{job['job_id']}", width="stretch"):
            ss()["view_job"] = job["job_id"]
            st.rerun()


def list_jobs() -> list[dict]:
    root = jobs_dir()
    if not root.is_dir():
        return []
    out = []
    for d in root.iterdir():
        f = d / "status.json"
        if d.name.startswith("_") or not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            owner = current_owner()
            if owner and data.get("owner") != owner:
                continue
            out.append({"job_id": d.name, "status": data.get("status"), "updated": data.get("updated_at", "")})
        except Exception:
            continue
    return sorted(out, key=lambda j: j["updated"], reverse=True)


# ---------------- 1. 대본 확인 ----------------

def step_script():
    st.header("1. 대본 확인")
    up = st.file_uploader("연출표 마크다운 (.md)", type=["md", "markdown", "txt"])
    if up is not None:
        text = up.getvalue().decode("utf-8-sig")
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if h != ss()["md_hash"]:
            reset_draft()
            ss().update(md_text=text, md_hash=h, md_name=up.name)
    if not ss()["md_text"]:
        st.info("`## 장면 1 [0~4초] : 제목` + 나레이션/자막 강조/화면 연출/효과음 형식의 md 파일을 올려 주세요. (예: sample.md)")
        return

    try:
        board = parse_storyboard(ss()["md_text"])
    except Exception as exc:
        show_error(exc)
        return
    st.success(f"{board.title or ss()['md_name']} — 장면 {len(board.scenes)}개")

    ensure_split(board)
    images_bulk(board)
    style = st.text_area("AI 이미지 공통 화풍 (모든 장면에 같이 적용)", value=image_gen.DEFAULT_STYLE, key="style", height=90)

    problems = []
    for s in board.scenes:
        with st.expander(f"장면 {s.index} [{s.target_start_s}~{s.target_end_s}초] {s.title}", expanded=s.index == 1):
            c1, c2 = st.columns([3, 2])
            with c1:
                st.markdown(f"**나레이션**: {s.narration}")
                if s.highlights:
                    st.markdown("**빨간 강조**: " + ", ".join(f":red[{h}]" for h in s.highlights))
                st.caption(f"화면 연출: {s.visual_direction}  \n효과음: {s.sfx_direction}")
                src = ss()["split"].get(s.index, {}).get("source", "rule")
                key = f"chunks_{s.index}"
                if key not in st.session_state:
                    st.session_state[key] = " / ".join(ss()["split"][s.index]["chunks"])
                text = st.text_input(f"자막 분할 ({SOURCE_KO.get(src, src)}) — '/'로 끊는 위치를 고칠 수 있어요", key=key)
                chunks = subtitles.parse_manual(text)
                problem = subtitles.check_chunks(s.narration, chunks)
                if problem:
                    st.error(problem)
                    problems.append(s.index)
                else:
                    st.caption(" ｜ ".join(f"{c} ({len(c.split())}어절)" for c in chunks))
            with c2:
                image_slot(s, style)

    if st.button("🔄 자막 다시 나누기", help="수정 내용을 버리고 AI/규칙으로 다시 나눕니다"):
        for s in board.scenes:
            st.session_state.pop(f"chunks_{s.index}", None)
        ss()["split"] = {}
        st.rerun()

    missing = [s.index for s in board.scenes if ss()["image_choice"].get(s.index, "ai") == "upload" and s.index not in ss()["uploads"]]
    n_ai = sum(1 for s in board.scenes if ss()["image_choice"].get(s.index, "ai") == "ai")
    if missing:
        st.warning(f"이미지를 올리지 않은 장면: {', '.join(map(str, missing))}")
    if n_ai:
        st.caption(f"AI 이미지 {n_ai}장을 만듭니다 (OpenAI 장당 과금, 장당 수십 초).")
    disabled = bool(problems or missing)
    if st.button("✅ 대본·이미지 확정", type="primary", disabled=disabled):
        confirm_script(board, style)


def ensure_split(board: Storyboard):
    if ss()["split"]:
        return
    with st.spinner("자막을 나누는 중..."):
        mode = st.session_state.get("split_mode", "auto")
        chunks, source, log = subtitles.split_scenes(board.scenes, mode)
    ss()["split"] = {i: {"chunks": chunks[i], "source": source[i]} for i in chunks}
    ss()["split_log"] = log
    for idx, reason in log.get("fallbacks", {}).items():
        st.toast(f"장면 {idx}: AI 분할 대신 규칙 분할 ({reason})")


def images_bulk(board: Storyboard):
    files = st.file_uploader("장면 이미지 한꺼번에 올리기 (선택) — 파일 이름 앞 번호 순서대로 장면 1, 2, …에 붙습니다",
                             type=["png", "jpg", "jpeg"], accept_multiple_files=True, key="bulk")
    if not files:
        return
    def num(f):
        m = IMG_NAME_RE.match(f.name)
        return int(m.group(1)) if m else 10**6
    files = sorted(files, key=lambda f: (num(f), f.name))
    sig = tuple(f.name for f in files)
    if ss().get("bulk_sig") == sig:
        return
    ss()["bulk_sig"] = sig
    for scene, f in zip(board.scenes, files):
        save_upload(scene.index, f)
    if len(files) != len(board.scenes):
        st.warning(f"이미지 {len(files)}장을 앞 장면부터 붙였습니다. 나머지 장면은 업로드하거나 AI로 만드세요.")


def save_upload(scene_no: int, f):
    d = Path(ss()["upload_dir"])
    ext = Path(f.name).suffix.lower() or ".png"
    path = d / f"scene_{scene_no:02d}{ext}"
    for old in d.glob(f"scene_{scene_no:02d}.*"):
        old.unlink()
    path.write_bytes(f.getvalue())
    ss()["uploads"][scene_no] = str(path)
    ss()["image_choice"][scene_no] = "upload"
    st.session_state[f"choice_{scene_no}"] = "upload"


def image_slot(s, style: str):
    default = ss()["image_choice"].get(s.index, "upload" if s.index in ss()["uploads"] else "ai")
    st.session_state.setdefault(f"choice_{s.index}", default)
    choice = st.radio("장면 이미지", ["upload", "ai"], horizontal=True, key=f"choice_{s.index}",
                      format_func=lambda c: {"upload": "직접 올리기", "ai": "AI로 만들기"}[c])
    ss()["image_choice"][s.index] = choice
    if choice == "upload":
        f = st.file_uploader("이미지", type=["png", "jpg", "jpeg"], key=f"img_{s.index}", label_visibility="collapsed")
        if f is not None and ss().get(f"img_sig_{s.index}") != f.name + str(f.size):
            ss()[f"img_sig_{s.index}"] = f.name + str(f.size)
            save_upload(s.index, f)
        if s.index in ss()["uploads"]:
            st.image(ss()["uploads"][s.index], width=180)
    else:
        default_prompt = f"Scene {s.index} — {s.title}.\nVisual direction (Korean): {s.visual_direction or s.narration}"
        st.text_area("장면 설명 (프롬프트, 공통 화풍 뒤에 붙음)", value=default_prompt, key=f"prompt_{s.index}", height=110)


def confirm_script(board: Storyboard, style: str):
    overrides = {}
    for s in board.scenes:
        chunks = subtitles.parse_manual(st.session_state[f"chunks_{s.index}"])
        orig = ss()["split"][s.index]
        source = orig["source"] if chunks == orig["chunks"] else "manual"
        overrides[s.index] = (chunks, source)
    provided = {i: Path(p) for i, p in ss()["uploads"].items() if ss()["image_choice"].get(i) == "upload"}
    prompts = {s.index: f"{style}\n\n{st.session_state.get(f'prompt_{s.index}', '')}"
               for s in board.scenes if s.index not in provided}
    try:
        image_gen.check_ready(bool(prompts))
        bar = st.progress(0.0, text="job 만드는 중...")

        def on_img(n, total, scene):
            bar.progress(min(0.99, (n - 1) / total), text=f"AI 이미지 생성 중... 장면 {scene} ({n}/{total})")

        fake = bool(os.environ.get("MD2SHORT_FAKE_TTS"))
        os.environ["MD2SHORT_VOICE_ID"] = st.session_state.get("voice_id") or voice.voice_id()
        job_dir, state, _, _ = pipeline.start_job(
            ss()["md_text"], None, "rule", pipeline.job_config(st.session_state.get("speed", 0.9), fake),
            overrides=overrides, markdown_input=ss()["md_name"] or "upload.md", images_input="web",
            provided=provided, ai_images=True, style=style, prompts=prompts, on_image_progress=on_img,
            owner=current_owner())
        bar.progress(1.0, text="완료")
        ss()["job_id"] = job_dir.name
        ss()["step"] = "images"
        st.rerun()
    except Exception as exc:
        show_error(exc)


# ---------------- 2. 이미지 확인 ----------------

def load_job(job_id: str):
    d = jobs_dir() / job_id
    return d, JobState(d), json.loads((d / "inputs" / "storyboard.json").read_text(encoding="utf-8"))


def image_grid(job_id: str, allow_regen: bool):
    job_dir, state, sb = load_job(job_id)
    cols = st.columns(3)
    for k, img in enumerate(sb["images"]):
        with cols[k % 3]:
            st.image(str(job_dir / "inputs" / "images" / img["job_name"]),
                     caption=f"장면 {img['scene']} · {SOURCE_KO.get(img.get('source', 'upload'), '')} · {img.get('width')}×{img.get('height')}")
            if allow_regen:
                with st.popover(f"장면 {img['scene']} 이미지 다시 만들기"):
                    p = st.text_area("프롬프트", value=img.get("prompt") or image_gen.build_prompt(
                        next(_scene(sb, img["scene"]))), key=f"regen_p_{job_id}_{img['scene']}", height=180)
                    if st.button("AI로 다시 만들기 (과금)", key=f"regen_b_{job_id}_{img['scene']}"):
                        try:
                            image_gen.check_ready(True)
                            with st.spinner("이미지 생성 중..."):
                                image_gen.regenerate_scene_image(job_dir, img["scene"], p)
                            st.rerun()
                        except Exception as exc:
                            show_error(exc)


def _scene(sb, idx):
    from md2short.storyboard import Scene
    for s in sb["scenes"]:
        if s["index"] == idx:
            yield Scene(**s)


def step_images():
    job_id = ss()["job_id"]
    st.header("2. 이미지 확인")
    st.caption(f"job: {job_id} — 마음에 들지 않는 장면만 다시 만드세요.")
    image_grid(job_id, allow_regen=True)
    st.divider()
    speed = st.session_state.get("speed", 0.9)
    st.write(f"말 속도 **{speed}** · voice `{st.session_state.get('voice_id')}` (사이드바에서 변경)")
    if st.button("🎙️ 음성 만들기 (ElevenLabs 과금)", type="primary"):
        job_dir, state, sb = load_job(job_id)
        try:
            voice.validate_speed(speed)
            fake = bool(os.environ.get("MD2SHORT_FAKE_TTS"))
            pipeline.preflight(need_key=not fake, need_render=False)
            os.environ["MD2SHORT_VOICE_ID"] = st.session_state.get("voice_id") or voice.voice_id()
            board = Storyboard(title=sb.get("title"), scenes=sb["scenes"])
            from md2short.assets import SceneImage
            imgs = [SceneImage(**i) for i in sb["images"]]
            state.data["config"].update(speed=speed, voice_id=os.environ["MD2SHORT_VOICE_ID"])
            state.save()
            with st.spinner("음성 생성 중..."):
                pipeline.voice_and_plan(job_dir, state, board, imgs, speed)
            ss()["step"] = "timing"
            st.rerun()
        except Exception as exc:
            show_error(exc)


# ---------------- 3. 타이밍 확인 ----------------

def timing_table(edl: dict):
    rows = []
    for s in edl["scenes"]:
        rows.append({
            "장면": s["index"],
            "목표(연출표)": f"{s['target_s'][0]}~{s['target_s'][1]}초",
            "실제(음성)": f"{format_seconds(s['start_ms'])}~{format_seconds(s['end_ms'])}초",
            "모션": s["motion"] + ("+" + "+".join(s["effects"]) if s["effects"] else ""),
            "효과음": ", ".join(f"{x['key']}({'O' if x['applied'] else '없음'})" for x in s["sfx"]) or "-",
            "자막": " / ".join(s.get("subtitle_chunks", [])),
        })
    st.dataframe(rows, hide_index=True, width="stretch")


def step_timing():
    job_id = ss()["job_id"]
    job_dir = jobs_dir() / job_id
    edl = json.loads((job_dir / "edit" / "edl.json").read_text(encoding="utf-8"))
    st.header("3. 음성·타이밍 확인")
    st.audio(str(job_dir / "audio" / "narration.mp3"))
    timing_table(edl)
    total = edl["audio_duration_ms"]
    if MIN_MS <= total <= MAX_MS:
        st.success(f"총 길이 {format_seconds(total)}초 (규격 45~58초)")
    else:
        hint = suggest_speed(total, edl.get("tts_speed", 1.0))
        st.error(f"총 길이 {format_seconds(total)}초 — 규격(45~58초)을 벗어납니다. 그대로 만들면 QC 실패로 기록됩니다."
                 + (f" 말 속도를 {hint}로 바꿔 새로 만들면 50초에 가까워집니다." if hint else ""))
    warnings = json.loads((job_dir / "logs" / "warnings.json").read_text(encoding="utf-8"))
    if warnings:
        with st.expander(f"경고 {len(warnings)}건 (효과음·배경음 파일 없음 등)"):
            for w in warnings:
                st.write("- " + (w.get("message") or f"장면 {w.get('scene')}: {w.get('text')}"))
    c1, c2 = st.columns(2)
    if c1.button("🎬 영상 만들기", type="primary"):
        render_job(job_id, rerender=False)
    if c2.button("처음으로 (이 job 취소)"):
        state = JobState(job_dir)
        if state.status == "planned":
            state.transition("aborted")
        reset_draft()
        st.rerun()


def render_job(job_id: str, rerender: bool):
    job_dir = jobs_dir() / job_id
    bar = st.progress(0.0, text="렌더 준비 중... (첫 실행은 몇 분 걸릴 수 있습니다)")

    def on_progress(stage, done, total):
        frac = done / max(1, total)
        frac = frac * 0.8 if stage == "Rendered" else 0.8 + frac * 0.2
        bar.progress(min(0.99, frac), text=f"{'프레임 그리는 중' if stage == 'Rendered' else '인코딩 중'} {done}/{total}")

    try:
        pipeline.preflight(need_key=False, need_render=True)
        if rerender:
            pipeline.rerender(job_id, yes=True, on_progress=on_progress)
        else:
            pipeline.finish(job_dir, JobState(job_dir), yes=True, on_progress=on_progress)
        bar.progress(1.0, text="완료")
        ss()["view_job"] = job_id
        ss()["step"] = "result"
        st.rerun()
    except Exception as exc:
        show_error(exc)


# ---------------- 4. 결과 ----------------

def view_job(job_id: str):
    job_dir = jobs_dir() / job_id
    if not (job_dir / "status.json").is_file():
        st.error("job을 찾을 수 없습니다.")
        return
    state = JobState(job_dir)
    owner = current_owner()
    if owner and state.data.get("owner") != owner:
        st.error("이 작업을 볼 권한이 없습니다.")
        return
    st.header(f"작업 {job_id}")
    st.write(f"상태: **{STATUS_KO.get(state.status, state.status)}**"
             + (f" — 실패 단계 `{state.data.get('failed_stage')}`: {state.data.get('error')}" if state.status == "failed" else ""))
    ret = job_dir / "output" / "ret.mp4"
    if ret.is_file():
        c1, c2 = st.columns([2, 3])
        with c1:
            st.video(str(ret))
            st.download_button("⬇️ MP4 다운로드", data=ret.read_bytes(), file_name=f"{job_id}.mp4", mime="video/mp4")
        with c2:
            qc_path = job_dir / "qc_report.json"
            if qc_path.is_file():
                rep = json.loads(qc_path.read_text(encoding="utf-8"))
                st.subheader("QC " + ("✅ 통과" if rep["passed"] else "⚠️ 실패"))
                names = {"resolution": "해상도", "fps": "fps", "duration": "길이(ms)", "tail_sync": "자막 끝 sync(ms)",
                         "render_length": "렌더 길이 차(frame)", "artifacts": "산출물"}
                st.dataframe([{"항목": names.get(k, k), "결과": "통과" if c["passed"] else "실패", "값": str(c["value"])}
                              for k, c in rep["checks"].items()], hide_index=True, width="stretch")
    if (job_dir / "edit" / "edl.json").is_file():
        with st.expander("장면·자막 타이밍"):
            timing_table(json.loads((job_dir / "edit" / "edl.json").read_text(encoding="utf-8")))
    if (job_dir / "inputs" / "storyboard.json").is_file():
        with st.expander("장면 이미지 (다시 만든 뒤 '다시 렌더'를 누르세요)"):
            image_grid(job_id, allow_regen=state.status not in ("created",))
    if state.status in ("planned", "aborted", "qc_passed", "qc_failed") or (
            state.status == "failed" and state.data.get("failed_stage") in ("confirm", "render", "qc")):
        if st.button("🔁 다시 렌더 (음성 재사용, TTS 과금 없음)"):
            render_job(job_id, rerender=True)
    if state.status == "parsed":
        if st.button("이 job 이어서 진행 (이미지 확인 단계)"):
            ss().update(job_id=job_id, step="images", view_job=None)
            st.rerun()


# ---------------- main ----------------

def main():
    init_state()
    auth_gate()
    sidebar()
    if ss()["view_job"]:
        view_job(ss()["view_job"])
        return
    step = ss()["step"]
    st.progress({"script": 0.1, "images": 0.4, "timing": 0.7, "result": 1.0}.get(step, 0.1),
                text={"script": "1/4 대본 확인", "images": "2/4 이미지 확인", "timing": "3/4 음성·타이밍", "result": "4/4 영상"}[step])
    if step == "script":
        step_script()
    elif step == "images":
        step_images()
    elif step == "timing":
        step_timing()


main()
