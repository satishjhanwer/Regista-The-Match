"""Synthetic match event contract.

Coordinate system
-----------------
All x/y values are absolute pitch coordinates in metres:
x in [0, 105] along the touchline, y in [0, 68] along the goal line.
Which goal a team attacks depends on the period; see
``MatchMeta.home_attacks_right_first_half`` and ``attacks_right()``.

Clock
-----
``t`` is seconds since the start of the period (stoppage time included,
so t > 2700 means added time). ``match_clock_s`` is the broadcast clock:
period 2 restarts at 2700 regardless of first-half stoppage, so it is not
monotonic across the break. ``elapsed_s`` is monotonic playing time since
kickoff and is what replay ordering and windowing should use.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

PITCH_LENGTH_M = 105.0
PITCH_WIDTH_M = 68.0
PERIOD_LENGTH_S = 2700.0
SCHEMA_VERSION = "1.0"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_serialization_defaults_required=True)


# --------------------------------------------------------------------------- #
# Match metadata
# --------------------------------------------------------------------------- #

PositionGroup = Literal["GK", "DEF", "MID", "FWD"]


class Player(Model):
    player_id: str
    name: str
    short_name: str
    shirt: int
    position: PositionGroup
    role: str = Field(description="Tactical role in the formation, e.g. LCB, CDM, RW")
    career_appearances: int = Field(ge=0, description="Appearances before this match")
    career_goals: int = Field(ge=0, description="Goals before this match")


class Team(Model):
    team_id: str
    name: str
    short_name: str
    primary_color: str
    secondary_color: str
    formation: str
    players: list[Player]


class MatchMeta(Model):
    schema_version: str = SCHEMA_VERSION
    match_id: str
    competition: str
    venue: str
    kickoff_utc: str
    home: Team
    away: Team
    home_attacks_right_first_half: bool
    seed: int
    generator: str


def attacks_right(meta: MatchMeta, team_id: str, period: int) -> bool:
    """True when ``team_id`` attacks the x=105 goal in ``period``."""
    home_right = meta.home_attacks_right_first_half if period == 1 else not meta.home_attacks_right_first_half
    return home_right if team_id == meta.home.team_id else not home_right


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #


class Pressure(Model):
    defenders_within_5m: int = Field(ge=0)
    nearest_defender_m: float = Field(ge=0)
    nearest_defender_id: str | None = None


class FreezeFramePlayer(Model):
    player_id: str
    x: float
    y: float


class BaseEvent(Model):
    event_id: str
    seq: int = Field(ge=0)
    match_id: str
    period: Literal[1, 2]
    t: float = Field(ge=0, description="Seconds since period start")
    match_clock_s: float = Field(ge=0, description="Broadcast clock; period 2 restarts at 2700 so it can overlap 1st-half stoppage")
    elapsed_s: float = Field(ge=0, description="Monotonic playing time since kickoff incl. stoppage; use for replay ordering")
    team_id: str | None = None
    player_id: str | None = None
    possession_id: int = Field(ge=0)
    x: float = Field(ge=0, le=PITCH_LENGTH_M)
    y: float = Field(ge=0, le=PITCH_WIDTH_M)


class PeriodStartEvent(BaseEvent):
    type: Literal["period_start"] = "period_start"


class PeriodEndEvent(BaseEvent):
    type: Literal["period_end"] = "period_end"
    home_score: int
    away_score: int


class PassEvent(BaseEvent):
    type: Literal["pass"] = "pass"
    end_x: float = Field(ge=0, le=PITCH_LENGTH_M)
    end_y: float = Field(ge=0, le=PITCH_WIDTH_M)
    recipient_id: str | None
    outcome: Literal["complete", "incomplete", "out"]
    length_m: float = Field(ge=0)
    height: Literal["ground", "low", "high"]
    duration_s: float = Field(gt=0)
    ball_speed_kmh: float = Field(ge=0, description="Mean ball speed over the pass")
    pressure: Pressure
    receiver_defenders_within_5m: int = Field(ge=0)
    is_cross: bool = False
    is_through_ball: bool = False


class CarryEvent(BaseEvent):
    type: Literal["carry"] = "carry"
    end_x: float = Field(ge=0, le=PITCH_LENGTH_M)
    end_y: float = Field(ge=0, le=PITCH_WIDTH_M)
    distance_m: float = Field(ge=0)
    duration_s: float = Field(gt=0)
    top_speed_kmh: float = Field(ge=0)


class ShotEvent(BaseEvent):
    type: Literal["shot"] = "shot"
    outcome: Literal["goal", "saved", "off_target", "blocked", "woodwork"]
    body_part: Literal["right_foot", "left_foot", "head"]
    shot_speed_kmh: float = Field(ge=0)
    distance_m: float = Field(ge=0, description="Distance to centre of goal")
    angle_rad: float = Field(ge=0, description="Angle subtended by the goal mouth")
    pressure: Pressure
    assist_event_id: str | None = None
    freeze_frame: list[FreezeFramePlayer]


class SaveEvent(BaseEvent):
    type: Literal["save"] = "save"
    shot_event_id: str


class PressureEvent(BaseEvent):
    type: Literal["pressure"] = "pressure"
    target_player_id: str
    distance_m: float = Field(ge=0)
    duration_s: float = Field(gt=0)


class TackleEvent(BaseEvent):
    type: Literal["tackle"] = "tackle"
    opponent_id: str
    outcome: Literal["won", "lost"]


class InterceptionEvent(BaseEvent):
    type: Literal["interception"] = "interception"
    pass_event_id: str


class ClearanceEvent(BaseEvent):
    type: Literal["clearance"] = "clearance"
    end_x: float = Field(ge=0, le=PITCH_LENGTH_M)
    end_y: float = Field(ge=0, le=PITCH_WIDTH_M)


class FoulEvent(BaseEvent):
    type: Literal["foul"] = "foul"
    fouled_player_id: str
    card: Literal["yellow", "red"] | None = None


class SprintEvent(BaseEvent):
    """Physical-tracking derived event: a player's run with peak speed and distance."""

    type: Literal["sprint"] = "sprint"
    top_speed_kmh: float = Field(ge=0)
    distance_m: float = Field(ge=0)
    duration_s: float = Field(gt=0)


