"""장면 구간·자막·cue 계획과 Remotion props 생성 (AC-4, AC-6, AC-7, AC-8).

모든 시간은 words.json(ms)에서 출발해 ``timeutil.ms_to_frames``로만 frame이 된다.
Remotion은 props의 frame 정수를 그대로 쓴다.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import cues
from .assets import SceneImage, find_bgm, find_sfx
from .errors import InputValidationError
from .storyboard import Storyboard
from .timeutil import ms_to_frames

BGM_VOLUME = 0.18


def scene_word_ranges(words: list[dict], scene_char_starts: list[int]) -> list[tuple[int, int]]:
    """장면별 단어 index 범위 [a, b)."""
    bounds = scene_char_starts + [10**12]
    ranges = []
    for k in range(len(scene_char_starts)):
        idx = [i for i, w in enumerate(words) if bounds[k] <= w["char_start"] < bounds[k + 1]]
        if not idx:
            raise InputValidationError("이 장면의 나레이션 단어를 음성에서 찾지 못했습니다.", scene=k + 1)
        ranges.append((idx[0], idx[-1] + 1))
    return ranges


def scene_intervals_ms(words: list[dict], ranges: list[tuple[int, int]], audio_ms: int) -> list[tuple[int, int]]:
    starts = [words[a]["start"] for a, _ in ranges]
    starts[0] = 0  # 장면 1은 오디오 시작부터 (첫 음성 이전 무음 포함)
    ends = starts[1:] + [audio_ms]
    return list(zip(starts, ends))


def chunks_to_words(subtitle_chunks: list[str], word_idx: list[int], words: list[dict], scene_no: int) -> list[list[int]]:
    """자막 덩어리(어절 문자열)를 장면의 words.json 단어 index 목록으로 대응시킨다."""
    sizes = [len(c.split()) for c in subtitle_chunks]
    if sum(sizes) != len(word_idx):
        raise InputValidationError(
            f"자막 덩어리 어절 수({sum(sizes)})와 음성 단어 수({len(word_idx)})가 다릅니다.", scene=scene_no)
    out, pos = [], 0
    for c, n in zip(subtitle_chunks, sizes):
        idx = word_idx[pos:pos + n]
        if [words[i]["text"] for i in idx] != c.split():
            raise InputValidationError(f"자막 덩어리 '{c}'가 음성 단어와 맞지 않습니다.", scene=scene_no)
        out.append(idx)
        pos += n
    return out


def word_spans(word: dict, highlight_chars: set[int]) -> list[dict]:
    spans: list[dict] = []
    for offset, ch in enumerate(word["text"]):
        flag = (word["char_start"] + offset) in highlight_chars
        if spans and spans[-1]["highlight"] == flag:
            spans[-1]["text"] += ch
        else:
            spans.append({"text": ch, "highlight": flag})
    return spans


def merge_spans(spans: list[dict]) -> list[dict]:
    out: list[dict] = []
    for s in spans:
        if out and out[-1]["highlight"] == s["highlight"]:
            out[-1]["text"] += s["text"]
        else:
            out.append(dict(s))
    return out


def build_plan(
    board: Storyboard,
    images: list[SceneImage],
    words_doc: dict,
    job_dir: Path,
    assets: Path,
) -> tuple[dict, dict, list[dict]]:
    """edl, props, warnings를 만들고 파일로 쓴다."""
    words = words_doc["words"]
    audio_ms = words_doc["audio_duration_ms"]
    char_starts = words_doc["scene_char_starts"]
    total_frames = ms_to_frames(audio_ms)
    if total_frames < 1:
        raise InputValidationError("음성 길이가 0입니다.")

    ranges = scene_word_ranges(words, char_starts)
    intervals = scene_intervals_ms(words, ranges, audio_ms)

    # 강조 문자 (전체 텍스트 기준 offset)
    highlight_chars: set[int] = set()
    for scene, base in zip(board.scenes, char_starts):
        for a, b in scene.highlight_ranges:
            highlight_chars.update(range(base + a, base + b))

    warnings: list[dict] = []
    audio_assets = job_dir / "inputs" / "audio_assets"
    audio_assets.mkdir(parents=True, exist_ok=True)

    bgm_src = find_bgm(assets)
    bgm = None
    if bgm_src is None:
        warnings.append({"type": "missing_bgm", "message": f"배경음악이 없습니다. '{assets / 'bgm'}'에 mp3를 넣으면 깔립니다."})
    else:
        shutil.copy2(bgm_src, audio_assets / "bgm.mp3")
        bgm = {"file": "bgm.mp3", "volume": BGM_VOLUME, "ducks": [], "source": bgm_src.name}

    sfx_files: dict[str, str | None] = {}
    edl_scenes = []
    props_scenes = []
    props_captions = []
    props_sfx = []

    for k, scene in enumerate(board.scenes):
        start_ms, end_ms = intervals[k]
        from_f = ms_to_frames(start_ms)
        end_f = total_frames if k == len(board.scenes) - 1 else ms_to_frames(end_ms)
        dur_f = end_f - from_f
        if dur_f < 1:
            raise InputValidationError("장면 길이가 1 frame보다 짧습니다.", scene=scene.index)

        base, effects, motion_reason = cues.match_motion(scene.visual_direction)
        sfx_keys, sfx_reason, unmatched = cues.match_sfx(scene.sfx_direction)
        for seg in unmatched:
            warnings.append({"type": "unmatched_direction", "scene": scene.index, "text": seg})

        scene_sfx = []
        for key in sfx_keys:
            if key == cues.SILENCE_KEY:
                if bgm is not None:
                    bgm["ducks"].append({"fromFrame": from_f, "durationInFrames": cues.SILENCE_DUCK_FRAMES})
                scene_sfx.append({"key": key, "file": None, "applied": bgm is not None})
                continue
            if key not in sfx_files:
                src = find_sfx(assets, key)
                if src is None:
                    sfx_files[key] = None
                    warnings.append(
                        {"type": "missing_sfx", "key": key, "message": f"효과음 '{key}' 파일이 없습니다. '{assets / 'sfx'}/{key}*.mp3'를 넣으면 재생됩니다."}
                    )
                else:
                    name = f"sfx_{key}{src.suffix.lower()}"
                    shutil.copy2(src, audio_assets / name)
                    sfx_files[key] = name
            fname = sfx_files[key]
            scene_sfx.append({"key": key, "file": fname, "applied": fname is not None})
            if fname:
                props_sfx.append({"file": fname, "fromFrame": from_f})

        a, b = ranges[k]
        from .subtitles import rule_split

        sub_chunks = scene.subtitle_chunks or rule_split(scene.narration)
        chunks = chunks_to_words(sub_chunks, list(range(a, b)), words, scene.index)
        prev_end = from_f
        for chunk in chunks:
            # 덩어리 표시 구간 = 첫 어절 시작 ~ 마지막 어절 끝 (words.json 기준), 장면 안으로 제한
            c_from = max(prev_end, from_f, ms_to_frames(words[chunk[0]]["start"]))
            c_end = min(end_f, ms_to_frames(words[chunk[-1]]["end"]))
            if c_end - c_from < 1:
                text = " ".join(words[w]["text"] for w in chunk)
                warnings.append({"type": "dropped_caption", "scene": scene.index, "text": text,
                                 "message": f"[장면 {scene.index}] 자막 '{text}'이(가) 1 frame보다 짧아 표시되지 않습니다."})
                continue
            spans: list[dict] = []
            for wi, w in enumerate(chunk):
                if wi:
                    spans.append({"text": " ", "highlight": False})
                spans.extend(word_spans(words[w], highlight_chars))
            props_captions.append({"fromFrame": c_from, "durationInFrames": c_end - c_from, "spans": merge_spans(spans)})
            prev_end = c_end

        img = images[k]
        props_scenes.append(
            {"index": scene.index, "image": img.job_name, "fromFrame": from_f, "durationInFrames": dur_f, "motion": base, "effects": effects}
        )
        edl_scenes.append(
            {
                "index": scene.index,
                "title": scene.title,
                "subtitle_chunks": sub_chunks,
                "subtitle_source": scene.subtitle_source or "rule",
                "target_s": [scene.target_start_s, scene.target_end_s],
                "start_ms": start_ms,
                "end_ms": end_ms,
                "fromFrame": from_f,
                "durationInFrames": dur_f,
                "image": {"job_name": img.job_name, "original_name": img.original_name, "width": img.width, "height": img.height},
                "motion": base,
                "effects": effects,
                "motion_reason": motion_reason,
                "sfx": scene_sfx,
                "sfx_reason": sfx_reason,
            }
        )

    if sum(s["durationInFrames"] for s in props_scenes) != total_frames:
        raise InputValidationError("장면 frame 합계가 전체 길이와 다릅니다(내부 오류).")

    props = {
        "durationInFrames": total_frames,
        "narration": "narration.mp3",
        "bgm": None if bgm is None else {k: v for k, v in bgm.items() if k != "source"},
        "scenes": props_scenes,
        "captions": props_captions,
        "sfx": props_sfx,
    }
    edl = {
        "audio_duration_ms": audio_ms,
        "tts_speed": words_doc.get("tts_speed", 1.0),
        "durationInFrames": total_frames,
        "bgm": bgm,
        "scenes": edl_scenes,
    }

    edit = job_dir / "edit"
    edit.mkdir(parents=True, exist_ok=True)
    _dump(edit / "edl.json", edl)
    _dump(edit / "props.json", props)
    _dump(job_dir / "logs" / "warnings.json", warnings)
    _dump(job_dir / "logs" / "plan.json", {"scenes": len(props_scenes), "captions": len(props_captions), "sfx": len(props_sfx), "durationInFrames": total_frames})
    return edl, props, warnings


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
