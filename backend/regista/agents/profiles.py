"""Fan profiles: presets, relevance (what a viewer sees) and overlay placement.

Personalization never changes facts. It decides whether an insight is shown to a
profile, with what priority and in which overlay slot, and the Narrator decides
how it is told.
"""

from __future__ import annotations

from ..contracts.insight import DisplayDirective, FanProfile, Insight, OverlaySlot

PRESETS: dict[str, FanProfile] = {
    p.profile_id: p
    for p in (
        FanProfile(profile_id="analyst-en", mode="analyst", language="en"),
        FanProfile(profile_id="casual-en-nvl", mode="casual", language="en", favorite_team_id="NVL"),
        FanProfile(profile_id="casual-es-slm", mode="casual", language="es", favorite_team_id="SLM"),
        FanProfile(profile_id="focus-hi-nvl09", mode="player_focus", language="hi", favorite_team_id="NVL", focus_player_id="NVL-09"),
        FanProfile(profile_id="analyst-es", mode="analyst", language="es", metric_of_interest="press"),
    )
}
LANGUAGES = ("en", "es", "hi")

SLOT: dict[str, OverlaySlot] = {
    "goal": "lower_third",
    "shot_quality": "lower_third",
    "key_pass": "lower_third",
    "player_tag": "player_tag",
    "milestone": "lower_third",
    "momentum_shift": "ticker",
    "press_change": "side_panel",
    "control_vs_chaos": "side_panel",
    "rhythm_shift": "side_panel",
    "period_summary": "top_bar",
    "recap": "side_panel",
}

# metric_of_interest -> insight kinds it boosts
INTEREST = {
    "press": {"press_change"},
    "xg": {"shot_quality", "key_pass"},
    "momentum": {"momentum_shift", "control_vs_chaos"},
    "speed": {"player_tag"},
}


def profile_from_params(
    profile_id: str | None = None,
    mode: str | None = None,
    language: str | None = None,
    team: str | None = None,
    player: str | None = None,
    metric: str | None = None,
) -> FanProfile:
    """A preset, optionally overridden field by field. The id encodes every field, so caches key on it safely."""
    base = PRESETS.get(profile_id or "", PRESETS["analyst-en"])
    fields = {
        "mode": mode or base.mode,
        "language": language if language in LANGUAGES else base.language,
        "favorite_team_id": team if team is not None else base.favorite_team_id,
        "focus_player_id": player if player is not None else base.focus_player_id,
        "metric_of_interest": metric if metric is not None else base.metric_of_interest,
    }
    for k in ("favorite_team_id", "focus_player_id", "metric_of_interest"):
        fields[k] = fields[k] or None
    if profile_id in PRESETS and all(getattr(base, k) == v for k, v in fields.items()):
        return base
    pid = "-".join(str(fields[k] or "_") for k in ("mode", "language", "favorite_team_id", "focus_player_id", "metric_of_interest"))
    return FanProfile(profile_id=pid, **fields)


def relevance(insight: Insight, profile: FanProfile) -> int | None:
    """Priority of the insight for this viewer (1-5), or None to hide it."""
    p = insight.priority
    if insight.kind in ("period_summary", "recap", "goal"):
        return p
    involved = profile.focus_player_id is not None and profile.focus_player_id in insight.entities.player_ids
    if profile.mode == "player_focus":
        if involved:
            return min(5, p + 1)
        return p if p >= 4 else None
    if profile.mode == "casual" and p <= 2 and insight.kind != "milestone":
        return None
    if profile.metric_of_interest and insight.kind in INTEREST.get(profile.metric_of_interest, ()):
        p += 1
    if profile.favorite_team_id and profile.favorite_team_id in insight.entities.team_ids and profile.mode == "casual":
        p += 1
    return max(1, min(5, p))


def display_for(insight: Insight, profile: FanProfile) -> DisplayDirective | None:
    prio = relevance(insight, profile)
    if prio is None:
        return None
    return DisplayDirective(
        slot=SLOT[insight.kind],
        template_id=f"{insight.kind}.{profile.mode}",
        show_at_match_clock_s=insight.clock.match_clock_s,
        ttl_ms=insight.ttl_ms,
        priority=prio,
    )
