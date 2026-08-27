from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

try:
    import fcntl  # POSIX only; used to serialise first-time schema setup
except ImportError:  # pragma: no cover - Windows
    fcntl = None

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

from quant_picker.config import (
    database_schema,
    database_url,
    pg_idle_transaction_timeout,
    project_root,
    sqlite_busy_timeout,
    uses_postgresql,
)

logger = logging.getLogger(__name__)

_PG_SCHEMA = database_schema() if uses_postgresql() else None


class Base(DeclarativeBase):
    metadata = MetaData(schema=_PG_SCHEMA)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("username", name="uq_user_username"),)


class UserNotificationSetting(Base):
    """Per-user push channels and credentials (secrets stored encrypted)."""

    __tablename__ = "user_notification_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    wechat_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    trigger: Mapped[str] = mapped_column(String(16), default="daily_summary")
    intraday_trigger: Mapped[str] = mapped_column(String(16), default="signal_change")
    smtp_host: Mapped[str | None] = mapped_column(String(128), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_user: Mapped[str | None] = mapped_column(String(128), nullable=True)
    smtp_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_to: Mapped[str | None] = mapped_column(String(128), nullable=True)
    wpush_apikey_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    wpush_channel: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Which QUANT_PICKER_SECRET_KEY encrypted the columns above, so a replaced
    # key is reported at startup instead of surfacing as a failed push.
    key_fingerprint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", name="uq_user_notify"),)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
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

    __table_args__ = (
        UniqueConstraint("user_id", "symbol", "market", "interval", name="uq_watch_user"),
        Index("ix_watchlist_user", "user_id"),
    )


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


def _tune_sqlite(engine) -> None:
    """Make a file-backed SQLite usable from the web and scheduler at once.

    Both processes write (scheduler stores bars and recommendations, the web
    stores watchlists and settings). The default rollback journal makes a writer
    block readers, so a page refresh during a sync would fail with
    "database is locked". WAL lets readers run during a write, and the busy
    timeout absorbs the remaining writer-vs-writer overlap.
    """
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


def get_engine():
    global _engine
    if _engine is None:
        url = database_url()
        kwargs: dict = {"echo": False}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {
                "check_same_thread": False,
                "timeout": sqlite_busy_timeout(),
            }
        elif url.startswith("postgresql"):
            kwargs["pool_pre_ping"] = True
            schema = database_schema()
            # Last line of defence for a transaction nothing ever closes: such a
            # connection holds table locks indefinitely and blocks migrations.
            # The server drops it instead of letting it sit there for hours.
            idle_ms = int(pg_idle_transaction_timeout() * 1000)
            options = f"-csearch_path={schema}"
            if idle_ms > 0:
                options += f" -cidle_in_transaction_session_timeout={idle_ms}"
            kwargs["connect_args"] = {"options": options}
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite") and ":memory:" not in url and url != "sqlite://":
            _tune_sqlite(_engine)
    return _engine


def get_session_factory():
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine())
    return _Session


# Arbitrary constant; only has to be stable across processes of this app.
_SCHEMA_LOCK_KEY = 0x9114_C4E2


