"""LLM provider factory. Every agent gets its chat client from here.

Selected with REGISTA_LLM_PROVIDER:

    foundry        Microsoft Foundry project (target for submission). FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_MODEL
    azure_openai   Azure OpenAI resource. AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_MODEL, optional AZURE_OPENAI_API_KEY
    foundry_local  Microsoft Foundry Local on this machine, no cloud account. FOUNDRY_LOCAL_MODEL (alias, e.g. qwen2.5-3b),
                   optional FOUNDRY_LOCAL_ENDPOINT (default: discovered with the foundry CLI)
    openai_compat  Any OpenAI-compatible endpoint (Ollama, LM Studio, a hosted API). OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_API_KEY
    none           No LLM. Agents fall back to deterministic templates (tests, CI, offline demo)

If unset, the first provider whose required variables are present wins, in the order above, ending at "none".
Imports are lazy so the core package and tests never need the agent extras installed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

PROVIDERS = ("foundry", "azure_openai", "foundry_local", "openai_compat", "none")

_REQUIRED = {
    "foundry": ("FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_MODEL"),
    "azure_openai": ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_MODEL"),
    "foundry_local": ("FOUNDRY_LOCAL_MODEL",),
    "openai_compat": ("OPENAI_BASE_URL", "OPENAI_MODEL"),
    "none": (),
}


def resolve_provider(env: dict[str, str] | None = None) -> str:
    """Provider name from REGISTA_LLM_PROVIDER, or the first fully configured one, or ``none``."""
    env = dict(os.environ) if env is None else env
    explicit = env.get("REGISTA_LLM_PROVIDER", "").strip().lower()
    if explicit:
        if explicit not in PROVIDERS:
            raise ValueError(f"REGISTA_LLM_PROVIDER={explicit!r}; expected one of {PROVIDERS}")
        missing = [k for k in _REQUIRED[explicit] if not env.get(k)]
        if missing:
            raise ValueError(f"provider {explicit!r} needs {missing}")
        return explicit
    for name in PROVIDERS:
        if all(env.get(k) for k in _REQUIRED[name]):
            return name
    return "none"


_MODEL_VAR = {
    "foundry": "FOUNDRY_MODEL",
    "azure_openai": "AZURE_OPENAI_MODEL",
    "foundry_local": "FOUNDRY_LOCAL_MODEL",
    "openai_compat": "OPENAI_MODEL",
}


def describe_provider(provider: str | None = None) -> str:
    """``provider/model`` for provenance in traces and recordings, or ``templates`` when no model is configured."""
    provider = provider or resolve_provider()
    if provider == "none":
        return "templates"
    return f"{provider}/{os.getenv(_MODEL_VAR[provider], '?')}"


def build_chat_client(provider: str | None = None) -> Any | None:
    """Return an Agent Framework chat client, or None for the deterministic fallback."""
    provider = provider or resolve_provider()

    if provider == "foundry":
        from agent_framework.foundry import FoundryChatClient
        from azure.identity import DefaultAzureCredential

        return FoundryChatClient(
            project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
            model=os.environ["FOUNDRY_MODEL"],
            credential=DefaultAzureCredential(),
        )

    if provider == "azure_openai":
        from agent_framework.openai import OpenAIChatClient

        endpoint, model = os.environ["AZURE_OPENAI_ENDPOINT"], os.environ["AZURE_OPENAI_MODEL"]
        if key := os.getenv("AZURE_OPENAI_API_KEY"):
            return OpenAIChatClient(api_key=key, azure_endpoint=endpoint, model=model)
        from azure.identity import DefaultAzureCredential

        return OpenAIChatClient(credential=DefaultAzureCredential(), azure_endpoint=endpoint, model=model)

    if provider == "foundry_local":
        from agent_framework.openai import OpenAIChatCompletionClient

        # Chat completions, as FoundryLocalClient uses: Foundry Local does not keep Responses API history.
        endpoint, model_id = foundry_local_endpoint(os.environ["FOUNDRY_LOCAL_MODEL"])
        return OpenAIChatCompletionClient(base_url=f"{endpoint}/v1", model=model_id, api_key="foundry-local")

    if provider == "openai_compat":
        from agent_framework.openai import OpenAIChatClient

        return OpenAIChatClient(
            base_url=os.environ["OPENAI_BASE_URL"],
            model=os.environ["OPENAI_MODEL"],
            api_key=os.getenv("OPENAI_API_KEY") or "not-needed",
        )

    return None


def _foundry(*args: str) -> dict:
    exe = shutil.which("foundry")
    if exe is None:
        raise RuntimeError("Foundry Local is not installed (winget install Microsoft.FoundryLocal)")
    out = subprocess.run([exe, *args, "--output", "json"], capture_output=True, text=True, timeout=600, check=True).stdout
    return json.loads(out[out.index("{") :])


def foundry_local_endpoint(alias: str) -> tuple[str, str]:
    """Start Foundry Local if needed, load ``alias``, and return (endpoint, model id) of its OpenAI-compatible API.

    Agent Framework's ``FoundryLocalClient`` pins ``foundry-local-sdk`` 0.5.1, which discovers the service with
    ``foundry service status``; current Foundry Local CLIs (0.12+) renamed that to ``foundry server``. Underneath it is
    an OpenAI chat-completions client on the local Foundry service, so we discover the same endpoint with the current
    CLI and talk to it through Agent Framework's OpenAI chat-completions client.
    """
    endpoint = os.getenv("FOUNDRY_LOCAL_ENDPOINT")
    if not endpoint:
        status = _foundry("server", "status")
        if not status.get("running"):
            _foundry("server", "start")
            status = _foundry("server", "status")
        endpoint = status["webUrls"][0]
    _foundry("model", "load", alias)
    loaded = _foundry("model", "list", "--loaded")["models"]
    model_id = next((m["id"] for m in loaded if alias in (m["alias"], m["id"])), None)
    if model_id is None:
        raise RuntimeError(f"Foundry Local did not load {alias!r}")
    return endpoint.rstrip("/"), model_id
