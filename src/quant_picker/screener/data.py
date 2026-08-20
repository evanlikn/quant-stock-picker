from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import pandas as pd

from quant_picker.config import load_screener_config
from quant_picker.data.providers.tickflow_client import get_tickflow_client
from quant_picker.screener.engine import ProgressCallback
from quant_picker.screener.factors import (
    compute_price_factors,
    extract_fundamental_factors,
    normalize_klines,
)
from quant_picker.screener.universe import UniverseEntry


def _fetch_klines(tf_symbol: str, count: int) -> pd.DataFrame:
    raw = get_tickflow_client().klines.get(
        tf_symbol,
        period="1d",
        count=count,
        adjust="forward_additive",
        as_dataframe=True,
    )
    return normalize_klines(raw)


def fetch_price_factor_frame(
    entries: list[UniverseEntry],
    *,
    progress: ProgressCallback | None = None,
) -> pd.DataFrame:
    cfg = load_screener_config()
    count = int(cfg.get("kline_count") or 120)
    max_workers = max(int(cfg.get("max_workers") or 8), 1)

    rows: list[dict] = []
    total = len(entries)
    done = 0

    def worker(entry: UniverseEntry) -> dict | None:
        try:
            bars = _fetch_klines(entry.tf_symbol, count)
            factors = compute_price_factors(bars)
            if not factors:
                return None
            return {
                "tf_symbol": entry.tf_symbol,
                "symbol": entry.symbol,
                "market": entry.market,
                "display_name": entry.name,
                **factors,
            }
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(worker, entry): entry for entry in entries}
        for fut in as_completed(futures):
            done += 1
            if progress:
                progress(done / max(total, 1), f"拉取日K并计算价量因子 ({done}/{total})")
            row = fut.result()
            if row:
                rows.append(row)

    return pd.DataFrame(rows)


def fetch_fundamental_factor_frame(
    tf_symbols: list[str],
    factor_names: list[str],
    *,
    progress: ProgressCallback | None = None,
) -> tuple[pd.DataFrame, str | None]:
    if not tf_symbols or not factor_names:
        return pd.DataFrame(), None

    field_map = {
        "roe": "roe",
        "revenue_yoy": "revenue_yoy",
        "net_margin": "net_margin",
        "roa": "roa",
        "debt_to_asset": "debt_to_asset_ratio",
    }
    requested_fields = [field_map[name] for name in factor_names if name in field_map]
    if not requested_fields:
        return pd.DataFrame(), None

    try:
        if progress:
            progress(0.0, "拉取基本面因子…")
        raw = get_tickflow_client().financials.metrics(
            symbols=tf_symbols,
            latest=True,
            as_dataframe=True,
            show_progress=False,
        )
    except Exception as exc:
        return pd.DataFrame(), str(exc)

    if raw is None or raw.empty:
        return pd.DataFrame(), "财务数据为空"

    if progress:
        progress(1.0, "基本面因子拉取完成")

    latest = raw.sort_values("report_date").groupby("symbol", as_index=False).tail(1)
    rows: list[dict] = []
    for _, row in latest.iterrows():
        factors = extract_fundamental_factors(row)
        if not factors:
            continue
        rows.append({"tf_symbol": str(row["symbol"]), **factors})

    return pd.DataFrame(rows), None


def merge_factor_frames(price_df: pd.DataFrame, fundamental_df: pd.DataFrame) -> pd.DataFrame:
    if price_df.empty:
        return price_df
    if fundamental_df is None or fundamental_df.empty:
        return price_df
    return price_df.merge(fundamental_df, on="tf_symbol", how="left", suffixes=("", "_fund"))
