from __future__ import annotations
import asyncio
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from sqlalchemy import select, delete, or_
from sqlalchemy.orm import Session
from .models import Base, TeamRecord, TeamPoints, GameLine
from .db import engine, SessionLocal
from .cfbd_client import fetch_team_records, fetch_team_games, fetch_lines, CFBDQuotaError

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

async def refresh_season(
    season: int, teams: Optional[List[str]] = None, *, points_from_cfbd: bool = False
) -> int:
    """Fetch records from CFBD and write to DB. Returns count.

    When `teams` is given, that season's lines and points are refreshed too.
    Callers that need a fast return (app startup) omit it.

    Costs two CFBD calls: /records and /lines. Points are derived from the lines
    rows rather than fetched per team. Pass points_from_cfbd=True to spend one
    call per team instead and pick up postseason scoring — worth doing once after
    a season's bowls, not on a schedule.
    """
    data = await fetch_team_records(season)
    with SessionLocal() as s:
        written = upsert_records(s, season, data)
    if teams:
        # Lines first: points are summed from the rows this writes.
        await refresh_lines(season)
        if points_from_cfbd:
            await refresh_points_from_cfbd(season, teams)
        else:
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

def points_from_games(
    session: Session, season: int, teams: List[str]
) -> Dict[str, int]:
    """Points scored by each team, summed from the stored game rows.

    The same arithmetic _sum_points does against CFBD /games, run instead over
    the rows refresh_lines already pulled in a single request. Only teams that
    actually appear in a stored game are returned, so the caller can tell "no
    local data for this team" apart from "played but scored nothing".

    Regular season only, because that is what the lines feed covers.
    """
    if not teams:
        return {}

    rows = session.execute(
        select(GameLine).where(
            GameLine.season == season,
            or_(GameLine.home_team.in_(teams), GameLine.away_team.in_(teams)),
        )
    ).scalars().all()

    wanted = set(teams)
    totals: Dict[str, int] = {}
    for row in rows:
        for team, points in ((row.home_team, row.home_points), (row.away_team, row.away_points)):
            if team not in wanted:
                continue
            # Seeing the fixture is enough to count as local data; an unplayed
            # game contributes nothing but still means the team is covered.
            totals.setdefault(team, 0)
            if points is not None:
                totals[team] += points
    return totals


async def compute_points_for(
    season: int, teams: List[str], *, refresh: bool = False
) -> Dict[str, int]:
    """Points scored by each team in a season. Makes no external calls.

    The scores are already in game_lines, so this is one query plus arithmetic
    rather than a /games call per team — which used to mean 54 calls every time
    the TTL lapsed, and 54 calls per page load whenever those calls were failing.

    A finished season keeps whatever is stored for it. Those values came from a
    feed that included conference championships and bowls, which the lines feed
    does not, and recomputing them locally would silently drop real points from
    the standings. Only the live season is derived here, where the difference is
    nil until January. Use refresh_points_from_cfbd() once a season ends to fold
    the postseason back in.
    """
    if not teams:
        return {}

    final = season_is_final(season)

    with SessionLocal() as s:
        stored = {
            r.team: r.points_for
            for r in s.execute(
                select(TeamPoints).where(
                    TeamPoints.season == season,
                    TeamPoints.team.in_(teams),
                )
            ).scalars().all()
        }
        local = points_from_games(s, season, teams)

    result: Dict[str, int] = {}
    changed: Dict[str, int] = {}
    for team in teams:
        if final and not refresh and team in stored:
            result[team] = stored[team]          # postseason-inclusive, leave it alone
        elif team in local:
            result[team] = local[team]
            if stored.get(team) != local[team]:
                changed[team] = local[team]
        else:
            result[team] = stored.get(team, 0)   # no games stored yet

    # Keep the table current so the numbers survive a lines table that gets cleared.
    if changed:
        _store_points(season, changed)

    return result


async def refresh_points_from_cfbd(season: int, teams: List[str]) -> Dict[str, int]:
    """Recompute points from CFBD /games — one call per team, postseason included.

    The expensive path, kept for the once-a-year job of finalising a season after
    the bowls. Nothing calls this on a page render or on the daily refresh.
    """
    if not teams:
        return {}

    async def team_pf(team: str) -> int:
        return _sum_points(await fetch_team_games(season, team), team)

    results = await asyncio.gather(*(team_pf(t) for t in teams), return_exceptions=True)

    fetched: Dict[str, int] = {}
    for team, result in zip(teams, results):
        if isinstance(result, BaseException):
            print(f"Points-for fetch failed for {team} ({season}): {result}")
        else:
            fetched[team] = result
    if fetched:
        _store_points(season, fetched)
    return fetched


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

# A failed lines refresh is remembered so the next render does not try again
# immediately. Without this, an outage or a spent quota means every page load
# re-attempts the fetch — with retries and backoff — and nothing ever caches.
_lines_retry_after: Dict[int, datetime] = {}

# How long to wait before trying again after a failed refresh. A spent monthly
# quota is measured in days, so retrying it every quarter hour just fills the
# log; anything else is usually a blip worth retrying sooner.
_RETRY_AFTER_ERROR = _PF_TTL_SECONDS
_RETRY_AFTER_QUOTA = int(os.getenv("CFBD_QUOTA_BACKOFF", str(6 * 60 * 60)))


async def ensure_lines(season: int) -> None:
    """Fetch lines if we have none, or if a live season's copy has gone stale.

    Never raises: the parlay page is drawn from whatever rows are already stored,
    so CFBD being unreachable makes the numbers stale, not the page broken.
    """
    with SessionLocal() as s:
        newest = s.execute(
            select(GameLine.last_updated)
            .where(GameLine.season == season)
            .order_by(GameLine.last_updated.desc())
            .limit(1)
        ).scalar_one_or_none()

    if newest is not None:
        if season_is_final(season):
            return
        if newest >= datetime.utcnow() - timedelta(seconds=_PF_TTL_SECONDS):
            return

    retry_at = _lines_retry_after.get(season)
    if retry_at is not None and datetime.utcnow() < retry_at:
        return

    try:
        await refresh_lines(season)
        _lines_retry_after.pop(season, None)
    except Exception as e:
        quota = isinstance(e, CFBDQuotaError)
        wait = _RETRY_AFTER_QUOTA if quota else _RETRY_AFTER_ERROR
        _lines_retry_after[season] = datetime.utcnow() + timedelta(seconds=wait)
        print(
            f"Lines refresh failed for {season}, using stored rows "
            f"(next attempt in {wait // 60}m): {e}"
        )

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
