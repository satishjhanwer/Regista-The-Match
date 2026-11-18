"""Random plans for the truth score: tactical changes planted at unknown times, and unplanted controls.

The demo match plants its storylines at fixed minutes, so the acceptance tests only show that the detectors find
changes where the demo puts them. A truth score needs changes the detectors cannot expect: here each match gets
one or two changes of a random mechanism (press switch, chaos spell, control spell), side, strength, start and
length, and one match in four gets none, so false alarms are measured on matches where nothing happened.

Plans draw from their own ``random.Random``, so the match simulated from a seed and the plan for that seed are
independent. Generated plans have no scripted moments: the simulator only scores scripted shots, so these matches
end goalless. The score is about tactical changes, not goals.
"""

from __future__ import annotations

import random

from .director import Plan, Window
from .roster import AWAY_ID, HOME_ID

MECHANISMS = ("press", "chaos", "control")
CONTROL_SHARE = 0.25
GAP_MIN = 5.0
# Overrides per mechanism and strength, for the side that changes ("own") and its opponent ("opp"). The strong
# variants are the demo's own storylines (S1-S3).
OVERRIDES = {
    ("press", "strong"): {"own": dict(press=0.92, line_push_m=12.0, directness=1.3), "opp": dict(pass_skill=-0.30, tempo=1.1)},
    ("press", "moderate"): {"own": dict(press=0.75, line_push_m=8.0, directness=1.15), "opp": dict(pass_skill=-0.15)},
    ("chaos", "strong"): {"both": dict(pass_skill=-0.95, long_ball=0.33, tempo=0.75, directness=1.8, press=0.65)},
    ("chaos", "moderate"): {"both": dict(pass_skill=-0.6, long_ball=0.25, tempo=0.85, directness=1.5, press=0.55)},
    ("control", "strong"): {"own": dict(pass_skill=0.75, tempo=0.85, directness=0.8), "opp": dict(press=0.25, line_push_m=-4.0)},
    ("control", "moderate"): {"own": dict(pass_skill=0.55, tempo=0.9, directness=0.9), "opp": dict(press=0.3, line_push_m=-2.0)},
}
LABELS = {"press": "{team} switch to a high press", "chaos": "A chaotic spell", "control": "{team} take control"}
NAMES = {HOME_ID: "Northvale", AWAY_ID: "Saltmere"}


def random_plan(seed: int) -> Plan:
    """The plan for one truth-score match: no change (a control) or one or two non-overlapping changes."""
    rng = random.Random(f"truth-plan-{seed}")
    if rng.random() < CONTROL_SHARE:
        return Plan(windows=(), script=())
    windows: list[Window] = []
    for i, mechanism in enumerate(rng.sample(MECHANISMS, rng.choice((1, 2)))):
        for _ in range(50):  # rejection sampling: a window inside one half, clear of the other change
            half = rng.choice((1, 2))
            length = rng.uniform(10.0, 15.0)
            start = (0.0 if half == 1 else 45.0) + rng.uniform(5.0, 44.0 - length)
            end = start + length
            if all(end + GAP_MIN <= w.start_min or start >= w.end_min + GAP_MIN for w in windows):
                break
        else:
            continue
        windows.append(_window(f"P{i + 1}_{mechanism}", mechanism, start, end, rng))
    return Plan(windows=tuple(sorted(windows, key=lambda w: w.start_min)), script=())


def _window(storyline_id: str, mechanism: str, start: float, end: float, rng: random.Random) -> Window:
    difficulty = rng.choice(("strong", "moderate"))
    team = None if mechanism == "chaos" else rng.choice((HOME_ID, AWAY_ID))
    spec = OVERRIDES[(mechanism, difficulty)]
    if team is None:
        overrides = {HOME_ID: spec["both"], AWAY_ID: spec["both"]}
    else:
        overrides = {team: spec["own"], (AWAY_ID if team == HOME_ID else HOME_ID): spec["opp"]}
    label = LABELS[mechanism].format(team=NAMES.get(team, ""))
    return Window(
        storyline_id,
        label,
        round(start, 2),
        round(end, 2),
        f"Planted {difficulty} {mechanism} change for the truth score.",
        (),
        overrides,
        mechanism,
        team,
        difficulty,
    )
