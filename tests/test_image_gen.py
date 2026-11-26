import base64
import json

import httpx
import pytest
from typer.testing import CliRunner

from md2short import image_gen
from md2short.assets import image_size
from md2short.cli import app
from md2short.errors import ExternalApiError, InputValidationError

from .conftest import EMOTION, SAMPLE


def test_prompt_has_common_style_and_direction(board):
    p = image_gen.build_prompt(board.scenes[1])
    assert p.startswith(image_gen.DEFAULT_STYLE)
    assert board.scenes[1].visual_direction in p


def test_materialize_mixed_upload_and_ai(board, tmp_path, monkeypatch):
    monkeypatch.setenv("MD2SHORT_FAKE_IMAGES", "1")
    provided = {1: next(EMOTION.glob("0_*")), 3: next(EMOTION.glob("2_*"))}
    imgs, log = image_gen.materialize_images(board.scenes, tmp_path, provided, ai_missing=True)
    assert [i.source for i in imgs] == ["upload", "ai", "upload", "ai", "ai", "ai"]
    assert [l["scene"] for l in log] == [2, 4, 5, 6]
    assert image_size(tmp_path / "scene_02.png") == (216, 384)


def test_missing_without_ai_is_error(board, tmp_path):
    with pytest.raises(InputValidationError) as exc:
        image_gen.materialize_images(board.scenes, tmp_path, {}, ai_missing=False)
    assert exc.value.scene == 1


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body


def test_openai_request_shape(tmp_path, monkeypatch):
    monkeypatch.delenv("MD2SHORT_FAKE_IMAGES", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    sent = {}
    png = image_gen._png_bytes(4, 6, "x")

    def post(self, url, headers=None, json=None):
        sent.update(url=url, json=json, headers=headers)
        return _Resp(200, {"data": [{"b64_json": base64.b64encode(png).decode()}]})

    monkeypatch.setattr(httpx.Client, "post", post)
    meta = image_gen.generate_image("prompt", tmp_path / "a.png", 1)
    assert sent["url"].endswith("/v1/images/generations")
    assert sent["json"]["size"] == "1024x1536" and sent["json"]["model"] == image_gen.image_model()
    assert (tmp_path / "a.png").read_bytes() == png
    assert meta["size"] == "1024x1536"


def test_moderation_error_is_korean(tmp_path, monkeypatch):
    monkeypatch.delenv("MD2SHORT_FAKE_IMAGES", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(httpx.Client, "post",
                        lambda self, url, headers=None, json=None: _Resp(400, {"error": {"code": "moderation_blocked"}}))
    with pytest.raises(ExternalApiError) as exc:
        image_gen.generate_image("p", tmp_path / "a.png", 5)
    assert "장면 5" in exc.value.message and "안전 정책" in exc.value.message


def test_cli_ai_images_and_regen(isolated, monkeypatch):
    monkeypatch.setenv("MD2SHORT_FAKE_IMAGES", "1")
    runner = CliRunner()
    res = runner.invoke(app, ["run", str(SAMPLE), "--ai-images", "--yes", "--skip-render"])
    assert res.exit_code == 0, res.output
    job = next((isolated / "jobs").iterdir())
    sb = json.loads((job / "inputs" / "storyboard.json").read_text(encoding="utf-8"))
    assert all(i["source"] == "ai" for i in sb["images"])
    old_sha = sb["images"][4]["sha256"]

    res = runner.invoke(app, ["regen-image", job.name, "--scene", "5", "--prompt", "다른 구도의 장면"])
    assert res.exit_code == 0, res.output
    sb2 = json.loads((job / "inputs" / "storyboard.json").read_text(encoding="utf-8"))
    assert sb2["images"][4]["sha256"] != old_sha and sb2["images"][4]["prompt"] == "다른 구도의 장면"
    props = json.loads((job / "edit" / "props.json").read_text(encoding="utf-8"))
    assert props["scenes"][4]["image"] == "scene_05.png"


def test_cli_requires_images_or_ai(isolated):
    res = CliRunner().invoke(app, ["run", str(SAMPLE), "--yes", "--skip-render"])
    assert res.exit_code == 1 and "--ai-images" in res.output
