from __future__ import annotations
import os
from typing import List, Dict, Any, Optional
import httpx

CFBD_BASE = "https://api.collegefootballdata.com"

class CFBDApiError(Exception):
    pass

def _headers() -> dict:
    token = os.getenv("CFBD_API_KEY")
    if not token:
        raise CFBDApiError("CFBD_API_KEY not set. Create a free key at collegefootballdata.com and put it in .env")
    return {"Authorization": f"Bearer {token}"}

async def fetch_team_records(year: int) -> List[Dict[str, Any]]:
    """Return team records for the given season year from CFBD.
    Endpoint: GET /records?year=YYYY
    """
    url = f"{CFBD_BASE}/records"
    params = {"year": year}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, params=params, headers=_headers())
        if r.status_code != 200:
            raise CFBDApiError(f"CFBD /records error {r.status_code}: {r.text[:200]}")
        data = r.json()
        if not isinstance(data, list):
            raise CFBDApiError("Unexpected response from CFBD /records (expected list)")
        return data

async def fetch_team_games(year: int, team: str) -> List[Dict[str, Any]]:
    """Return all games for a given team and year (regular + postseason).
    Endpoint: GET /games?year=YYYY&team=Team
    """
    url = f"{CFBD_BASE}/games"
    params = {"year": year, "team": team}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, params=params, headers=_headers())
        if r.status_code != 200:
            raise CFBDApiError(f"CFBD /games error {r.status_code}: {r.text[:200]}")
        data = r.json()
        if not isinstance(data, list):
            raise CFBDApiError("Unexpected response from CFBD /games (expected list)")
        return data
