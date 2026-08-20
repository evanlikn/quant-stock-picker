from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

from quant_picker.config import load_screener_config


ProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True)
class RankedStock:
    rank: int
    tf_symbol: str
    symbol: str
    market: str
    display_name: str | None
    composite_score: float
    factor_scores: dict[str, float]


def _winsorize(series: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    if series.dropna().empty:
        return series
    lo = series.quantile(lower)
    hi = series.quantile(upper)
    return series.clip(lo, hi)


def score_universe(frame: pd.DataFrame, factor_defs: list[dict[str, Any]]) -> pd.DataFrame:
    if frame.empty:
        return frame

    active = [f for f in factor_defs if f["name"] in frame.columns and frame[f["name"]].notna().any()]
    if not active:
        raise ValueError("没有可用于打分的因子数据")

    weights = np.array([float(f.get("weight") or 0) for f in active], dtype=float)
    if weights.sum() <= 0:
        weights = np.ones(len(active), dtype=float)
    weights = weights / weights.sum()

    z_cols: list[str] = []
    for factor, weight in zip(active, weights):
        name = factor["name"]
        series = pd.to_numeric(frame[name], errors="coerce")
        clipped = _winsorize(series)
        std = clipped.std(skipna=True)
        if std is None or std == 0 or np.isnan(std):
            z = pd.Series(0.0, index=frame.index)
        else:
            z = (clipped - clipped.mean(skipna=True)) / std
        if str(factor.get("direction", "high")).lower() == "low":
            z = -z
        col = f"_z_{name}"
        frame[col] = z
        z_cols.append(col)

    frame["composite_score"] = 0.0
    for col, weight in zip(z_cols, weights):
        frame["composite_score"] += frame[col].fillna(0.0) * weight

    return frame.sort_values("composite_score", ascending=False)


def pick_top_n(frame: pd.DataFrame, top_n: int) -> list[RankedStock]:
    cfg = load_screener_config()
    factor_defs = cfg.get("factors") or []
    factor_names = [str(f["name"]) for f in factor_defs]

    scored = score_universe(frame, factor_defs)
    rows: list[RankedStock] = []
    for i, (_, row) in enumerate(scored.head(top_n).iterrows(), start=1):
        factor_scores = {
            name: float(row[name])
            for name in factor_names
            if name in row.index and pd.notna(row[name])
        }
        rows.append(
            RankedStock(
                rank=i,
                tf_symbol=str(row["tf_symbol"]),
                symbol=str(row["symbol"]),
                market=str(row["market"]),
                display_name=(None if pd.isna(row.get("display_name")) else str(row["display_name"])),
                composite_score=float(row["composite_score"]),
                factor_scores=factor_scores,
            )
        )
    return rows