@contextmanager
def _schema_lock(engine):
    """Serialise first-time setup across processes.

    systemd starts the web and scheduler units together, so on a fresh database
    both reach CREATE TABLE at the same moment. SQLite then fails the loser with
    "database is locked" and PostgreSQL with a duplicate table error, leaving one
    of the two services dead. The same window would also let both processes
    generate a secret key and write a different one each.
    """
    from sqlalchemy import text

    if uses_postgresql():
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _SCHEMA_LOCK_KEY})
            conn.commit()
            try:
                yield
            finally:
                conn.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": _SCHEMA_LOCK_KEY}
                )
                conn.commit()
        return

    lock_path = _sqlite_lock_path(engine)
    if lock_path is None or fcntl is None:  # in-memory database, or non-POSIX
        yield
        return
    with open(lock_path, "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _sqlite_lock_path(engine) -> Path | None:
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    return Path(f"{database}.initlock")


def init_db() -> None:
    from quant_picker.security.crypto import ensure_secret_key

    engine = get_engine()
    with _schema_lock(engine):
        Base.metadata.create_all(engine)
        ensure_secret_key()
        _migrate_schema(engine)


def _qualified(table: str) -> str:
    if uses_postgresql():
        return f"{database_schema()}.{table}"
    return table


def _bootstrap_admin_id(engine) -> int:
    """Return the account that inherits pre-multi-user data, creating it if needed."""
    from sqlalchemy import text

    from quant_picker.auth.passwords import hash_password
    from quant_picker.security.crypto import random_password

    users = _qualified("users")
    with engine.begin() as conn:
        row = conn.execute(text(f"SELECT id FROM {users} ORDER BY id LIMIT 1")).first()
        if row:
            return int(row[0])

        username = os.getenv("QUANT_PICKER_ADMIN_USERNAME", "").strip() or "admin"
        password = os.getenv("QUANT_PICKER_ADMIN_PASSWORD", "").strip()
        generated = not password
        if generated:
            password = random_password()
        conn.execute(
            text(
                f"INSERT INTO {users} "
                "(username, display_name, password_hash, is_admin, is_active, created_at) "
                "VALUES (:u, :d, :h, :admin, :active, :created)"
            ),
            {
                "u": username,
                "d": "管理员",
                "h": hash_password(password),
                "admin": True,
                "active": True,
                "created": datetime.utcnow(),
            },
        )
        new_id = conn.execute(
            text(f"SELECT id FROM {users} WHERE username = :u"), {"u": username}
        ).scalar_one()

    if generated:
        _persist_bootstrap_password(username, password)
    logger.warning("已创建初始管理员账号 %s", username)
    return int(new_id)


def _persist_bootstrap_password(username: str, password: str) -> None:
    path = project_root() / "data" / "bootstrap_admin_password.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"用户名: {username}\n密码: {password}\n（首次登录后请修改密码并删除本文件）\n",
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    logger.warning("初始管理员密码已写入 %s，请登录后修改并删除该文件", path)


def _migrate_watchlist_owner(engine, insp) -> None:
    """Add watchlist_items.user_id and move existing rows to the bootstrap admin."""
    from sqlalchemy import text

    table = _qualified("watchlist_items")
    cols = {c["name"] for c in insp.get_columns("watchlist_items")}

    # 必须无条件执行：全新库由 create_all 直接建出带 user_id 的表，不会走下面的
    # 迁移分支，若把建号放在分支里，新部署会一个账号都没有，谁也登不进去。
    admin_id = _bootstrap_admin_id(engine)

    if "user_id" not in cols:
        _run_ddl(engine, [f"ALTER TABLE {table} ADD COLUMN user_id INTEGER"])
        # Separate transaction, and idempotent, so a crash between the two
        # leaves rows that the next start still backfills instead of orphaning.
        with engine.begin() as conn:
            result = conn.execute(
                text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"),
                {"uid": admin_id},
            )
        logger.warning("已将 %s 条自选归属到初始管理员", result.rowcount)
        if uses_postgresql():
            _run_ddl(engine, [f"ALTER TABLE {table} ALTER COLUMN user_id SET NOT NULL"])

    if not uses_postgresql():
        # SQLite cannot drop a table-level constraint; a legacy file DB keeps the
        # old (symbol, market, interval) uniqueness and blocks shared symbols.
        names = {c["name"] for c in insp.get_unique_constraints("watchlist_items")}
        if "uq_watch" in names:
            logger.warning(
                "SQLite 无法替换 uq_watch 约束，不同用户将无法收藏同一只股票；"
                "请迁移到 PostgreSQL 或重建数据库文件"
            )
        return

    constraints = {c["name"] for c in insp.get_unique_constraints("watchlist_items")}
    if "uq_watch_user" not in constraints:
        _run_ddl(
            engine,
            [
                f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS uq_watch",
                f"ALTER TABLE {table} ADD CONSTRAINT uq_watch_user "
                "UNIQUE (user_id, symbol, market, interval)",
            ],
        )
        logger.warning("已将自选唯一约束替换为 uq_watch_user")

    _run_ddl(engine, [f"CREATE INDEX IF NOT EXISTS ix_watchlist_user ON {table} (user_id)"])


class MigrationBlocked(RuntimeError):
    """A schema change could not acquire its lock within the timeout."""


def _run_ddl(engine, statements: list[str]) -> None:
    """Apply DDL, failing fast and legibly when another session holds the lock.

    ALTER TABLE needs an exclusive lock, so a single long-lived reader (one
    stale Streamlit session sitting "idle in transaction" is enough) makes it
    wait forever. init_db() runs on every web and scheduler start, so an
    unbounded wait means the app never finishes booting and prints nothing to
    explain why.
    """
    from sqlalchemy import exc, text

    try:
        with engine.begin() as conn:
            if uses_postgresql():
                conn.execute(text("SET LOCAL lock_timeout = '5s'"))
            for sql in statements:
                conn.execute(text(sql))
    except exc.DBAPIError as err:
        if getattr(err.orig, "sqlstate", None) != "55P03":  # lock_not_available
            raise
        raise MigrationBlocked(
            "数据库结构升级被其他连接阻塞（通常是仍在运行的 Web 或 scheduler 进程，"
            "或残留的 idle in transaction 连接）。请先停掉这些进程再启动，"
            "或执行：SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE state = 'idle in transaction';"
        ) from err


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
        _run_ddl(engine, [f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"])

    if insp.has_table("strategy_positions"):
        pos_table = "strategy_positions"
        if uses_postgresql():
            pos_table = f"{database_schema()}.{pos_table}"
        pos_cols = {c["name"] for c in insp.get_columns("strategy_positions")}
        if "trailing_stop" not in pos_cols:
            _run_ddl(engine, [f"ALTER TABLE {pos_table} ADD COLUMN trailing_stop FLOAT"])

    if insp.has_table("user_notification_settings"):
        notify_cols = {c["name"] for c in insp.get_columns("user_notification_settings")}
        if "key_fingerprint" not in notify_cols:
            _run_ddl(
                engine,
                [
                    f"ALTER TABLE {_qualified('user_notification_settings')} "
                    "ADD COLUMN key_fingerprint VARCHAR(32)"
                ],
            )

    _migrate_watchlist_owner(engine, inspect(engine))
