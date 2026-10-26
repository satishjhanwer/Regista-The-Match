"""API: replay control, WebSocket overlays per profile, on-demand renders. Template Narrator (no model)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from regista.api.app import create_app
from regista.api.replay import Replay


@pytest.fixture()
def client(sims):
    match, _ = sims[7]
    with TestClient(create_app(match, client=None, autoplay=False)) as c:
        yield c


def drain_until(ws, kind, limit=500):
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"no {kind} message")


def test_rest_basics(client):
    assert client.get("/api/health").json()["ok"]
    assert client.get("/api/match").json()["home"]["name"] == "Northvale FC"
    assert {p["profile_id"] for p in client.get("/api/profiles").json()} >= {"analyst-en", "focus-hi-nvl09"}
    st = client.post("/api/replay", json={"action": "seek", "minute": 30}).json()
    assert st["clock"]["display"].startswith("30:") and not st["playing"]
    assert client.post("/api/replay", json={"action": "speed", "value": 20}).json()["speed"] == 20
    assert client.post("/api/replay", json={"action": "bogus"}).status_code == 422
    series = client.get("/api/momentum").json()
    assert series[0]["minute"] == 0 and 29.5 < series[-1]["minute"] <= 30.5 and all(-1 <= p["index"] <= 1 for p in series)
    kinds = {i["kind"] for i in client.get("/api/insights").json()}
    assert "control_vs_chaos" in kinds and "goal" not in kinds


def test_ws_streams_ticks_events_and_verified_overlays(client):
    client.post("/api/replay", json={"action": "seek", "minute": 61})
    with client.websocket_connect("/ws?profile=analyst-en") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["profile"]["profile_id"] == "analyst-en"
        assert ws.receive_json()["type"] == "tick"
        ws.send_json({"type": "control", "action": "step", "value": 90})
        events = drain_until(ws, "events")
        assert events["events"] and {"id", "type", "x", "y"} <= set(events["events"][0])
        overlay = drain_until(ws, "overlay")
        p = overlay["payload"]
        assert p["insight"]["kind"] == "press_change"
        assert p["rendered"]["verification"]["status"] == "verified"
        assert p["display"]["slot"] == "side_panel"
        assert overlay["source"] == "template" and [s["agent"] for s in overlay["trace"]][-1] == "verifier"


def test_profiles_get_their_own_language(client):
    client.post("/api/replay", json={"action": "seek", "minute": 88})
    with client.websocket_connect("/ws?profile=focus-hi-nvl09") as hi, client.websocket_connect("/ws?profile=casual-es-slm") as es:
        for ws in (hi, es):
            ws.receive_json(), ws.receive_json()
        client.post("/api/replay", json={"action": "step", "value": 60})
        a, b = drain_until(hi, "overlay"), drain_until(es, "overlay")
        assert a["payload"]["insight"]["insight_id"] == b["payload"]["insight"]["insight_id"]
        assert a["payload"]["rendered"]["language"] == "hi" and b["payload"]["rendered"]["language"] == "es"
        assert a["payload"]["insight"]["facts"] == b["payload"]["insight"]["facts"]


def test_render_on_demand_and_seek_back(client):
    client.post("/api/replay", json={"action": "seek", "minute": 40})
    goal = next(i for i in client.get("/api/insights").json() if i["kind"] == "goal")
    r = client.get(f"/api/render/{goal['insight_id']}", params={"mode": "casual", "lang": "es", "team": "SLM"}).json()
    assert r["rendered"]["language"] == "es" and r["rendered"]["verification"]["status"] == "verified"
    assert client.get("/api/render/nope").status_code == 404
    with client.websocket_connect("/ws") as ws:
        ws.receive_json(), ws.receive_json()
        client.post("/api/replay", json={"action": "seek", "minute": 10})
        assert drain_until(ws, "reset")
    assert not any(i["kind"] == "goal" for i in client.get("/api/insights").json())


def test_replay_adds_recaps(sims):
    match, _ = sims[7]
    rp = Replay(match)
    rp.advance_to(rp.end_s)
    kinds = [c.insight.kind for c in rp.history]
    assert kinds.count("recap") == 2 and kinds[-1] == "recap" and kinds[-2] == "period_summary"
    assert rp.finished and rp.clock()["display"].startswith("90+")


def test_recorded_run_is_served_from_cache(sims, tmp_path, monkeypatch):
    import asyncio

    from regista.agents.__main__ import record

    monkeypatch.setenv("REGISTA_LLM_PROVIDER", "none")
    match, _ = sims[7]
    out = tmp_path / "renders.json"
    asyncio.run(record(match, out, ["analyst-en", "casual-es-slm"], 4))
    with TestClient(create_app(match, client=None, cache_path=out, autoplay=False)) as c:
        assert c.get("/api/health").json()["recorded_renders"] > 20
        c.post("/api/replay", json={"action": "seek", "minute": 38})
        with c.websocket_connect("/ws?profile=casual-es-slm") as ws:
            ws.receive_json(), ws.receive_json()
            c.post("/api/replay", json={"action": "step", "value": 60})
            overlay = drain_until(ws, "overlay")
            assert overlay["trace"][0]["agent"] == "cache" and overlay["payload"]["rendered"]["language"] == "es"


def test_every_message_matches_the_stream_contract(client):
    from pydantic import TypeAdapter

    from regista.contracts.stream import StreamMessage

    adapter = TypeAdapter(StreamMessage)
    client.post("/api/replay", json={"action": "seek", "minute": 37})
    seen = set()
    with client.websocket_connect("/ws?profile=casual-en-nvl") as ws:
        ws.send_json({"type": "control", "action": "nope"})
        ws.send_json({"type": "control", "action": "step", "value": 120})
        for _ in range(40):
            msg = ws.receive_json()
            adapter.validate_python(msg)
            seen.add(msg["type"])
            if "overlay" in seen and "error" in seen:
                break
    assert {"hello", "tick", "events", "overlay", "error"} <= seen


def test_serves_built_frontend_next_to_the_api(sims, tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html><title>Regista</title>", encoding="utf-8")
    monkeypatch.setenv("REGISTA_STATIC", str(tmp_path))
    match, _ = sims[7]
    with TestClient(create_app(match, client=None, autoplay=False)) as c:
        assert "<title>Regista</title>" in c.get("/").text
        assert c.get("/api/health").json()["ok"]


def test_resume_reaudits_a_recorded_run(sims, tmp_path, monkeypatch):
    import asyncio
    import json

    from regista.agents.__main__ import record

    monkeypatch.setenv("REGISTA_LLM_PROVIDER", "none")
    match, _ = sims[7]
    out = tmp_path / "renders.json"
    asyncio.run(record(match, out, ["analyst-en"], 2, {"goal"}))
    data = json.loads(out.read_text(encoding="utf-8"))
    data["renders"][0]["rendered"]["claims"][0]["text"] = "Vukovic scored his second goal."  # now wrong: he had 1
    data["renders"][0]["rendered"]["body"] = " ".join(c["text"] for c in data["renders"][0]["rendered"]["claims"])
    out.write_text(json.dumps(data), encoding="utf-8")
    asyncio.run(record(match, out, ["analyst-en"], 2, {"goal"}, resume=out))
    again = json.loads(out.read_text(encoding="utf-8"))
    assert all(s["agent"] != "cache" for r in again["renders"] for s in r["trace"])
    assert "second goal" not in again["renders"][0]["rendered"]["body"]
