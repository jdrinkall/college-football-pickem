from __future__ import annotations
import asyncio
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .models import Base, TeamRecord, TeamPoints
from .db import engine, SessionLocal
from .cfbd_client import fetch_team_records, fetch_team_games

# Create tables on import
Base.metadata.create_all(bind=engine)

def upsert_records(session: Session, season: int, cfbd_records: List[Dict]) -> int:
    """Replace all team_records for a season with the list from CFBD.
    Returns number of rows written.
    CFBD /records returns structure like:
      { 'team': 'Georgia', 'conference': 'SEC', 'division': 'East', 'total': 15, 'wins': 14, 'losses': 1, 'ties': 0, ... }
    The real payload has nested objects; we map defensively.
    """
    # Clear existing season rows
    session.execute(delete(TeamRecord).where(TeamRecord.season == season))
    written = 0
    now = datetime.utcnow()
    for row in cfbd_records:
        team = row.get('team') or row.get('school') or (row.get('team', {}) if isinstance(row.get('team'), str) else None)
        if isinstance(team, dict):
            team = team.get('school') or team.get('name')
        conference = row.get('conference') or (row.get('team', {}).get('conference') if isinstance(row.get('team'), dict) else None)
        division = row.get('division')
        wins = int(row.get('wins') or row.get('total', {}).get('wins', 0))
        losses = int(row.get('losses') or row.get('total', {}).get('losses', 0))
        ties = int(row.get('ties') or row.get('total', {}).get('ties', 0))
        total_games = int(row.get('totalGames') or row.get('games') or (wins + losses + ties))

        if not team:
            continue

        rec = TeamRecord(
            season=season,
            team=team,
            conference=conference,
            division=division,
            wins=wins,
            losses=losses,
            ties=ties,
            total_games=total_games,
            last_updated=now,
        )
        session.add(rec)
        written += 1
    session.commit()
    return written

async def refresh_season(season: int, teams: Optional[List[str]] = None) -> int:
    """Fetch records from CFBD and write to DB. Returns count.

    When `teams` is given, that season's points are refreshed too. Callers that need
    a fast return (app startup) omit it and let points refresh lazily on render.
    """
    data = await fetch_team_records(season)
    with SessionLocal() as s:
        written = upsert_records(s, season, data)
    if teams:
        await compute_points_for(season, teams, refresh=True)
    return written

# How long a *live* season's stored points stay usable before we re-fetch. Finished
# seasons are never re-fetched, so this only applies to the season in progress.
_PF_TTL_SECONDS = int(os.getenv("POINTS_FOR_TTL", "900"))

def season_is_final(season: int, today: Optional[datetime] = None) -> bool:
    """True once a season's results can no longer change.

    A season's games run from August into early January (bowls, then the title game),
    so the 2025 season is only settled from February 2026 onward.
    """
    today = today or datetime.utcnow()
    return (today.year > season and today.month >= 2) or today.year > season + 1

def _sum_points(games: List[Dict], team: str) -> int:
    """Total points scored by `team` across its games."""
    pf = 0
    for g in games:
        # Each game has home/away info; add the points for the side that matches 'team'
        home = g.get("home_team") or g.get("homeTeam")
        away = g.get("away_team") or g.get("awayTeam")
        home_p = g.get("home_points") or g.get("homePoints") or 0
        away_p = g.get("away_points") or g.get("awayPoints") or 0
        if isinstance(home_p, str):
            try: home_p = int(home_p)
            except: home_p = 0
        if isinstance(away_p, str):
            try: away_p = int(away_p)
            except: away_p = 0
        if team == home:
            pf += home_p or 0
        elif team == away:
            pf += away_p or 0
    return int(pf)

def _store_points(season: int, points: Dict[str, int]) -> None:
    """Upsert per-team points for a season."""
    now = datetime.utcnow()
    with SessionLocal() as s:
        existing = {
            r.team: r
            for r in s.execute(
                select(TeamPoints).where(
                    TeamPoints.season == season,
                    TeamPoints.team.in_(list(points)),
                )
            ).scalars().all()
        }
        for team, pf in points.items():
            row = existing.get(team)
            if row is None:
                s.add(TeamPoints(season=season, team=team, points_for=pf, last_updated=now))
            else:
                row.points_for = pf
                row.last_updated = now
        s.commit()

async def compute_points_for(
    season: int, teams: List[str], *, refresh: bool = False
) -> Dict[str, int]:
    """Points scored by each team in a season, served from the DB.

    CFBD is called only for teams with no stored value, or — while a season is still
    in progress — whose stored value has gone stale. A finished season is never
    re-fetched, so history pages cost no API calls and survive a CFBD outage. A team
    whose fetch fails falls back to its stored value rather than failing the request.
    """
    if not teams:
        return {}

    with SessionLocal() as s:
        stored = {
            r.team: (r.points_for, r.last_updated)
            for r in s.execute(
                select(TeamPoints).where(
                    TeamPoints.season == season,
                    TeamPoints.team.in_(teams),
                )
            ).scalars().all()
        }

    final = season_is_final(season)
    cutoff = datetime.utcnow() - timedelta(seconds=_PF_TTL_SECONDS)

    def needs_fetch(team: str) -> bool:
        if refresh or team not in stored:
            return True
        if final:
            return False
        updated = stored[team][1]
        return updated is None or updated < cutoff

    to_fetch = [t for t in teams if needs_fetch(t)]

    fetched: Dict[str, int] = {}
    if to_fetch:
        async def team_pf(team: str) -> int:
            return _sum_points(await fetch_team_games(season, team), team)

        results = await asyncio.gather(
            *(team_pf(t) for t in to_fetch), return_exceptions=True
        )
        for team, result in zip(to_fetch, results):
            if isinstance(result, BaseException):
                print(f"Points-for fetch failed for {team} ({season}): {result}")
            else:
                fetched[team] = result
        if fetched:
            _store_points(season, fetched)

    return {
        team: fetched.get(team, stored.get(team, (0, None))[0])
        for team in teams
    }

def season_records(session: Session, season: int, teams: List[str]) -> Dict[str, Dict]:
    """W-L-T rows for the given teams in a season, keyed by team."""
    if not teams:
        return {}
    rows = session.execute(
        select(TeamRecord).where(
            TeamRecord.season == season,
            TeamRecord.team.in_(teams),
        )
    ).scalars().all()
    return {
        r.team: {
            "wins": r.wins,
            "losses": r.losses,
            "ties": r.ties,
            "games": r.total_games,
        }
        for r in rows
    }
