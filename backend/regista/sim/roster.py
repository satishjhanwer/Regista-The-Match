"""Fictional clubs and players. No real club, player, crest or competition is used."""

from __future__ import annotations

from ..contracts.events import MatchMeta, Player, Team

# role -> (x, y) base position in the team's attacking frame (attacking towards x=105).
# Facing +x, the right flank is low y.
FORMATION_433: dict[str, tuple[float, float]] = {
    "GK": (5.0, 34.0),
    "RB": (28.0, 9.0),
    "RCB": (21.0, 25.0),
    "LCB": (21.0, 43.0),
    "LB": (28.0, 59.0),
    "CDM": (39.0, 34.0),
    "RCM": (48.0, 21.0),
    "LCM": (48.0, 47.0),
    "RW": (68.0, 9.0),
    "ST": (74.0, 34.0),
    "LW": (68.0, 59.0),
}

_GROUP = {
    "GK": "GK",
    "RB": "DEF",
    "RCB": "DEF",
    "LCB": "DEF",
    "LB": "DEF",
    "CDM": "MID",
    "RCM": "MID",
    "LCM": "MID",
    "RW": "FWD",
    "ST": "FWD",
    "LW": "FWD",
}

# (role, shirt, name, short_name, career_apps, career_goals)
_NORTHVALE = [
    ("GK", 1, "Tomas Brenner", "Brenner", 212, 0),
    ("RB", 2, "Kofi Mensah-Hale", "Mensah-Hale", 88, 3),
    ("RCB", 5, "Liam Okafor", "Okafor", 154, 9),
    ("LCB", 6, "Jonas Elmqvist", "Elmqvist", 131, 6),
    ("LB", 3, "Rafael Duarte", "Duarte", 97, 4),
    ("CDM", 4, "Idris Calloway", "Calloway", 176, 11),
    ("RCM", 8, "Mateus Ferrante", "Ferrante", 64, 7),
    ("LCM", 10, "Elias Nordgren", "Nordgren", 143, 29),
    ("RW", 7, "Sami Haddad", "Haddad", 72, 18),
    ("ST", 9, "Dario Vukovic", "Vukovic", 118, 48),
    ("LW", 11, "Noah Achterberg", "Achterberg", 45, 9),
]

_SALTMERE = [
    ("GK", 1, "Aleksander Rudnik", "Rudnik", 165, 0),
    ("RB", 2, "Callum Fairweather", "Fairweather", 109, 2),
    ("RCB", 4, "Yusuf Demirel", "Demirel", 140, 8),
    ("LCB", 5, "Pieter van Raalte", "van Raalte", 77, 3),
    ("LB", 3, "Marcus Oyelaran", "Oyelaran", 58, 1),
    ("CDM", 6, "Hugo Lindqvist", "Lindqvist", 99, 6),
    ("RCM", 8, "Teo Marchetti", "Marchetti", 123, 14),
    ("LCM", 14, "Kenji Arakawa", "Arakawa", 66, 5),
    ("RW", 7, "Bastien Roux", "Roux", 91, 21),
    ("ST", 9, "Ilan Shapira", "Shapira", 102, 37),
    ("LW", 11, "Ade Balogun", "Balogun", 39, 8),
]


def _team(team_id: str, name: str, short: str, primary: str, secondary: str, rows: list) -> Team:
    players = [
        Player(
            player_id=f"{team_id}-{shirt:02d}",
            name=full,
            short_name=sn,
            shirt=shirt,
            position=_GROUP[role],
            role=role,
            career_appearances=apps,
            career_goals=goals,
        )
        for role, shirt, full, sn, apps, goals in rows
    ]
    return Team(
        team_id=team_id,
        name=name,
        short_name=short,
        primary_color=primary,
        secondary_color=secondary,
        formation="4-3-3",
        players=players,
    )


HOME_ID = "NVL"
AWAY_ID = "SLM"


def build_meta(match_id: str, seed: int, generator: str) -> MatchMeta:
    return MatchMeta(
        match_id=match_id,
        competition="Regista Synthetic League",
        venue="Harbourline Park",
        kickoff_utc="2026-10-24T14:00:00Z",
        home=_team(HOME_ID, "Northvale FC", "NVL", "#1F4E79", "#F2C14E", _NORTHVALE),
        away=_team(AWAY_ID, "Saltmere Athletic", "SLM", "#8B1E3F", "#E8E3D9", _SALTMERE),
        home_attacks_right_first_half=True,
        seed=seed,
        generator=generator,
    )
