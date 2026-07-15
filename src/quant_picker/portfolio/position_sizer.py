from __future__ import annotations

from dataclasses import dataclass

from quant_picker.config import load_settings
from quant_picker.market.detector import Market
from quant_picker.strategies.base import Signal


@dataclass
class PositionResult:
    amount: float
    shares: int


class PositionSizer:
    MODES = ("single_choice", "multi_strategy")

    def __init__(self) -> None:
        self.settings = load_settings()

    def _position_budget_pct(self) -> float:
        mode = self.settings.get("position_mode", "single_choice")
        max_pct = float(self.settings.get("max_single_position_pct", 0.30))
        per_w = float(self.settings.get("per_strategy_weight", 0.10))

        if mode == "multi_strategy":
            # Each enabled strategy gets per_strategy_weight; N strategies ≈ per_w × N total.
            return per_w
        # single_choice: user picks one strategy, size against full single-name cap.
        return max_pct

    def _allocation(
        self,
        signal: Signal,
        confidence: str = "medium",
    ) -> float:
        capital = float(self.settings.get("total_capital", 100000))
        max_pct = float(self.settings.get("max_single_position_pct", 0.30))
        budget_pct = self._position_budget_pct()

        base = capital * budget_pct * max(signal.strength, 0.0)
        if self.settings.get("backtest", {}).get("adjust_amount_by_confidence", True):
            if confidence == "low":
                base *= 0.5
            elif confidence == "high":
                base *= 1.0
            else:
                base *= 0.75
        return min(base, capital * max_pct)

    def _shares_for_amount(self, amount: float, price: float | None, lot: int) -> int:
        if not price or price <= 0 or lot <= 0 or amount <= 0:
            return 0
        return int(amount / price / lot) * lot

    def _reference_position(
        self,
        signal: Signal,
        confidence: str,
        price: float | None,
        lot: int,
    ) -> PositionResult:
        """Estimate a reference holding for buy/sell sizing."""
        allocation = self._allocation(signal, confidence)
        shares = self._shares_for_amount(allocation, price, lot)
        if shares > 0:
            return PositionResult(round(shares * price, 2), shares)

        capital = float(self.settings.get("total_capital", 100000))
        max_pct = float(self.settings.get("max_single_position_pct", 0.30))
        max_alloc = capital * max_pct
        shares = self._shares_for_amount(max_alloc, price, lot)
        if shares > 0:
            return PositionResult(round(shares * price, 2), shares)

        # Cannot form a whole lot; still show target allocation as suggested amount.
        return PositionResult(round(allocation, 2), 0)

    def compute(
        self,
        signal: Signal,
        market: Market,
        confidence: str = "medium",
        price: float | None = None,
    ) -> PositionResult:
        if signal.action == "hold":
            return PositionResult(0.0, 0)

        lot_sizes = self.settings.get("lot_size", {})
        lot = int(lot_sizes.get(market.value, lot_sizes.get("cn", 100)))

        ref = self._reference_position(signal, confidence, price, lot)
        if signal.action == "buy":
            return ref
        # sell: use the same reference position as the suggested exit size
        return ref
