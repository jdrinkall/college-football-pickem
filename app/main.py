from __future__ import annotations
import os
from datetime import datetime, time
from typing import List, Optional

from fastapi import FastAPI, Depends, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import select
from .selected_teams import SELECTED_TEAMS, ALL_SELECTED_TEAMS

from .db import SessionLocal
from .models import TeamRecord, Base
from .schemas import TeamRecordOut
from .services import refresh_season

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="CFB Wins & Losses")


# Static & templates
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


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
            return int(env_year)
        except ValueError:
            pass
    # Basic heuristic: season year is current year for Aug-Jan bowls logic; keep simple
    today = datetime.today()
    return today.year


@app.on_event("startup")
async def startup_event():
    # On startup, try an initial refresh
    try:
        season = current_season()
        await refresh_season(season)
    except Exception as e:
        # Log to console only; UI exposes manual refresh
        print(f"Startup refresh failed: {e}")
    # Scheduler for daily refresh at 5:00 AM local time
    scheduler = AsyncIOScheduler()
    scheduler.add_job(lambda: refresh_season(current_season()), CronTrigger(hour=5, minute=0))
    scheduler.start()


@app.get("/healthz")
async def healthz():
    return {"ok": True, "time": datetime.utcnow().isoformat()}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, year: Optional[int] = None, conference: Optional[str] = None, db: Session = Depends(get_db)):
    season = year or current_season()
    q = select(TeamRecord).where(
        TeamRecord.season == season,
        TeamRecord.team.in_(ALL_SELECTED_TEAMS)
    )
    if conference:
        q = q.where(TeamRecord.conference == conference)
    q = q.order_by(TeamRecord.wins.desc(), TeamRecord.losses, TeamRecord.team)
    rows = db.execute(q).scalars().all()

    # Build a lookup of team -> wins
    team_wins = {r.team: r.wins for r in rows}

    # Aggregate wins for each individual
    individual_wins = {
        name: sum(team_wins.get(team, 0) for team in teams)
        for name, teams in SELECTED_TEAMS.items()
    }

    confs = sorted({r.conference for r in db.execute(
        select(TeamRecord).where(
            TeamRecord.season == season,
            TeamRecord.team.in_(ALL_SELECTED_TEAMS)
        )
    ).scalars().all() if r.conference})

    return templates.TemplateResponse("index.html", {
        "request": request,
        "season": season,
        "records": rows,
        "conferences": confs,
        "selected_conference": conference or "",
        "individuals": SELECTED_TEAMS,
        "individual_wins": individual_wins,
    })

@app.post("/admin/refresh")
async def admin_refresh(year: Optional[int] = None):
    season = year or current_season()
    try:
        count = await refresh_season(season)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"updated": count, "season": season}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, year: Optional[int] = None, conference: Optional[str] = None, db: Session = Depends(get_db)):
    season = year or current_season()
    q = select(TeamRecord).where(TeamRecord.season == season)
    if conference:
        q = q.where(TeamRecord.conference == conference)
    q = q.order_by(TeamRecord.wins.desc(), TeamRecord.losses, TeamRecord.team)
    rows = db.execute(q).scalars().all()

    # For conference filter options
    confs = sorted({r.conference for r in db.execute(select(TeamRecord).where(TeamRecord.season == season)).scalars().all() if r.conference})

    return templates.TemplateResponse("index.html", {
        "request": request,
        "season": season,
        "records": rows,
        "conferences": confs,
        "selected_conference": conference or "",
    })
