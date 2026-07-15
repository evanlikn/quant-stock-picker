from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BacktestReport:
    total_return: float = 0.0
    win_rate: float = 0.0
    trade_count: int = 0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    equity_curve: list[float] = field(default_factory=list)
    fold_metrics: list[dict[str, Any]] = field(default_factory=list)
    fold_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_return": self.total_return,
            "win_rate": self.win_rate,
            "trade_count": self.trade_count,
            "max_drawdown": self.max_drawdown,
            "sharpe_ratio": self.sharpe_ratio,
            "profit_factor": self.profit_factor,
            "fold_count": self.fold_count,
            "equity_curve": self.equity_curve,
            "fold_metrics": self.fold_metrics,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BacktestReport:
        return cls(
            total_return=float(data.get("total_return", 0)),
            win_rate=float(data.get("win_rate", 0)),
            trade_count=int(data.get("trade_count", 0)),
            max_drawdown=float(data.get("max_drawdown", 0)),
            sharpe_ratio=float(data.get("sharpe_ratio", 0)),
            profit_factor=float(data.get("profit_factor", 0)),
            equity_curve=list(data.get("equity_curve") or []),
            fold_metrics=list(data.get("fold_metrics") or []),
            fold_count=int(data.get("fold_count", 0)),
        )
