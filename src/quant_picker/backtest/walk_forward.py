from __future__ import annotations

import itertools
from typing import Any

import pandas as pd

from quant_picker.backtest.engine import BacktestEngine
from quant_picker.backtest.metrics import aggregate_oos_reports
from quant_picker.backtest.report import BacktestReport
from quant_picker.backtest.wfo_windows import (
    iter_walk_forward_folds,
    parse_window_days,
    window_sizes,
)
from quant_picker.config import load_settings
from quant_picker.strategies.registry import build_strategy


def _grid_combinations(space: dict[str, list], max_combos: int) -> list[dict[str, Any]]:
    keys = list(space.keys())
    values = [space[k] for k in keys]
    combos = []
    for combo in itertools.product(*values):
        combos.append(dict(zip(keys, combo)))
        if len(combos) >= max_combos:
            break
    return combos


def search_best_params(
    train_df: pd.DataFrame,
    strategy_name: str,
    interval: str,
    param_space: dict[str, list],
) -> tuple[dict[str, Any], float]:
    settings = load_settings()
    wf = settings.get("walk_forward", {})
    objective = wf.get("objective", "sharpe_ratio")
    max_combos = wf.get("max_grid_combinations", 200)
    engine = BacktestEngine()
    best_params: dict[str, Any] = {}
    best_score = float("-inf")

    for params in _grid_combinations(param_space, max_combos):
        if "short_window" in params and "long_window" in params:
            if params["short_window"] >= params["long_window"]:
                continue
        if "entry_window" in params and "exit_window" in params:
            if params["exit_window"] >= params["entry_window"]:
                continue
        strategy = build_strategy(strategy_name, interval, params)
        report = engine.run(train_df, strategy, interval)
        score = getattr(report, objective, report.sharpe_ratio)
        if score > best_score:
            best_score = score
            best_params = params
    return best_params, best_score


class WalkForwardEngine:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.wf = self.settings.get("walk_forward", {})
        self.engine = BacktestEngine()

    def _step_candidates(self, interval: str) -> list[int]:
        raw = self.wf.get("step_bars_candidates", {}).get(interval)
        if not raw:
            _, _, default = window_sizes(interval)
            return [default]
        return [parse_window_days(v) for v in raw]

    def run_for_strategy(
        self,
        df: pd.DataFrame,
        strategy_name: str,
        interval: str,
        step_bars: int | None = None,
    ) -> tuple[dict[str, Any], BacktestReport]:
        min_folds = int(self.wf.get("min_folds", 3))
        cfg_space = build_strategy(strategy_name, interval).param_space(interval)

        oos_reports: list[BacktestReport] = []
        live_params: dict[str, Any] = {}
        folds = 0

        for train_slice, test_slice in iter_walk_forward_folds(
            df, interval, step_override=step_bars
        ):
            best_params, _ = search_best_params(train_slice, strategy_name, interval, cfg_space)
            if not best_params:
                best_params = build_strategy(strategy_name, interval)._params  # type: ignore
            live_params = best_params
            strategy = build_strategy(strategy_name, interval, best_params)
            oos = self.engine.run(test_slice, strategy, interval)
            oos_reports.append(oos)
            folds += 1

        if folds < min_folds:
            defaults = build_strategy(strategy_name, interval)
            live_params = defaults._params  # type: ignore
            full_report = self.engine.run(df, defaults, interval)
            full_report.fold_count = folds
            return live_params, full_report

        agg = aggregate_oos_reports(oos_reports)
        agg.fold_count = folds
        return live_params, agg

    def find_best_step_bars(
        self,
        df: pd.DataFrame,
        strategy_name: str,
        interval: str,
    ) -> tuple[int, BacktestReport]:
        _, _, default_step = window_sizes(interval)
        best_step = default_step
        best_report = BacktestReport()
        best_score = float("-inf")
        objective = self.wf.get("objective", "sharpe_ratio")
        min_folds = int(self.wf.get("min_folds", 3))

        for step in self._step_candidates(interval):
            _, report = self.run_for_strategy(df, strategy_name, interval, step_bars=step)
            score = getattr(report, objective, report.sharpe_ratio)
            if report.fold_count >= min_folds and score > best_score:
                best_score = score
                best_step = step
                best_report = report

        if best_report.fold_count == 0:
            _, best_report = self.run_for_strategy(
                df, strategy_name, interval, step_bars=default_step
            )
            best_step = default_step
        return best_step, best_report
