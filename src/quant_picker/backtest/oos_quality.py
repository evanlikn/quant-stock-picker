from __future__ import annotations

from quant_picker.backtest.report import BacktestReport
from quant_picker.config import load_settings


def oos_sample_warning(oos: BacktestReport | None) -> str | None:
    """Return a user-facing warning when OOS metrics are statistically weak."""
    if oos is None:
        return "尚无 Walk-forward OOS 结果，指标不可用。"

    settings = load_settings()
    wf = settings.get("walk_forward", {})
    min_folds = int(wf.get("min_folds", 3))
    min_avg_trades = int(wf.get("min_oos_avg_trades", 3))

    issues: list[str] = []
    if oos.fold_count < min_folds:
        issues.append(f"WFO 折数不足（{oos.fold_count} < {min_folds}）")
    if oos.trade_count < min_avg_trades:
        issues.append(
            f"OOS 平均交易次数过少（{oos.trade_count} < {min_avg_trades}，"
            "为各测试窗完成平仓次数的均值）"
        )
    if oos.fold_metrics:
        total_trades = sum(int(f.get("trade_count", 0)) for f in oos.fold_metrics)
        if total_trades < min_avg_trades:
            issues.append(f"OOS 各折合计交易仅 {total_trades} 笔")

    if not issues:
        return None
    return (
        "⚠ OOS 样本不足："
        + "；".join(issues)
        + "。胜率、收益、Sharpe 等指标仅供参考，请结合「全样本回测」与当前信号综合判断。"
    )
