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
