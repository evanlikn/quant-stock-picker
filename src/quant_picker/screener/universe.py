from __future__ import annotations

import re
from dataclasses import dataclass

from quant_picker.config import load_screener_config
from quant_picker.data.providers.tickflow_client import get_tickflow_client


@dataclass(frozen=True)
class UniverseEntry:
    tf_symbol: str
    symbol: str
    market: str
    name: str | None
    instrument_type: str | None


def universe_id_for_market(market: str) -> str:
    cfg = load_screener_config()
    universes = cfg.get("universes") or {}
    universe_id = universes.get(market.lower())
    if not universe_id:
        raise ValueError(f"未配置市场 {market} 的股票池，请在 config/screener.yaml 中设置 universes")
    return str(universe_id)


def load_universe_symbols(market: str) -> list[str]:
    universe_id = universe_id_for_market(market)
    detail = get_tickflow_client().universes.get(universe_id)
    symbols = detail.get("symbols") or []
    if not symbols:
        raise ValueError(f"股票池 {universe_id} 为空")
    return list(symbols)


def _is_st_name(name: str | None) -> bool:
    if not name:
        return False
    return bool(re.search(r"\*?ST", name, re.IGNORECASE))


def filter_universe_entries(entries: list[UniverseEntry]) -> list[UniverseEntry]:
    cfg = load_screener_config()
    filters = cfg.get("filters") or {}
    exclude_st = bool(filters.get("exclude_st", True))
    exclude_bj = bool(filters.get("exclude_bj", True))
    exclude_types = {str(x).lower() for x in (filters.get("exclude_types") or [])}

    kept: list[UniverseEntry] = []
    for entry in entries:
        if exclude_bj and entry.tf_symbol.endswith(".BJ"):
            continue
        inst_type = (entry.instrument_type or "stock").lower()
        if inst_type in exclude_types:
            continue
        if exclude_st and _is_st_name(entry.name):
            continue
        kept.append(entry)
    return kept


def load_universe_entries(market: str) -> tuple[str, list[UniverseEntry]]:
    universe_id = universe_id_for_market(market)
    tf_symbols = load_universe_symbols(market)
    cfg = load_screener_config()
    batch_size = int(cfg.get("instrument_batch_size") or 500)
    client = get_tickflow_client()

    entries: list[UniverseEntry] = []
    for i in range(0, len(tf_symbols), batch_size):
        chunk = tf_symbols[i : i + batch_size]
        rows = client.instruments.get(chunk)
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows:
            tf_symbol = str(row.get("symbol") or "")
            if not tf_symbol:
                continue
            code = str(row.get("code") or tf_symbol.split(".", 1)[0])
            region = str(row.get("region") or market).lower()
            entries.append(
                UniverseEntry(
                    tf_symbol=tf_symbol,
                    symbol=code,
                    market=region,
                    name=row.get("name"),
                    instrument_type=row.get("type") or row.get("instrument_type"),
                )
            )

    return universe_id, filter_universe_entries(entries)