PossessionCause = Literal[
    "kickoff",
    "tackle",
    "interception",
    "out_of_play",
    "save",
    "clearance",
    "foul",
    "goal_kick",
]


class PossessionChangeEvent(BaseEvent):
    type: Literal["possession_change"] = "possession_change"
    from_team_id: str | None
    to_team_id: str
    cause: PossessionCause


MatchEvent = Annotated[
    PeriodStartEvent
    | PeriodEndEvent
    | PassEvent
    | CarryEvent
    | ShotEvent
    | SaveEvent
    | PressureEvent
    | TackleEvent
    | InterceptionEvent
    | ClearanceEvent
    | FoulEvent
    | SprintEvent
    | PossessionChangeEvent,
    Field(discriminator="type"),
]


class MatchFile(Model):
    """A full simulated match: metadata plus the ordered event stream."""

    meta: MatchMeta
    events: list[MatchEvent]


# --------------------------------------------------------------------------- #
# Ground truth (never streamed to the pipeline; used for evaluation only)
# --------------------------------------------------------------------------- #


class Storyline(Model):
    storyline_id: str
    label: str
    start_clock_s: float
    end_clock_s: float
    description: str
    expected_signals: list[str]


class TruthShot(Model):
    event_id: str
    xg_true: float = Field(ge=0, le=1)


class GroundTruth(Model):
    match_id: str
    seed: int
    final_score: dict[str, int]
    storylines: list[Storyline]
    scripted_event_ids: dict[str, str]
    shots: list[TruthShot]
    pass_model: dict[str, float]
    xg_model: dict[str, float]


def match_minute(period: int, t: float) -> float:
    """Football minute for windowing: stoppage folds into the last minute of its half (44.99 / 89.99)."""
    return min(t, PERIOD_LENGTH_S - 0.01) / 60.0 + (45.0 if period == 2 else 0.0)


def format_clock(period: int, t: float) -> str:
    """Broadcast clock string: '23:41', '67:05', stoppage as '45+01:12' or '90+03:20'."""
    base = 0 if period == 1 else 45
    if t < PERIOD_LENGTH_S:
        return f"{base + int(t // 60)}:{int(t % 60):02d}"
    extra = t - PERIOD_LENGTH_S
    return f"{base + 45}+{int(extra // 60):02d}:{int(extra % 60):02d}"
