import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from research_agent.config import Settings
from research_agent.mcp_client import Gateway
from research_agent.preview import render_preview


def test_shaniu_environment_aliases_and_explicit_override(tmp_path, monkeypatch):
    for name in ("RESEARCH_MODEL_NAME", "RESEARCH_MODEL_BASE_URL", "RESEARCH_MODEL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SHANIU_MODEL", "test-model")
    monkeypatch.setenv("SHANIU_API_BASE", "https://example.org/v2")
    monkeypatch.setenv("SHANIU_API_KEY", "test-token")
    settings = Settings(_env_file=None, data_dir=tmp_path)
    assert settings.model_name == "test-model"
    assert settings.model_base_url == "https://example.org/v2"
    assert settings.model_api_key.get_secret_value() == "test-token"
    monkeypatch.setenv("RESEARCH_MODEL_NAME", "override")
    assert Settings(_env_file=None).model_name == "override"


def test_credentials_require_explicit_reference(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_RESEARCH_TOKEN", raising=False)
    credentials = tmp_path / "credentials.env"
    credentials.write_text("TEST_RESEARCH_TOKEN=example-token\n", encoding="utf-8")
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    assert not settings.prepare().model_api_key.get_secret_value()
    settings.credentials_file = credentials
    with pytest.raises(ValueError, match="MODEL_API_KEY_ENV"):
        settings.prepare()
    settings.model_api_key_env = "TEST_RESEARCH_TOKEN"
    assert settings.prepare().model_api_key.get_secret_value() == "example-token"
    assert "example-token" not in repr(settings)


async def test_gateway_serializes_complex_settings(settings, monkeypatch):
    settings.tool_transport = "stdio"
    settings.model_extra_body = {"thinking": {"type": "disabled"}}

    @asynccontextmanager
    async def fake_connect(params, timeout):
        assert json.loads(params.env["RESEARCH_MODEL_EXTRA_BODY"]) == settings.model_extra_body
        assert params.env["RESEARCH_CREDENTIALS_FILE"] == "null"
        yield object()

    monkeypatch.setattr("research_agent.mcp_client.connect", fake_connect)
    async with Gateway(settings).open() as gateway:
        assert gateway.session is not None


def test_preview_uses_manifest_to_exclude_old_slides(tmp_path, monkeypatch):
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"placeholder")
    output = tmp_path / "preview"
    images = output / "slides"
    images.mkdir(parents=True)
    (images / "Slide9.PNG").write_bytes(b"stale")

    def fake_run(args, **kwargs):
        (output / "deck.pdf").write_bytes(b"preview")
        (images / "Slide1.PNG").write_bytes(b"current")
        (output / "slides.json").write_text('["Slide1.PNG"]', encoding="utf-8-sig")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("research_agent.preview.powerpoint_available", lambda: True)
    monkeypatch.setattr("research_agent.preview.subprocess.run", fake_run)
    result = render_preview(deck, output)
    assert result["images"] == [str(images / "Slide1.PNG")]
    assert (images / "Slide9.PNG").exists()


def test_preview_rejects_missing_file(tmp_path):
    with pytest.raises(ValueError, match="PPTX"):
        render_preview(tmp_path / "missing.pptx")
