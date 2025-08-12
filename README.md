# CFB Wins & Losses (FastAPI)

A tiny FastAPI site that tracks W-L records for FBS teams using the CollegeFootballData API (CFBD).  
Stores results in SQLite and serves a simple Tailwind UI.

## Quickstart

```bash
# 1) Extract this project and open in VS Code
cd cfb_wins_app

# 2) Create a virtualenv (recommended)
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3) Install deps
pip install -r requirements.txt

# 4) Configure secrets
cp .env.example .env
# edit .env and set CFBD_API_KEY from https://collegefootballdata.com (free key)

# 5) Run
uvicorn app.main:app --reload

# 6) Open
# http://127.0.0.1:8000
```

### Notes
- Data source: CollegeFootballData API (free key required).
- Scheduler refreshes records every day at 5am local time and also on server start.
- You can force a refresh from the UI or via `POST /admin/refresh?year=YYYY`.
