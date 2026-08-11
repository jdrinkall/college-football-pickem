from __future__ import annotations
import asyncio
import os
import random
from typing import List, Dict, Any, Optional
import httpx

CFBD_BASE = "https://api.collegefootballdata.com"

# A cold page load asks for every selected team at once (~54 requests). CFBD's edge
# answers a burst that size with 503/429 HTML error pages, so cap how many requests
# are in flight and retry the transient failures instead of letting one blip zero
# out the Points For column.
MAX_CONCURRENCY = int(os.getenv("CFBD_MAX_CONCURRENCY", "6"))
MAX_ATTEMPTS = int(os.getenv("CFBD_MAX_ATTEMPTS", "4"))
RETRY_STATUSES = {429, 500, 502, 503, 504}

class CFBDApiError(Exception):
    pass

_semaphore: Optional[asyncio.Semaphore] = None

def _get_semaphore() -> asyncio.Semaphore:
    """Built lazily so it binds to the running event loop, not import time."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    return _semaphore

def _headers() -> dict:
    token = os.getenv("CFBD_API_KEY")
    if not token:
        raise CFBDApiError("CFBD_API_KEY not set. Create a free key at collegefootballdata.com and put it in .env")
    return {"Authorization": f"Bearer {token}"}

def _backoff_seconds(response: Optional[httpx.Response], attempt: int) -> float:
    """Honour Retry-After when CFBD sends it, else exponential backoff with jitter."""
    if response is not None:
        header = response.headers.get("Retry-After")
        if header:
            try:
                return min(float(header), 30.0)
            except ValueError:
                pass
    return min(2 ** attempt, 8) + random.uniform(0, 0.5)

async def _get_list(path: str, params: dict, what: str) -> List[Dict[str, Any]]:
    """GET a CFBD endpoint expecting a JSON list, with concurrency cap and retries.

    Retries 429 and 5xx (transient) but not other 4xx (bad key, bad params), which
    fail immediately. Raises CFBDApiError once attempts are exhausted.
    """
    url = f"{CFBD_BASE}{path}"
    last_error = "no attempts made"

    for attempt in range(MAX_ATTEMPTS):
        response: Optional[httpx.Response] = None
        # Sleep outside the semaphore so a backing-off request doesn't hold a slot.
        async with _get_semaphore():
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.get(url, params=params, headers=_headers())
            except httpx.HTTPError as e:
                last_error = f"{type(e).__name__}: {e}"

        if response is not None:
            if response.status_code == 200:
                data = response.json()
                if not isinstance(data, list):
                    raise CFBDApiError(f"Unexpected response from CFBD {what} (expected list)")
                return data

            last_error = f"{response.status_code}: {response.text[:200]}"
            if response.status_code not in RETRY_STATUSES:
                raise CFBDApiError(f"CFBD {what} error {last_error}")

        if attempt < MAX_ATTEMPTS - 1:
            await asyncio.sleep(_backoff_seconds(response, attempt))

    raise CFBDApiError(
        f"CFBD {what} failed after {MAX_ATTEMPTS} attempts - last error {last_error}"
    )

async def fetch_team_records(year: int) -> List[Dict[str, Any]]:
    """Return team records for the given season year from CFBD.
    Endpoint: GET /records?year=YYYY
    """
    return await _get_list("/records", {"year": year}, "/records")

async def fetch_team_games(year: int, team: str) -> List[Dict[str, Any]]:
    """Return all games for a given team and year (regular + postseason).
    Endpoint: GET /games?year=YYYY&team=Team
    """
    return await _get_list("/games", {"year": year, "team": team}, "/games")

async def fetch_lines(year: int, season_type: str = "regular") -> List[Dict[str, Any]]:
    """Return betting lines for a whole season in one call, scores included.
    Endpoint: GET /lines?year=YYYY&seasonType=regular
    """
    return await _get_list(
        "/lines", {"year": year, "seasonType": season_type}, "/lines"
    )
