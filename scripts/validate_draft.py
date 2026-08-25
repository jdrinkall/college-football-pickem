"""Check a draft CSV before it goes live.

    python scripts/validate_draft.py 2026

Catches the things that fail silently on the website rather than loudly here:
a misspelled team scores zero wins all season, a duplicate means two people are
credited for the same team, and a short roster quietly undercounts someone.

Team names are checked against CFBD's official FBS list for that season, using
the key in .env. With no network it falls back to drafts/fbs_teams_<year>.txt,
and failing that it checks only the things that don't need a team list.
"""
from __future__ import annotations

import csv
import difflib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PICKS_PER_PLAYER = 6


def load_rows(path: str) -> list[tuple[int, str, str]]:
    """(line number, player, team) for every row, blanks included."""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            rows.append((i, (row.get("player") or "").strip(), (row.get("team") or "").strip()))
    return rows


def official_teams(year: int) -> tuple[set[str], str]:
    """Valid team names for a season, and where they came from."""
    try:
        import httpx
        from dotenv import load_dotenv

        load_dotenv(os.path.join(ROOT, ".env"))
        key = os.getenv("CFBD_API_KEY")
        if key:
            r = httpx.get(
                "https://api.collegefootballdata.com/teams/fbs",
                params={"year": year},
                headers={"Authorization": f"Bearer {key}"},
                timeout=30,
            )
            if r.status_code == 200:
                return {t["school"] for t in r.json()}, "CFBD"
    except Exception:
        pass

    cached = os.path.join(ROOT, "drafts", f"fbs_teams_{year}.txt")
    if os.path.exists(cached):
        names = set()
        with open(cached, encoding="utf-8") as f:
            for line in f:
                if line.startswith("  ") and line.strip():
                    names.add(line.strip())
        if names:
            return names, f"drafts/fbs_teams_{year}.txt"

    return set(), ""


def main() -> int:
    year = sys.argv[1] if len(sys.argv) > 1 else None
    if not year or not re.fullmatch(r"\d{4}", year):
        print("usage: python scripts/validate_draft.py <year>")
        return 2

    path = os.path.join(ROOT, "drafts", f"{year}.csv")
    if not os.path.exists(path):
        print(f"ERROR  no such file: drafts/{year}.csv")
        return 2

    rows = load_rows(path)
    valid, source = official_teams(int(year))

    errors: list[str] = []
    warnings: list[str] = []

    # Roster shape
    players: dict[str, list[str]] = {}
    for _, player, team in rows:
        if player:
            players.setdefault(player, [])
            if team:
                players[player].append(team)

    if not players:
        print(f"ERROR  drafts/{year}.csv has no player rows")
        return 1

    for player, picks in players.items():
        if len(picks) < PICKS_PER_PLAYER:
            warnings.append(
                f"{player} has {len(picks)}/{PICKS_PER_PLAYER} picks "
                f"({PICKS_PER_PLAYER - len(picks)} still blank)"
            )
        elif len(picks) > PICKS_PER_PLAYER:
            errors.append(f"{player} has {len(picks)} picks, expected {PICKS_PER_PLAYER}")

    # Same team twice, to one player or across the league
    owner: dict[str, str] = {}
    for player, picks in players.items():
        for team in picks:
            if team in owner:
                if owner[team] == player:
                    errors.append(f"{player} drafted {team} twice")
                else:
                    errors.append(f"{team} drafted by both {owner[team]} and {player}")
            else:
                owner[team] = player

    # Spelling, against the official list
    if valid:
        for line, player, team in rows:
            if team and team not in valid:
                near = difflib.get_close_matches(team, valid, n=3, cutoff=0.6)
                hint = f"  did you mean: {', '.join(near)}?" if near else "  no close match found"
                errors.append(f"line {line}: {player} — \"{team}\" is not an FBS team name.{hint}")
    else:
        warnings.append(
            "could not load an official team list (no network and no cached file), "
            "so spelling was NOT checked"
        )

    # Report
    filled = sum(len(p) for p in players.values())
    total = len(players) * PICKS_PER_PLAYER
    print(f"drafts/{year}.csv — {len(players)} players, {filled}/{total} picks filled")
    if source:
        print(f"team names checked against {source} ({len(valid)} FBS teams)")
    print()

    for w in warnings:
        print(f"  WARN   {w}")
    for e in errors:
        print(f"  ERROR  {e}")

    if not errors and not warnings:
        print("  All good — every pick is a real team, no duplicates, rosters full.")
        print("\nCommit drafts/%s.csv and the site picks it up on deploy." % year)
        return 0
    if not errors:
        print("\nNo errors. The site will load this fine; blanks just aren't scored yet.")
        return 0

    print(f"\n{len(errors)} error(s) to fix before this goes live.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
