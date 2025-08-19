from __future__ import annotations
from datetime import datetime
from typing import List, Dict
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .models import Base, TeamRecord
from .db import engine, SessionLocal
from .cfbd_client import fetch_team_records

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

async def refresh_season(season: int) -> int:
    """Fetch records from CFBD and write to DB. Returns count."""
    data = await fetch_team_records(season)
    with SessionLocal() as s:
        return upsert_records(s, season, data)

from .cfbd_client import fetch_team_games
import asyncio

async def compute_points_for(season: int, teams: list[str]) -> dict[str, int]:
    """Compute total points scored for each team in a season by summing game points."""
    async def team_pf(team: str) -> tuple[str, int]:
        games = await fetch_team_games(season, team)
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
        return (team, int(pf))
    results = await asyncio.gather(*(team_pf(t) for t in teams))
    return dict(results)
