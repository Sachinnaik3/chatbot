import pytest

from pia.settings import get_settings


def _app(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    from pia.api.main import create_app

    try:
        return create_app()
    finally:
        get_settings.cache_clear()


def test_prod_refuses_fake_llm(monkeypatch):
    with pytest.raises(RuntimeError):
        _app(monkeypatch, PIA_ENV="prod", PIA_LLM_PROVIDER="fake", PIA_PERSISTENCE="postgres")


def test_stage_refuses_in_memory_persistence(monkeypatch):
    with pytest.raises(RuntimeError, match="persistence=postgres"):
        _app(
            monkeypatch,
            PIA_ENV="stage",
            PIA_PERSISTENCE="memory",
            PIA_LLM_PROVIDER="anthropic",
            PIA_ANTHROPIC_API_KEY="x",
        )
