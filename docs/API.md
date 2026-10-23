# Regista API (backend/regista/api)

Run: `cd backend && python -m regista.api` (port 8000). Env vars are listed in `regista/api/app.py`.
Every message and response below is a model in `backend/regista/contracts/stream.py`, generated into
`frontend/src/contracts/stream.ts`. When `frontend/dist` exists, the built app is served at `/`.

## REST

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/health` | `{ok, provider, recorded_renders}` |
| GET | `/api/match` | `MatchMeta` (teams, rosters) |
| GET | `/api/profiles` | preset `FanProfile`s |
| GET / POST | `/api/replay` | status / control `{action, value?, minute?}`; actions `play`, `pause`, `speed` (value = match s per wall s), `seek` (`minute` or `value` = elapsed_s), `step` (value = match seconds), `restart` |
| GET | `/api/insights` | canonical `Insight`s reached so far (incl. `recap`) |
| GET | `/api/momentum` | sampled `MomentumPoint`s `{minute, index}` up to the replay clock (ribbon backfill) |
| GET | `/api/render/{insight_id}` | render on demand: `?profile=&mode=&lang=&team=&player=`; returns `{insight, rendered, trace, source}` |

## WebSocket `/ws?profile=<preset>&mode=&lang=&team=&player=`

Query fields override the preset. Server messages:

- `hello`: `{match, profile, replay}`
- `tick` (about 10/s while playing): `{clock: {period, t, match_clock_s, elapsed_s, display}, score, playing, speed, metrics: {momentum_index, momentum, chaos, control, xg, pressed_share, press_cusum}}`
- `events`: `{events: [{id, type, period, t, team, player, x, y, end_x?, end_y?, outcome?, ...}]}` in absolute pitch metres
- `overlay`: `{payload: OverlayPayload, source, trace: [{agent, action, status, ms, detail}]}`, only verified renders relevant to the profile
- `reset`: after a backwards seek; clear overlays
- `error`: `{error}`

Clients may send `{"type": "control", "action": ..., "value"?, "minute"?}` on the socket.
