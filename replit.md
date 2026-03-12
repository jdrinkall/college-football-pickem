# CFB Wins & Losses (FastAPI)

## Overview
A FastAPI web application that tracks win-loss records for FBS college football teams using the CollegeFootballData API (CFBD). Stores results in a database and serves a Tailwind-styled UI.

## Architecture
- **Framework**: FastAPI (Python 3.12)
- **Server**: Uvicorn with reload in development
- **Database**: PostgreSQL (via Replit's built-in DB) using SQLAlchemy ORM
- **Templating**: Jinja2 templates with Tailwind CSS (CDN)
- **Scheduler**: APScheduler (AsyncIOScheduler) — refreshes data daily at 5am
- **External API**: CollegeFootballData API (CFBD)

## Project Structure
```
app/
  main.py           # FastAPI app, routes, scheduler setup
  db.py             # SQLAlchemy engine and session (DATABASE_URL env var)
  models.py         # TeamRecord ORM model
  schemas.py        # Pydantic schemas
  services.py       # Business logic: refresh_season, compute_points_for
  cfbd_client.py    # CFBD API HTTP client
  selected_teams.py # Curated team/person mappings
  templates/        # Jinja2 HTML templates
  static/           # Static assets
```

## Key Environment Variables
- `CFBD_API_KEY` — CollegeFootballData API key (set in .env)
- `SEASON_YEAR` — Season year to display (default: current year, clamped to 2024-2025)
- `DATABASE_URL` — SQLAlchemy DB URL (defaults to `sqlite:///./app.db`, auto-set to PostgreSQL by Replit)

## Running the App
- **Development**: Workflow "Start application" runs `uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload`
- **Production**: `uvicorn app.main:app --host 0.0.0.0 --port 5000`

## Features
- View W-L records for selected FBS teams
- Filter by conference
- Individual standings (win totals aggregated per person's team picks)
- Points For tracking via CFBD API
- Admin refresh endpoint: `POST /admin/refresh?year=YYYY`
- Health check: `GET /healthz`
