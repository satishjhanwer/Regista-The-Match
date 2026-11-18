"""The static demo bundle agrees with the live hub: same overlays per viewer, same ticks, nothing unverified."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

from regista.agents.orchestrator import WarmPath
from regista.agents.profiles import PRESETS
from regista.api.app import DEFAULT_MATCH, load_match
from regista.api.hub import Hub, Viewer
from regista.api.replay import Replay

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "RGS-2026-0001.renders.foundry-local.json"


def _module():
    spec = importlib.util.spec_from_file_location("export_static", ROOT / "backend" / "scripts" / "export_static.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bundle():
    return asyncio.run(_module().build(DEFAULT_MATCH, CACHE))


def hub_overlays(profile_id: str) -> tuple[list[str], dict]:
    """Play the whole match through the real hub with one viewer; the overlay ids it received, and the final tick."""
    match = load_match(DEFAULT_MATCH)
    hub = Hub(Replay(match), WarmPath(match.meta, None, cache=WarmPath.load_cache(CACHE)), autoplay=False)
    got: list[dict] = []

    async def send(msg: dict) -> None:
        got.append(msg)

    async def run():
        await hub.connect(Viewer(send, PRESETS[profile_id]))
        while not hub.replay.finished:
            await hub.step(30.0)
        await hub.wait_renders()

    asyncio.run(run())
    ids = [m["payload"]["insight"]["insight_id"] for m in got if m["type"] == "overlay"]
    return ids, hub.tick_message().model_dump(mode="json")


@pytest.mark.parametrize("profile_id", ["analyst-en", "casual-es-slm", "focus-hi-nvl09"])
def test_each_viewer_gets_what_the_live_hub_sends(bundle, profile_id):
    ids, final_tick = hub_overlays(profile_id)
    shown = [r["id"] for r in bundle["renders"][profile_id] if r["display"] is not None]
    assert sorted(shown) == sorted(ids) and ids
    assert bundle["ticks"][-1]["metrics"] == final_tick["metrics"]
    assert bundle["ticks"][-1]["score"] == final_tick["score"] == {"NVL": 2, "SLM": 1}


def test_bundle_is_complete_and_verified(bundle):
    match = load_match(DEFAULT_MATCH)
    assert len(bundle["events"]) == len(bundle["elapsed"]) == len(bundle["ticks"]) == len(match.events)
    replay = Replay(match)
    replay.advance_to(replay.end_s)
    assert [i for _, i in bundle["fired"]] == [c.insight.insight_id for c in replay.history]
    assert all(r["rendered"]["verification"]["status"] in ("verified", "revised") for rows in bundle["renders"].values() for r in rows)
    ids = {p["profile_id"] for p in bundle["profiles"]}
    assert set(PRESETS) <= ids and len(ids) == len(bundle["profiles"]) >= 30
    sources = {r["source"] for r in bundle["renders"]["analyst-en"]}
    assert sources & {"llm", "llm_revised", "template_fallback"}, "the recorded Foundry Local run is in the bundle"
