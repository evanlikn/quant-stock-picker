from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from quant_picker.config import database_schema, database_url, uses_postgresql

_PG_SCHEMA = database_schema() if uses_postgresql() else None


class Base(DeclarativeBase):
    metadata = MetaData(schema=_PG_SCHEMA)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    interval: Mapped[str] = mapped_column(String(8), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    wfo_status: Mapped[str] = mapped_column(String(16), default="pending")
    last_optimized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_optimized_bar_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bars_since_optimization: Mapped[int] = mapped_column(Integer, default=0)
    retrain_cycle_bars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retrain_cycle_source: Mapped[str] = mapped_column(String(16), default="default")
    last_bar_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    history_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Stock-level manual position (shared by all strategies when enabled).
    position_manual_override: Mapped[bool] = mapped_column(Boolean, default=False)
    position_entry_price: Mapped[float] = mapped_column(Float, default=0.0)
    position_entry_shares: Mapped[int] = mapped_column(Integer, default=0)
    position_entry_atr: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_entry_bar_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    position_trailing_stop: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (UniqueConstraint("symbol", "market", "interval", name="uq_watch"),)


class Bar(Base):
    __tablename__ = "bars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    interval: Mapped[str] = mapped_column(String(8), nullable=False)
    bar_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("symbol", "market", "interval", "bar_time", name="uq_bar"),
        Index("ix_bars_lookup", "symbol", "market", "interval", "bar_time"),
    )


class AdaptiveStrategyParams(Base):
    __tablename__ = "adaptive_strategy_params"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    interval: Mapped[str] = mapped_column(String(8), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(32), nullable=False)
    params_json: Mapped[str] = mapped_column(Text, nullable=False)
    oos_metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    fold_count: Mapped[int] = mapped_column(Integer, default=0)
    optimized_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    param_version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        UniqueConstraint(
            "symbol", "market", "interval", "strategy_name", name="uq_adaptive"
        ),
    )


class BacktestResult(Base):
    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32))
    market: Mapped[str] = mapped_column(String(8))
    interval: Mapped[str] = mapped_column(String(8))
    strategy_name: Mapped[str] = mapped_column(String(32))
    report_json: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(32))
    bar_time: Mapped[datetime] = mapped_column(DateTime)
    action: Mapped[str] = mapped_column(String(8))
    strength: Mapped[float] = mapped_column(Float)
    amount: Mapped[float] = mapped_column(Float)
    shares: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    params_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    oos_metrics_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("watchlist_id", "strategy_name", "bar_time", name="uq_rec"),
    )


class StrategyPosition(Base):
    """Per-strategy live position for ATR stop (user may override entry price/shares)."""

    __tablename__ = "strategy_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(32), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, default=0.0)
    entry_shares: Mapped[int] = mapped_column(Integer, default=0)
    entry_atr: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_bar_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trailing_stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("watchlist_id", "strategy_name", name="uq_strategy_pos"),
    )


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int] = mapped_column(Integer)
    strategy_name: Mapped[str] = mapped_column(String(32))
    bar_time: Mapped[datetime] = mapped_column(DateTime)
    channel: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ScreenerRun(Base):
    __tablename__ = "screener_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    universe_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running")
    universe_size: Mapped[int] = mapped_column(Integer, default=0)
    screened_count: Mapped[int] = mapped_column(Integer, default=0)
    top_n: Mapped[int] = mapped_column(Integer, default=100)
    factor_config_json: Mapped[str] = mapped_column(Text, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ScreenerResult(Base):
    __tablename__ = "screener_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    tf_symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    composite_score: Mapped[float] = mapped_column(Float, default=0.0)
    factor_scores_json: Mapped[str] = mapped_column(Text, default="{}")

    __table_args__ = (
        UniqueConstraint("run_id", "rank", name="uq_screener_rank"),
        Index("ix_screener_run", "run_id"),
    )


_engine = None
_Session = None


def get_engine():
    global _engine
    if _engine is None:
        url = database_url()
        kwargs: dict = {"echo": False}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        elif url.startswith("postgresql"):
            kwargs["pool_pre_ping"] = True
            schema = database_schema()
            kwargs["connect_args"] = {"options": f"-csearch_path={schema}"}
        _engine = create_engine(url, **kwargs)
    return _engine


def get_session_factory():
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine())
    return _Session


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    _migrate_schema(engine)


def _migrate_schema(engine) -> None:
    """Lightweight column migrations for existing databases."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if not insp.has_table("watchlist_items"):
        return
    cols = {c["name"] for c in insp.get_columns("watchlist_items")}
    table = "watchlist_items"
    if uses_postgresql():
        table = f"{database_schema()}.{table}"

    additions: list[tuple[str, str]] = []
    if "display_name" not in cols:
        additions.append(("display_name", "VARCHAR(128)"))
    if "position_manual_override" not in cols:
        bool_default = "FALSE" if uses_postgresql() else "0"
        ts_type = "TIMESTAMP" if uses_postgresql() else "DATETIME"
        additions.append(("position_manual_override", f"BOOLEAN DEFAULT {bool_default}"))
        additions.append(("position_entry_price", "FLOAT DEFAULT 0"))
        additions.append(("position_entry_shares", "INTEGER DEFAULT 0"))
        additions.append(("position_entry_atr", "FLOAT"))
        additions.append(("position_entry_bar_time", ts_type))
    if "position_trailing_stop" not in cols:
        additions.append(("position_trailing_stop", "FLOAT"))
    if "history_days" not in cols:
        additions.append(("history_days", "INTEGER"))

    for col, ddl in additions:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))

    if insp.has_table("strategy_positions"):
        pos_table = "strategy_positions"
        if uses_postgresql():
            pos_table = f"{database_schema()}.{pos_table}"
        pos_cols = {c["name"] for c in insp.get_columns("strategy_positions")}
        if "trailing_stop" not in pos_cols:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {pos_table} ADD COLUMN trailing_stop FLOAT"))
