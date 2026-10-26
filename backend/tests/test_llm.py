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


def test_foundry_local_resolves_endpoint_and_variant(monkeypatch):
    import regista.llm as llm

    calls = []

    def fake(*args):
        calls.append(args)
        if args[:2] == ("server", "status"):
            return {"running": True, "webUrls": ["http://127.0.0.1:65272/"]}
        if args[:2] == ("model", "list"):
            return {"models": [{"alias": "qwen2.5-3b", "id": "qwen2.5-3b-instruct-generic-gpu:2"}]}
        return {"success": True}

    monkeypatch.delenv("FOUNDRY_LOCAL_ENDPOINT", raising=False)
    monkeypatch.setattr(llm, "_foundry", fake)
    assert llm.foundry_local_endpoint("qwen2.5-3b") == ("http://127.0.0.1:65272", "qwen2.5-3b-instruct-generic-gpu:2")
    assert ("model", "load", "qwen2.5-3b") in calls
    monkeypatch.setenv("FOUNDRY_LOCAL_ENDPOINT", "http://127.0.0.1:5000")  # explicit endpoint: no server discovery
    monkeypatch.setattr(llm, "_foundry", lambda *a: {"models": []} if a[:2] == ("model", "list") else {})
    with pytest.raises(RuntimeError, match="did not load"):
        llm.foundry_local_endpoint("nope")


def test_describe_provider(monkeypatch):
    from regista.llm import describe_provider

    assert describe_provider("none") == "templates"
    monkeypatch.setenv("FOUNDRY_LOCAL_MODEL", "qwen2.5-3b-instruct-generic-cpu:2")
    assert describe_provider("foundry_local") == "foundry_local/qwen2.5-3b-instruct-generic-cpu:2"
