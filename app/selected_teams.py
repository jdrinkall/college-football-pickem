"""Draft picks, loaded from the CSV files in drafts/.

One CSV per season, named after the year: drafts/2026.csv. Columns are
`player,team`, one row per pick. Row order sets the display order of players;
rows with an empty team are ignored, so a half-finished draft still loads.

Picks are always looked up by season — scoring a season's records against another
season's draft produces wrong totals silently, so there is no season-less accessor.
Adding a season means adding a CSV; nothing here needs editing.

Run `python scripts/validate_draft.py 2026` after editing a draft file. Team names
must match CFBD exactly ("San José State", "Miami (OH)"), and the validator checks
that for you rather than letting a typo quietly score zero all season.
"""
from __future__ import annotations

import csv
import os
import re
from datetime import datetime

DRAFTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "drafts"
)

def _load_draft(path: str) -> dict[str, list[str]]:
    """Read one season CSV into {player: [teams]}, preserving row order."""
    picks: dict[str, list[str]] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            player = (row.get("player") or "").strip()
            team = (row.get("team") or "").strip()
            if not player:
                continue
            picks.setdefault(player, [])
            if team:
                picks[player].append(team)
    return picks

def _load_all() -> dict[int, dict[str, list[str]]]:
    seasons: dict[int, dict[str, list[str]]] = {}
    if not os.path.isdir(DRAFTS_DIR):
        return seasons
    for name in sorted(os.listdir(DRAFTS_DIR)):
        match = re.fullmatch(r"(\d{4})\.csv", name)
        if match:
            seasons[int(match.group(1))] = _load_draft(os.path.join(DRAFTS_DIR, name))
    return seasons

PICKS_BY_SEASON: dict[int, dict[str, list[str]]] = _load_all()

# An empty drafts/ directory would otherwise break every page at import time.
if not PICKS_BY_SEASON:
    PICKS_BY_SEASON = {datetime.today().year: {}}

SEASONS: list[int] = sorted(PICKS_BY_SEASON)
LATEST_SEASON: int = SEASONS[-1]


def picks_for(season: int) -> dict[str, list[str]]:
    """Every player's picks for a season, including players with no picks yet."""
    return PICKS_BY_SEASON.get(season, {})


def teams_for(season: int) -> list[str]:
    """Distinct teams drafted in a season."""
    return sorted({team for teams in picks_for(season).values() for team in teams})


def played_seasons(player: str) -> list[int]:
    """Seasons where this player actually has picks (an empty draft doesn't count)."""
    return [s for s in SEASONS if PICKS_BY_SEASON[s].get(player)]


def latest_drafted_season() -> int:
    """Newest season that actually has picks in it.

    Not the same as LATEST_SEASON. A season's CSV is usually added before its
    draft happens, and until it is filled in every row is blank — so a page
    about "the teams you have this season" should stay on the last real draft
    rather than jumping to an empty one the moment next year's file appears.
    """
    for season in reversed(SEASONS):
        if any(PICKS_BY_SEASON[season].values()):
            return season
    return LATEST_SEASON


def all_players() -> list[str]:
    """Every player across all seasons, ordered by the season they first appear in."""
    ordered: list[str] = []
    for season in SEASONS:
        for player in PICKS_BY_SEASON[season]:
            if player not in ordered:
                ordered.append(player)
    return ordered


def all_teams() -> list[str]:
    """Every team drafted in any season — the full set worth keeping records for."""
    return sorted({team for season in SEASONS for team in teams_for(season)})
