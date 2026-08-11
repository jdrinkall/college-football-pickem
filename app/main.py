from __future__ import annotations
import secrets
import os
from datetime import datetime, time
from typing import Optional

from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import select

from .db import SessionLocal
from .models import TeamRecord
from .schemas import TeamRecordOut  # kept in case you use elsewhere
from .services import refresh_season, compute_points_for, season_records
from .selected_teams import (
    SEASONS,
    LATEST_SEASON,
    picks_for,
    teams_for,
    all_players,
    played_seasons,
)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="CFB Wins & Points For")

# UI + static
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Seasons come from the draft data — adding a season to selected_teams.py is enough.
ALLOWED_SEASONS = SEASONS

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def resolve_season(year: Optional[int]) -> int:
    """Clamp a requested season to one we actually have a draft for."""
    if year and int(year) in ALLOWED_SEASONS:
        return int(year)
    return current_season()

def current_season() -> int:
    env_year = os.getenv("SEASON_YEAR")
    if env_year:
        try:
            y = int(env_year)
            return y if y in ALLOWED_SEASONS else LATEST_SEASON
        except ValueError:
            pass
    y = datetime.today().year
    return y if y in ALLOWED_SEASONS else LATEST_SEASON

async def scheduled_refresh():
    """Daily refresh job. Swallows errors so a bad run doesn't kill the scheduler."""
    season = current_season()
    try:
        count = await refresh_season(season, teams_for(season))
        print(f"Scheduled refresh wrote {count} rows")
    except Exception as e:
        print(f"Scheduled refresh failed: {e}")

@app.on_event("startup")
async def startup_event():
    try:
        await refresh_season(current_season())
    except Exception as e:
        print(f"Startup refresh failed: {e}")

    # AsyncIOScheduler awaits coroutine functions itself — pass the function, not a
    # lambda (a lambda returns an un-awaited coroutine that is silently discarded).
    # Held on app.state so it isn't garbage collected.
    scheduler = AsyncIOScheduler()
    scheduler.add_job(scheduled_refresh, CronTrigger(hour=5, minute=0))
    scheduler.start()
    app.state.scheduler = scheduler

@app.get("/healthz")
async def healthz():
    return {"ok": True, "time": datetime.utcnow().isoformat()}

@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    year: Optional[int] = None,
    conference: Optional[str] = None,
    db: Session = Depends(get_db),
):
    season = resolve_season(year)
    season_teams = teams_for(season)
    season_picks = picks_for(season)

    # Query only the teams drafted in this season
    q = select(TeamRecord).where(
        TeamRecord.season == season,
        TeamRecord.team.in_(season_teams),
    )
    if conference:
        q = q.where(TeamRecord.conference == conference)
    q = q.order_by(TeamRecord.wins.desc(), TeamRecord.losses, TeamRecord.team)
    rows = db.execute(q).scalars().all()

    # Points come from the DB, refreshed from CFBD only when missing or stale.
    # Ask for every drafted team, not just the rows the conference filter left.
    pf_map = await compute_points_for(season, season_teams)

    for r in rows:
        setattr(r, "points_for", pf_map.get(r.team, 0))

    # Totals by person, always against this season's picks
    all_rows = db.execute(
        select(TeamRecord).where(
            TeamRecord.season == season,
            TeamRecord.team.in_(season_teams),
        )
    ).scalars().all()
    team_wins = {r.team: r.wins for r in all_rows}
    individual_wins = {
        name: sum(team_wins.get(team, 0) for team in team_list)
        for name, team_list in season_picks.items()
    }
    individual_points = {
        name: sum(pf_map.get(team, 0) for team in team_list)
        for name, team_list in season_picks.items()
    }

    # Conference list for the filter dropdown
    confs = sorted({r.conference for r in all_rows if r.conference})

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "season": season,
            "seasons": ALLOWED_SEASONS,
            "records": rows,
            "conferences": confs,
            "selected_conference": conference or "",
            "individuals": season_picks,
            "individual_wins": individual_wins,
            "individual_points": individual_points,
            "team_points": pf_map,
            "drafted": bool(season_teams),
        },
    )

@app.post("/admin/refresh")
async def admin_refresh(year: Optional[int] = None):
    season = resolve_season(year)
    try:
        # Explicit refresh also re-pulls points, so the button updates both columns
        count = await refresh_season(season, teams_for(season))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"updated": count, "season": season}


REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")

@app.post("/admin/refresh_token")
async def admin_refresh_token(token: str, year: int | None = None):
    if not REFRESH_TOKEN or not secrets.compare_digest(token, REFRESH_TOKEN):
        raise HTTPException(status_code=403, detail="forbidden")
    season = resolve_season(year)
    count = await refresh_season(season, teams_for(season))
    return {"updated": count, "season": season}

async def season_standings(db: Session, season: int) -> list[dict]:
    """Per-player totals for one season, best first."""
    season_teams = teams_for(season)
    team_agg = season_records(db, season, season_teams)
    pf_map = await compute_points_for(season, season_teams)

    table = []
    for name, team_list in picks_for(season).items():
        table.append({
            "name": name,
            "wins": sum(team_agg.get(t, {}).get("wins", 0) for t in team_list),
            "losses": sum(team_agg.get(t, {}).get("losses", 0) for t in team_list),
            "games": sum(team_agg.get(t, {}).get("games", 0) for t in team_list),
            "points_for": sum(pf_map.get(t, 0) for t in team_list),
        })
    table.sort(key=lambda x: (-x["wins"], -x["points_for"], x["name"]))
    return table

@app.get("/standings", response_class=HTMLResponse)
async def standings(request: Request, year: Optional[int] = None, db: Session = Depends(get_db)):
    season = resolve_season(year)
    table = await season_standings(db, season)
    return templates.TemplateResponse(
        "standings.html",
        {
            "request": request,
            "season": season,
            "seasons": ALLOWED_SEASONS,
            "standings": table,
            "drafted": bool(teams_for(season)),
        },
    )

@app.get("/history", response_class=HTMLResponse)
async def history(request: Request, db: Session = Depends(get_db)):
    """Career totals across every season, plus each season's finish per player."""
    # season -> {player: row}, and the finishing position within that season
    by_season: dict[int, dict[str, dict]] = {}
    for season in ALLOWED_SEASONS:
        if not teams_for(season):
            continue  # season not drafted yet — nothing to score
        table = await season_standings(db, season)
        by_season[season] = {
            row["name"]: {**row, "place": place}
            for place, row in enumerate(table, start=1)
        }

    careers = []
    for player in all_players():
        seasons_played = [s for s in played_seasons(player) if s in by_season]
        rows = [by_season[s][player] for s in seasons_played if player in by_season[s]]
        wins = sum(r["wins"] for r in rows)
        losses = sum(r["losses"] for r in rows)
        games = sum(r["games"] for r in rows)
        careers.append({
            "name": player,
            "seasons": len(rows),
            "wins": wins,
            "losses": losses,
            "games": games,
            "points_for": sum(r["points_for"] for r in rows),
            "titles": sum(1 for r in rows if r["place"] == 1),
            # Win rate keeps players comparable when they haven't played the same seasons
            "win_pct": (wins / games) if games else 0.0,
            "by_season": {s: by_season[s][player] for s in seasons_played if player in by_season[s]},
        })
    careers.sort(key=lambda x: (-x["win_pct"], -x["wins"], x["name"]))

    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "seasons": sorted(by_season),
            "careers": careers,
            "pending": [s for s in ALLOWED_SEASONS if not teams_for(s)],
        },
    )
