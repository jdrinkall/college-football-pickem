"""Draft picks, keyed by season.

Each season has its own draft, so picks must always be looked up by the season
being rendered. Scoring a season's records against a different season's picks
produces wrong totals silently, which is why there is no season-less accessor here.

To add a season: add a key to PICKS_BY_SEASON. Everything else — the season
dropdown, the allowed-season clamp, the history page — derives from this dict.
A player is counted as having played a season only if their list is non-empty,
so a scaffolded season with empty lists does not dilute career totals.
"""
from __future__ import annotations

PICKS_BY_SEASON: dict[int, dict[str, list[str]]] = {
    2025: {
        "Sean": [
            "Ohio State",
            "Miami",
            "LSU",
            "Navy",
            "Army",
            "Jacksonville State",
        ],
        "Randy": [
            "Notre Dame",
            "Kansas State",
            "Louisiana",
            "Utah",
            "East Carolina",
            "Western Kentucky",
        ],
        "Justin": [
            "Oregon",
            "Clemson",
            "Indiana",
            "Georgia Tech",
            "Tennessee",
            "Nebraska",
        ],
        "Matthew": [
            "Penn State",
            "Memphis",
            "SMU",
            "Illinois",
            "Oklahoma",
            "Miami (OH)",
        ],
        "Futa": [
            "Georgia",
            "Arizona State",
            "South Carolina",
            "Buffalo",
            "Arkansas State",
            "Colorado State",
        ],
        "Ben": [
            "Texas",
            "UNLV",
            "Michigan",
            "Ole Miss",
            "Kansas",
            "UTSA",
        ],
        "Austin": [
            "Toledo",
            "Alabama",
            "San José State",
            "Iowa State",
            "Florida",
            "Baylor",
        ],
        "Nick": [
            "Liberty",
            "James Madison",
            "BYU",
            "Georgia Southern",
            "Missouri",
            "USC",
        ],
        "Oliver": [
            "Boise State",
            "Tulane",
            "Texas Tech",
            "Louisville",
            "Texas A&M",
            "Ohio",
        ],
    },
    # 2026 draft has not happened yet. Fill in the team lists below once it does —
    # no other code changes are needed. Drop or add players here if the roster changes.
    2026: {
        "Sean": [],
        "Randy": [],
        "Justin": [],
        "Matthew": [],
        "Futa": [],
        "Ben": [],
        "Austin": [],
        "Nick": [],
        "Oliver": [],
    },
}

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
