import json

from md2short import cues
from md2short.assets import SceneImage
from md2short.plan import build_plan
from md2short.timeutil import ms_to_frames

EXPECTED_CUES = {
    1: ("zoomIn", [], ["knock"]),
    2: ("zoomIn", [], ["wind"]),
    3: ("zoomIn", [], ["drone"]),
    4: ("zoomIn", ["shake"], ["heartbeat", "silence"]),
    5: ("zoomIn", ["shake", "glitch"], ["scratch", "breath"]),
    6: ("fadeOut", [], ["drone"]),
}


def _images(n=6):
    return [SceneImage(scene=i, original_name=f"{i - 1}_x.png", job_name=f"scene_{i:02d}.png", sha256="0" * 64, width=941, height=1672)
            for i in range(1, n + 1)]


def _plan(board, words_doc, tmp_path, assets=None):
    job = tmp_path / "job"
    (job / "logs").mkdir(parents=True, exist_ok=True)
    return build_plan(board, _images(), words_doc, job, assets or (tmp_path / "no_assets"))


def test_sample_cue_snapshot(board):
    for s in board.scenes:
        base, effects, _ = cues.match_motion(s.visual_direction)
        keys, _, _ = cues.match_sfx(s.sfx_direction)
        assert (base, effects, keys) == EXPECTED_CUES[s.index], s.index


def test_scene_frames_are_contiguous_and_sum_to_total(board, words_doc, tmp_path):
    edl, props, _ = _plan(board, words_doc, tmp_path)
    scenes = props["scenes"]
    assert scenes[0]["fromFrame"] == 0
    for a, b in zip(scenes, scenes[1:]):
        assert a["fromFrame"] + a["durationInFrames"] == b["fromFrame"]
    assert sum(s["durationInFrames"] for s in scenes) == props["durationInFrames"]
    assert props["durationInFrames"] == ms_to_frames(words_doc["audio_duration_ms"])
    assert edl["scenes"][-1]["end_ms"] == words_doc["audio_duration_ms"]
    assert all(s["durationInFrames"] >= 1 for s in scenes)


def test_scene_start_is_first_word_of_scene(board, words_doc, tmp_path):
    edl, _, _ = _plan(board, words_doc, tmp_path)
    by_char = {w["char_start"]: w for w in words_doc["words"]}
    for k, s in enumerate(edl["scenes"][1:], start=1):
        assert s["start_ms"] == by_char[words_doc["scene_char_starts"][k]]["start"]


def test_captions_inside_scenes_and_chunk_size(board, words_doc, tmp_path):
    _, props, _ = _plan(board, words_doc, tmp_path)
    bounds = [(s["fromFrame"], s["fromFrame"] + s["durationInFrames"]) for s in props["scenes"]]
    for c in props["captions"]:
        start, end = c["fromFrame"], c["fromFrame"] + c["durationInFrames"]
        assert any(a <= start and end <= b for a, b in bounds)
        n_words = len("".join(s["text"] for s in c["spans"]).split())
        assert 1 <= n_words <= 6


def test_highlight_spans_exclude_particles(board, words_doc, tmp_path):
    _, props, _ = _plan(board, words_doc, tmp_path)
    red = [s["text"] for c in props["captions"] for s in c["spans"] if s["highlight"]]
    joined = " | ".join(red)
    assert "사냥감" in red and "사냥감을" not in joined
    assert "구독" in red and "구독으로" not in joined
    assert "장산범" in red  # 따옴표 ‘’ 제외
    all_text = "".join(s["text"] for c in props["captions"] for s in c["spans"])
    assert all_text.replace(" ", "") == words_doc["text"].replace(" ", "")


def test_missing_assets_warnings(board, words_doc, tmp_path):
    _, props, warnings = _plan(board, words_doc, tmp_path)
    missing_sfx = [w["key"] for w in warnings if w["type"] == "missing_sfx"]
    assert sorted(missing_sfx) == sorted(["knock", "wind", "drone", "heartbeat", "scratch", "breath"])
    assert len([w for w in warnings if w["type"] == "missing_bgm"]) == 1
    assert props["bgm"] is None and props["sfx"] == []


def test_assets_present_are_wired(board, words_doc, tmp_path):
    assets = tmp_path / "assets"
    (assets / "sfx").mkdir(parents=True)
    (assets / "bgm").mkdir()
    (assets / "sfx" / "knock_door.mp3").write_bytes(b"x")
    (assets / "bgm" / "dark.mp3").write_bytes(b"x")
    _, props, warnings = _plan(board, words_doc, tmp_path, assets)
    assert props["sfx"] == [{"file": "sfx_knock.mp3", "fromFrame": 0}]
    assert props["bgm"]["file"] == "bgm.mp3"
    scene4 = props["scenes"][3]
    assert props["bgm"]["ducks"] == [{"fromFrame": scene4["fromFrame"], "durationInFrames": cues.SILENCE_DUCK_FRAMES}]
    assert not [w for w in warnings if w["type"] == "missing_bgm"]
    assert (tmp_path / "job" / "inputs" / "audio_assets" / "sfx_knock.mp3").is_file()


def test_plan_is_deterministic(board, words_doc, tmp_path):
    _plan(board, words_doc, tmp_path)
    first = (tmp_path / "job" / "edit" / "props.json").read_bytes()
    _plan(board, words_doc, tmp_path)
    assert (tmp_path / "job" / "edit" / "props.json").read_bytes() == first
    assert json.loads(first)["narration"] == "narration.mp3"


def test_caption_timing_first_start_to_last_end(board, words_doc, tmp_path):
    from md2short.subtitles import rule_split

    for s in board.scenes:
        s.subtitle_chunks = rule_split(s.narration)
    _, props, _ = _plan(board, words_doc, tmp_path)
    words = words_doc["words"]
    texts = [w["text"] for w in words]
    caps = props["captions"]
    assert len(caps) == sum(len(s.subtitle_chunks) for s in board.scenes)
    pos = 0
    for c in caps:
        n = len("".join(sp["text"] for sp in c["spans"]).split())
        first, last = words[pos], words[pos + n - 1]
        assert c["fromFrame"] == ms_to_frames(first["start"]) or c["fromFrame"] >= ms_to_frames(first["start"])
        assert c["fromFrame"] + c["durationInFrames"] == ms_to_frames(last["end"])
        pos += n
    assert pos == len(texts)
    scene2 = ["".join(sp["text"] for sp in c["spans"]) for c in caps[2:7]]
    assert scene2[2] == "새하얀 털의 이 괴물은"
