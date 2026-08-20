from __future__ import annotations

import json
from dataclasses import dataclass, field

from quant_picker.config import load_screener_config
from quant_picker.screener.data import (
    fetch_fundamental_factor_frame,
    fetch_price_factor_frame,
    merge_factor_frames,
)
from quant_picker.screener.engine import ProgressCallback, RankedStock, pick_top_n
from quant_picker.screener.universe import load_universe_entries
from quant_picker.storage.repository import Repository


@dataclass
class ScreenerRunResult:
    run_id: int
    market: str
    universe_id: str
    universe_size: int
    screened_count: int
    top_n: int
    warnings: list[str] = field(default_factory=list)
    results: list[RankedStock] = field(default_factory=list)


class ScreenerRunner:
    def __init__(self, repo: Repository):
        self.repo = repo

    def run(
        self,
        market: str | None = None,
        *,
        progress: ProgressCallback | None = None,
    ) -> ScreenerRunResult:
        cfg = load_screener_config()
        market_key = (market or cfg.get("default_market") or "cn").lower()
        top_n = int(cfg.get("top_n") or 100)
        factor_defs = cfg.get("factors") or []

        if progress:
            progress(0.02, "加载股票池…")
        universe_id, entries = load_universe_entries(market_key)

        run = self.repo.create_screener_run(
            market=market_key,
            universe_id=universe_id,
            top_n=top_n,
            factor_config_json=json.dumps(factor_defs, ensure_ascii=False),
            universe_size=len(entries),
        )

        warnings: list[str] = []
        try:
            price_df = fetch_price_factor_frame(entries, progress=progress)
            if price_df.empty:
                raise ValueError("未能获取任何股票的价量因子数据")

            fundamental_names = [
                str(f["name"])
                for f in factor_defs
                if str(f.get("source", "price")).lower() == "fundamental"
            ]
            fundamental_df, fund_err = fetch_fundamental_factor_frame(
                price_df["tf_symbol"].tolist(),
                fundamental_names,
                progress=progress,
            )
            if fund_err:
                warnings.append(
                    f"基本面因子未纳入评分：{fund_err}（已仅使用价量因子继续）"
                )

            merged = merge_factor_frames(price_df, fundamental_df)
            if progress:
                progress(0.98, "多因子打分排序…")
            ranked = pick_top_n(merged, top_n)

            self.repo.save_screener_results(run.id, ranked)
            self.repo.finish_screener_run(
                run.id,
                status="done",
                screened_count=len(price_df),
                warnings=warnings,
            )

            return ScreenerRunResult(
                run_id=run.id,
                market=market_key,
                universe_id=universe_id,
                universe_size=len(entries),
                screened_count=len(price_df),
                top_n=top_n,
                warnings=warnings,
                results=ranked,
            )
        except Exception as exc:
            self.repo.finish_screener_run(
                run.id,
                status="failed",
                screened_count=0,
                warnings=warnings,
                error_message=str(exc),
            )
            raise
