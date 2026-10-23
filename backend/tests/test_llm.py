import pytest

from regista.llm import build_chat_client, resolve_provider


def test_defaults_to_none_without_config():
    assert resolve_provider({}) == "none"
    assert build_chat_client("none") is None


def test_auto_detect_order_prefers_foundry():
    env = {
        "FOUNDRY_PROJECT_ENDPOINT": "https://x.services.ai.azure.com/api/projects/p",
        "FOUNDRY_MODEL": "m",
        "OPENAI_BASE_URL": "http://localhost:11434/v1",
        "OPENAI_MODEL": "qwen2.5",
    }
    assert resolve_provider(env) == "foundry"


def test_auto_detect_local_endpoint():
    assert resolve_provider({"OPENAI_BASE_URL": "http://localhost:11434/v1", "OPENAI_MODEL": "qwen2.5"}) == "openai_compat"


def test_explicit_provider_validates_required_vars():
    with pytest.raises(ValueError, match="needs"):
        resolve_provider({"REGISTA_LLM_PROVIDER": "foundry"})
    with pytest.raises(ValueError, match="expected one of"):
        resolve_provider({"REGISTA_LLM_PROVIDER": "bogus"})


def test_explicit_none_wins_over_detected():
    assert resolve_provider({"REGISTA_LLM_PROVIDER": "none", "FOUNDRY_MODEL": "m", "FOUNDRY_PROJECT_ENDPOINT": "e"}) == "none"
