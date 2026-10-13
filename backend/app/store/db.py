"""
APEX-IN Database Manager & Session Factory
Handles database connection pooling, table initialization, and transaction management.
Supports Railway Postgres and fallback SQLite for local testing.
"""

import os
from contextlib import contextmanager
from typing import Generator, Optional, List
from datetime import datetime, timezone
from sqlalchemy import create_engine, select, and_
from sqlalchemy.orm import sessionmaker, Session
from backend.app.store.models import Base, TradeRecord, TradeEventRecord, SystemStateRecord

def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "sqlite:///./apex_in.db")
    # Railway compatibility: replace postgres:// with postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url

class DatabaseManager:
    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or get_database_url()
        connect_args = {}
        if self.db_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False

        self.engine = create_engine(
            self.db_url,
            connect_args=connect_args,
            pool_pre_ping=True,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=self.engine)

    def init_tables(self) -> None:
        Base.metadata.create_all(bind=self.engine)

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        sess = self.SessionLocal()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    # Repository Helpers
    def save_trade(self, trade: TradeRecord) -> None:
        with self.session() as s:
            s.merge(trade)

    def get_trade(self, trade_id: str) -> Optional[TradeRecord]:
        with self.session() as s:
            return s.query(TradeRecord).filter(TradeRecord.trade_id == trade_id).first()

    def list_trades(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        underlying: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> List[TradeRecord]:
        with self.session() as s:
            q = s.query(TradeRecord)
            if underlying:
                q = q.filter(TradeRecord.underlying == underlying.upper())
            if strategy:
                q = q.filter(TradeRecord.strategy_id == strategy)
            if from_date:
                q = q.filter(TradeRecord.decision_time_ist >= from_date)
            if to_date:
                q = q.filter(TradeRecord.decision_time_ist <= to_date + "T23:59:59")
            return q.order_by(TradeRecord.decision_time_ist.desc()).all()

    def log_trade_event(
        self,
        trade_id: str,
        event_type: str,
        timestamp_ist: str,
        order_id: Optional[int] = None,
        message: Optional[str] = None,
        raw_payload: Optional[dict] = None,
    ) -> TradeEventRecord:
        record = TradeEventRecord(
            trade_id=trade_id,
            order_id=order_id,
            event_type=event_type,
            timestamp_ist=timestamp_ist,
            message=message,
            raw=raw_payload,
        )
        with self.session() as s:
            s.add(record)
        return record

    def get_state(self, key: str, default=None):
        with self.session() as s:
            row = s.query(SystemStateRecord).filter(SystemStateRecord.key == key).first()
            return row.value if row else default

    def set_state(self, key: str, value: dict) -> None:
        with self.session() as s:
            row = s.query(SystemStateRecord).filter(SystemStateRecord.key == key).first()
            if row:
                row.value = value
                row.updated_at_utc = datetime.now(timezone.utc)
            else:
                row = SystemStateRecord(key=key, value=value)
                s.add(row)
