from __future__ import annotations

from dataclasses import dataclass

from quant_picker.config import load_settings
from quant_picker.market.detector import Market
from quant_picker.strategies.base import Signal


@dataclass
class PositionResult:
    amount: float
    shares: int


def get_position_sizing_config() -> dict:
    settings = load_settings()
    cfg = settings.get("position_sizing", {}) or {}
    return {
        "mode": str(cfg.get("mode", "atr_risk")),
        "atr_period": int(cfg.get("atr_period", 14)),
        "risk_pct": float(cfg.get("risk_pct", 0.01)),
        "stop_atr_mult": float(cfg.get("stop_atr_mult", 2.0)),
    }


def compute_atr_risk_position(
    capital: float,
    atr: float,
    price: float,
    *,
    lot: int = 1,
    max_position_value: float | None = None,
) -> PositionResult:
    """Fixed-risk sizing: risk = capital × risk_pct, stop distance = stop_atr_mult × ATR."""
    cfg = get_position_sizing_config()
    if atr <= 0 or price <= 0 or capital <= 0:
        return PositionResult(0.0, 0)

    risk_amount = capital * cfg["risk_pct"]
    stop_distance = cfg["stop_atr_mult"] * atr
    raw_shares = risk_amount / stop_distance

    if lot > 1:
        shares = int(raw_shares / lot) * lot
    else:
        shares = int(raw_shares)

    if shares <= 0:
        return PositionResult(round(risk_amount, 2), 0)

    amount = shares * price
    cap = max_position_value if max_position_value is not None else capital
    max_pct_cap = cap
    if amount > max_pct_cap:
        if lot > 1:
            shares = int(max_pct_cap / price / lot) * lot
        else:
            shares = int(max_pct_cap / price)
        amount = shares * price

    if shares <= 0:
        return PositionResult(round(risk_amount, 2), 0)
    return PositionResult(round(amount, 2), shares)


def compute_atr_risk_units(
    capital: float,
    atr: float,
    price: float,
    *,
    max_position_value: float | None = None,
) -> float:
    """Fractional units for backtest (no lot rounding)."""
    cfg = get_position_sizing_config()
    if atr <= 0 or price <= 0 or capital <= 0:
        return 0.0

    risk_amount = capital * cfg["risk_pct"]
    units = risk_amount / (cfg["stop_atr_mult"] * atr)
    cost = units * price
    cap = max_position_value if max_position_value is not None else capital
    if cost > cap:
        units = cap / price
    return max(units, 0.0)


def atr_stop_price(entry_price: float, atr: float) -> float:
    cfg = get_position_sizing_config()
    return entry_price - cfg["stop_atr_mult"] * atr


def trailing_stop_candidate(close: float, atr: float) -> float:
    """Stop level from latest close and ATR (trailing component)."""
    cfg = get_position_sizing_config()
    return close - cfg["stop_atr_mult"] * atr


def advance_trailing_stop(
    current_stop: float | None,
    close: float,
    atr: float,
    *,
    entry_price: float | None = None,
    entry_atr: float | None = None,
) -> float | None:
    """Ratchet stop upward using latest ATR; never loosen."""
    if atr <= 0 or close <= 0:
        return current_stop if current_stop and current_stop > 0 else None

    candidate = trailing_stop_candidate(close, atr)
    if current_stop is None or current_stop <= 0:
        initial = None
        if entry_price and entry_price > 0 and entry_atr and entry_atr > 0:
            initial = atr_stop_price(entry_price, entry_atr)
        base = initial if initial is not None else candidate
        return max(base, candidate)
    return max(current_stop, candidate)


class PositionSizer:
    MODES = ("single_choice", "multi_strategy")

    def __init__(self) -> None:
        self.settings = load_settings()

    def _position_budget_pct(self) -> float:
        mode = self.settings.get("position_mode", "single_choice")
        max_pct = float(self.settings.get("max_single_position_pct", 0.30))
        per_w = float(self.settings.get("per_strategy_weight", 0.10))

        if mode == "multi_strategy":
            return per_w
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
        """Fixed-percent allocation (legacy mode)."""
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

        return PositionResult(round(allocation, 2), 0)

    def _atr_risk_position(
        self,
        price: float | None,
        atr: float | None,
        lot: int,
    ) -> PositionResult:
        capital = float(self.settings.get("total_capital", 100000))
        max_pct = float(self.settings.get("max_single_position_pct", 0.30))
        if not price or price <= 0 or not atr or atr <= 0:
            return PositionResult(0.0, 0)
        return compute_atr_risk_position(
            capital,
            atr,
            price,
            lot=lot,
            max_position_value=capital * max_pct,
        )

    def compute(
        self,
        signal: Signal,
        market: Market,
        confidence: str = "medium",
        price: float | None = None,
        atr: float | None = None,
    ) -> PositionResult:
        if signal.action == "hold":
            return PositionResult(0.0, 0)

        lot_sizes = self.settings.get("lot_size", {})
        lot = int(lot_sizes.get(market.value, lot_sizes.get("cn", 100)))

        cfg = get_position_sizing_config()
        if cfg["mode"] == "atr_risk":
            return self._atr_risk_position(price, atr, lot)

        ref = self._reference_position(signal, confidence, price, lot)
        return ref
