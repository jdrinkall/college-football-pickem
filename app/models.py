from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class TeamRecord(Base):
    __tablename__ = "team_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    season = Column(Integer, index=True, nullable=False)
    team = Column(String, index=True, nullable=False)          # school name
    conference = Column(String, index=True, nullable=True)
    division = Column(String, nullable=True)
    wins = Column(Integer, nullable=False, default=0)
    losses = Column(Integer, nullable=False, default=0)
    ties = Column(Integer, nullable=False, default=0)
    total_games = Column(Integer, nullable=False, default=0)
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("season", "team", name="uix_season_team"),)

class TeamPoints(Base):
    """Points scored by a team in a season.

    Kept in its own table rather than as a column on TeamRecord because the two come
    from different CFBD endpoints and refresh independently — a failed /games call
    must not cost us the W-L row, and create_all() adds a new table on an existing
    SQLite file whereas it would not add a new column.
    """
    __tablename__ = "team_points"
    id = Column(Integer, primary_key=True, autoincrement=True)
    season = Column(Integer, index=True, nullable=False)
    team = Column(String, index=True, nullable=False)
    points_for = Column(Integer, nullable=False, default=0)
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("season", "team", name="uix_points_season_team"),)

class GameLine(Base):
    """One game's final score plus the moneyline we priced the parlay at.

    Only the chosen book's price is stored — which book that was is kept in
    `provider` so a payout can always be traced back to a real quote. Moneylines
    are nullable: about 9% of games (mostly early-season FCS matchups) are never
    priced, and those legs are dropped from the parlay rather than guessed at.
    """
    __tablename__ = "game_lines"
    id = Column(Integer, primary_key=True, autoincrement=True)
    season = Column(Integer, index=True, nullable=False)
    week = Column(Integer, index=True, nullable=False)
    game_id = Column(Integer, index=True, nullable=False)
    home_team = Column(String, index=True, nullable=False)
    away_team = Column(String, index=True, nullable=False)
    home_points = Column(Integer, nullable=True)
    away_points = Column(Integer, nullable=True)
    home_moneyline = Column(Integer, nullable=True)
    away_moneyline = Column(Integer, nullable=True)
    provider = Column(String, nullable=True)
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("season", "game_id", name="uix_line_season_game"),)
