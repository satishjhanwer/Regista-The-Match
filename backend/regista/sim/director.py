"""The director: time-varying team behaviour plus scripted moments.

The simulator is stochastic everywhere except where the director plants a
storyline. Planted storylines guarantee that the demo contains a control
phase, a chaotic spell, a pressing shift, a sprint and three goals, while the
rest of the match stays organic. Ground truth for every storyline is written
to the truth file so the analytics layer can be evaluated against it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..contracts.events import Storyline
from .roster import AWAY_ID, HOME_ID


@dataclass(frozen=True)
class TeamParams:
    """Behaviour knobs for one team: pass skill, press, defensive line, long-ball rate, tempo, directness."""

    pass_skill: float = 0.0  # additive logit offset on pass completion
    press: float = 0.4  # 0..1 pressing intensity out of possession
    line_push_m: float = 0.0  # extra defensive-line height out of possession
    long_ball: float = 0.10  # probability a pass is a long ball
    tempo: float = 1.0  # multiplier on gaps between actions (lower = faster)
    directness: float = 1.0  # preference for forward passes
    shot_appetite: float = 1.0


BASE: dict[str, TeamParams] = {
    HOME_ID: TeamParams(pass_skill=0.25, press=0.45, long_ball=0.08),
    AWAY_ID: TeamParams(pass_skill=0.20, press=0.35, long_ball=0.12),
}


@dataclass(frozen=True)
class Window:
    """A storyline: a time window and the TeamParams overrides that plant it."""

    storyline_id: str
    label: str
    start_min: float
    end_min: float
    description: str
    expected_signals: tuple[str, ...]
    overrides: dict  # team_id -> dict of TeamParams overrides


WINDOWS: list[Window] = [
    Window(
        "S1_home_control",
        "Northvale control the tempo",
        0,
        25,
        "Northvale keep the ball in long, low-risk sequences; Saltmere sit off in a mid block.",
        ("home pass completion high", "long home possession sequences", "low possession-sequence entropy"),
        {
            HOME_ID: dict(pass_skill=0.75, tempo=0.85, directness=0.8),
            AWAY_ID: dict(press=0.25, line_push_m=-4.0),
        },
    ),
    Window(
        "S2_chaos_spell",
        "A chaotic spell",
        25,
        40,
        "Both sides go direct; turnovers spike and nobody settles.",
        ("turnover rate up for both teams", "long-ball share up", "short possession sequences"),
        {
            HOME_ID: dict(pass_skill=-0.95, long_ball=0.32, tempo=0.75, directness=1.8, press=0.65),
            AWAY_ID: dict(pass_skill=-0.95, long_ball=0.35, tempo=0.75, directness=1.8, press=0.65),
        },
    ),
    Window(
        "S3_away_press_shift",
        "Saltmere switch to a high press",
        58,
        72,
        "Saltmere push their line up and press high; Northvale's build-up from the back breaks down.",
        (
            "away pressure events per home pass up",
            "home PPDA-against down / away PPDA down",
            "home pass completion in own half down",
            "turnovers in home defensive third up",
        ),
        {
            HOME_ID: dict(pass_skill=-0.30, tempo=1.1),
            AWAY_ID: dict(press=0.92, line_push_m=12.0, directness=1.3),
        },
    ),
    Window(
        "S4_home_go_long",
        "Northvale go long to beat the press",
        72,
        96,
        "Northvale bypass the press with longer passes; Saltmere's press fades with fatigue.",
        ("home long-ball share up", "away pressure events fall from S3 levels"),
        {
            HOME_ID: dict(long_ball=0.30, pass_skill=0.40, directness=1.4),
            AWAY_ID: dict(press=0.55, line_push_m=4.0),
        },
    ),
]


@dataclass(frozen=True)
class ScriptedMoment:
    """A scripted moment (goal or sprint) and when it happens."""

    moment_id: str
    kind: str  # goal_home_through_ball | goal_away_high_press | goal_home_header | sprint_counter
    period: int
    t: float  # seconds into the period
    team_id: str
    description: str


SCRIPT: list[ScriptedMoment] = [
    ScriptedMoment(
        "G1",
        "goal_home_through_ball",
        1,
        38 * 60 + 12,
        HOME_ID,
        "Nordgren splits the lines with a through ball; Vukovic finishes.",
    ),
    ScriptedMoment(
        "G2",
        "goal_away_high_press",
        2,
        (64 * 60 + 30) - 2700,
        AWAY_ID,
        "The press pays off: Lindqvist wins it high, Shapira scores.",
    ),
    ScriptedMoment(
        "M1",
        "sprint_counter",
        2,
        (76 * 60 + 40) - 2700,
        AWAY_ID,
        "Balogun breaks at 34.8 km/h, the fastest run of the match.",
    ),
    ScriptedMoment(
        "G3",
        "goal_home_header",
        2,
        (88 * 60 + 5) - 2700,
        HOME_ID,
        "Haddad crosses from the right; Vukovic heads the winner for his brace.",
    ),
]

STOPPAGE_S = {1: 125.0, 2: 250.0}


class Director:
    """Applies storyline overrides by match clock and releases each scripted moment once."""

    def __init__(self) -> None:
        self._done: set[str] = set()

    def params(self, team_id: str, match_clock_s: float) -> TeamParams:
        """Team parameters at a match clock, with any storyline overrides applied."""
        p = BASE[team_id]
        minute = match_clock_s / 60.0
        for w in WINDOWS:
            if w.start_min <= minute < w.end_min and team_id in w.overrides:
                p = replace(p, **w.overrides[team_id])
        return p

    def due(self, period: int, t: float) -> ScriptedMoment | None:
        """The next scripted moment due at this time, or None. Each moment is released once."""
        for m in SCRIPT:
            if m.moment_id not in self._done and m.period == period and t >= m.t:
                self._done.add(m.moment_id)
                return m
        return None

    @staticmethod
    def storylines() -> list[Storyline]:
        """The planted storylines, for the truth file."""
        return [
            Storyline(
                storyline_id=w.storyline_id,
                label=w.label,
                start_clock_s=w.start_min * 60,
                end_clock_s=w.end_min * 60,
                description=w.description,
                expected_signals=list(w.expected_signals),
            )
            for w in WINDOWS
        ]
