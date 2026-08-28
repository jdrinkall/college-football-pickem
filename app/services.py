from __future__ import annotations
import asyncio
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from sqlalchemy import select, delete, or_
from sqlalchemy.orm import Session
from .models import Base, TeamRecord, TeamPoints, GameLine
from .db import engine, SessionLocal
from .cfbd_client import fetch_team_records, fetch_team_games, fetch_lines

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
        await refresh_lines(season)  # one call; keeps the parlay page warm
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

# ---------------------------------------------------------------------------
# Parlay: a flat stake each week on every one of a player's teams to win.
# ---------------------------------------------------------------------------

# Books disagree on the same game, so pick one and stay with it all season —
# that's what actually betting a single book would have looked like. Falls
# through in order when a book hasn't priced a game.
MONEYLINE_PROVIDERS = [
    p.strip()
    for p in os.getenv("MONEYLINE_PROVIDERS", "DraftKings,ESPN Bet,Bovada").split(",")
    if p.strip()
]
PARLAY_STAKE = float(os.getenv("PARLAY_STAKE", "10"))

def _pick_moneyline(lines: Optional[List[Dict]]) -> tuple:
    """(home_ml, away_ml, provider) from the first book that priced the game."""
    priced = {}
    for ln in lines or []:
        home = ln.get("homeMoneyline", ln.get("home_moneyline"))
        away = ln.get("awayMoneyline", ln.get("away_moneyline"))
        if home is not None and away is not None:
            priced[ln.get("provider")] = (int(home), int(away))
    for provider in MONEYLINE_PROVIDERS:
        if provider in priced:
            return (*priced[provider], provider)
    for provider, (home, away) in priced.items():  # any book beats no price
        return (home, away, provider)
    return (None, None, None)

async def refresh_lines(season: int) -> int:
    """Pull a season's lines and scores (one CFBD call) and replace the stored rows."""
    data = await fetch_lines(season)
    now = datetime.utcnow()
    written = 0
    with SessionLocal() as s:
        s.execute(delete(GameLine).where(GameLine.season == season))
        for g in data:
            home_ml, away_ml, provider = _pick_moneyline(g.get("lines"))
            s.add(GameLine(
                season=season,
                week=int(g.get("week") or 0),
                game_id=int(g.get("id") or 0),
                home_team=g.get("homeTeam") or g.get("home_team") or "",
                away_team=g.get("awayTeam") or g.get("away_team") or "",
                home_points=g.get("homeScore", g.get("home_score")),
                away_points=g.get("awayScore", g.get("away_score")),
                home_moneyline=home_ml,
                away_moneyline=away_ml,
                provider=provider,
                last_updated=now,
            ))
            written += 1
        s.commit()
    return written

async def ensure_lines(season: int) -> None:
    """Fetch lines if we have none, or if a live season's copy has gone stale."""
    with SessionLocal() as s:
        newest = s.execute(
            select(GameLine.last_updated)
            .where(GameLine.season == season)
            .order_by(GameLine.last_updated.desc())
            .limit(1)
        ).scalar_one_or_none()

    if newest is None:
        await refresh_lines(season)
        return
    if season_is_final(season):
        return
    if newest < datetime.utcnow() - timedelta(seconds=_PF_TTL_SECONDS):
        await refresh_lines(season)

def american_to_decimal(moneyline: int) -> float:
    """American odds to a decimal multiplier that includes the stake.

    -150 means risk 150 to win 100 -> 1.667; +200 means risk 100 to win 200 -> 3.0.
    """
    if moneyline < 0:
        return 1.0 + 100.0 / abs(moneyline)
    return 1.0 + moneyline / 100.0

def parlay_season(
    session: Session, season: int, teams: List[str], stake: float = PARLAY_STAKE
) -> Dict:
    """Settle a flat parlay each week on every one of `teams` to win.

    Only the player's teams that actually played that week are legs — byes are not
    a leg. A leg with no quoted moneyline is dropped and the rest of the week still
    runs. A week with no priced legs is skipped entirely and nothing is staked.
    """
    if not teams:
        return {"weeks": [], "weeks_bet": 0, "weeks_hit": 0,
                "staked": 0.0, "returned": 0.0, "net": 0.0, "best": None}

    wanted = set(teams)
    rows = session.execute(
        select(GameLine).where(GameLine.season == season).order_by(GameLine.week)
    ).scalars().all()

    by_week: Dict[int, List[Dict]] = {}
    for r in rows:
        for team, moneyline, points, opp_points, opponent in (
            (r.home_team, r.home_moneyline, r.home_points, r.away_points, r.away_team),
            (r.away_team, r.away_moneyline, r.away_points, r.home_points, r.home_team),
        ):
            if team not in wanted:
                continue
            settled = points is not None and opp_points is not None
            by_week.setdefault(r.week, []).append({
                "team": team,
                "opponent": opponent,
                "moneyline": moneyline,
                "won": (points > opp_points) if settled else None,
                "priced": moneyline is not None and settled,
            })

    weeks = []
    staked = returned = 0.0
    for week in sorted(by_week):
        legs = by_week[week]
        priced = [l for l in legs if l["priced"]]
        if not priced:
            continue  # nothing quotable this week, so no bet was placed

        multiplier = 1.0
        for leg in priced:
            multiplier *= american_to_decimal(leg["moneyline"])
        hit = all(leg["won"] for leg in priced)
        payout = stake * multiplier if hit else 0.0

        staked += stake
        returned += payout
        weeks.append({
            "week": week,
            "legs": priced,
            "dropped": [l["team"] for l in legs if not l["priced"]],
            "multiplier": multiplier,
            "hit": hit,
            "payout": payout,
        })

    hits = [w for w in weeks if w["hit"]]
    return {
        "weeks": weeks,
        "weeks_bet": len(weeks),
        "weeks_hit": len(hits),
        "staked": staked,
        "returned": returned,
        "net": returned - staked,
        "best": max(hits, key=lambda w: w["payout"]) if hits else None,
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


def team_schedules(
    session: Session, season: int, teams: List[str]
) -> Dict[str, List[Dict]]:
    """Each team's season schedule, earliest week first, keyed by team.

    Built from the stored game rows the parlay already relies on, so a schedule
    costs no CFBD calls. Those rows are regular season only, so bowls and
    playoff games are absent. A game between two drafted teams appears in both
    teams' lists, each from that team's own point of view.
    """
    if not teams:
        return {}

    rows = session.execute(
        select(GameLine)
        .where(
            GameLine.season == season,
            or_(GameLine.home_team.in_(teams), GameLine.away_team.in_(teams)),
        )
        .order_by(GameLine.week, GameLine.game_id)
    ).scalars().all()

    schedules: Dict[str, List[Dict]] = {team: [] for team in teams}
    for row in rows:
        # Read each row from both ends; only the drafted side(s) are kept.
        for team, opponent, points, opp_points, at_home in (
            (row.home_team, row.away_team, row.home_points, row.away_points, True),
            (row.away_team, row.home_team, row.away_points, row.home_points, False),
        ):
            if team not in schedules:
                continue
            # A game with no score yet is on the schedule but not played.
            played = points is not None and opp_points is not None
            result = None
            if played:
                result = "W" if points > opp_points else "L" if points < opp_points else "T"
            schedules[team].append({
                "week": row.week,
                "opponent": opponent,
                "at_home": at_home,
                "points": points,
                "opponent_points": opp_points,
                "played": played,
                "result": result,
            })
    return schedules
