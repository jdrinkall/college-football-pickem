from __future__ import annotations
from pydantic import BaseModel
from typing import Optional

class TeamRecordOut(BaseModel):
    season: int
    team: str
    conference: Optional[str] = None
    division: Optional[str] = None
    wins: int
    losses: int
    ties: int
    total_games: int
