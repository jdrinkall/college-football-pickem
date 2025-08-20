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
from .services import refresh_season, compute_points_for
from .selected_teams import SELECTED_TEAMS, ALL_SELECTED_TEAMS

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="CFB Wins & Points For")

# UI + static
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Only allow these seasons, per your scope
ALLOWED_SEASONS = [2024, 2025]

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def current_season() -> int:
    env_year = os.getenv("SEASON_YEAR")
    if env_year:
        try:
            y = int(env_year)
            return y if y in ALLOWED_SEASONS else max(ALLOWED_SEASONS)
        except ValueError:
            pass
    y = datetime.today().year
    return y if y in ALLOWED_SEASONS else max(ALLOWED_SEASONS)

@app.on_event("startup")
async def startup_event():
    try:
        await refresh_season(current_season())
    except Exception as e:
        print(f"Startup refresh failed: {e}")

    # Note: refresh_season is async; schedule a task to run it
    scheduler = AsyncIOScheduler()
    scheduler.add_job(lambda: refresh_season(current_season()), CronTrigger(hour=5, minute=0))
    scheduler.start()

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
    # Resolve and clamp season
    season = int(year) if year else current_season()
    if season not in ALLOWED_SEASONS:
        season = max(ALLOWED_SEASONS)

    # Query only your selected teams
    q = select(TeamRecord).where(
        TeamRecord.season == season,
        TeamRecord.team.in_(ALL_SELECTED_TEAMS),
    )
    if conference:
        q = q.where(TeamRecord.conference == conference)
    q = q.order_by(TeamRecord.wins.desc(), TeamRecord.losses, TeamRecord.team)
    rows = db.execute(q).scalars().all()

    # ----- Points For: compute at render time -----
    teams = [r.team for r in rows]  # already filtered to selected teams
    pf_map = await compute_points_for(season, teams)
    
    for r in rows:
        setattr(r, "points_for", pf_map.get(r.team, 0))

    # Build totals by person (wins only, per your spec)
    team_wins = {r.team: r.wins for r in rows}
    individual_wins = {
        name: sum(team_wins.get(team, 0) for team in teams)
        for name, teams in SELECTED_TEAMS.items()
    }
    team_points = pf_map  # alias for clarity
    individual_points = {
    name: sum(team_points.get(team, 0) for team in teams_list)
    for name, teams_list in SELECTED_TEAMS.items()
    }
    

    # Conference list for the filter dropdown
    confs = sorted({
        r.conference
        for r in db.execute(
            select(TeamRecord).where(
                TeamRecord.season == season,
                TeamRecord.team.in_(ALL_SELECTED_TEAMS),
            )
        ).scalars().all()
        if r.conference
    })

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "season": season,
            "records": rows,
            "conferences": confs,
            "selected_conference": conference or "",
            "individuals": SELECTED_TEAMS,
            "individual_wins": individual_wins,
            "individual_points": individual_points,
            "team_points": team_points,
        },
    )

@app.post("/admin/refresh")
async def admin_refresh(year: Optional[int] = None):
    season = int(year) if year else current_season()
    if season not in ALLOWED_SEASONS:
        season = max(ALLOWED_SEASONS)
    try:
        count = await refresh_season(season)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"updated": count, "season": season}


REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")

@app.post("/admin/refresh_token")
async def admin_refresh_token(token: str, year: int | None = None):
    if not REFRESH_TOKEN or not secrets.compare_digest(token, REFRESH_TOKEN):
        raise HTTPException(status_code=403, detail="forbidden")
    season = year if year else (int(os.getenv("SEASON_YEAR", "2025")))
    count = await refresh_season(season)
    return {"updated": count, "season": season}

