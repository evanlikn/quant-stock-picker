from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))
os.environ.setdefault("QUANT_PICKER_ROOT", _ROOT)

import streamlit as st

from quant_picker.storage.db import get_session_factory, init_db
from quant_picker.storage.repository import Repository

st.set_page_config(page_title="建议历史", page_icon="📜", layout="wide")
init_db()
repo = Repository(get_session_factory()())

st.title("建议历史")

items = repo.list_watchlist()
options = {f"{i.symbol} ({i.interval})": i.id for i in items}
selected = st.selectbox("筛选自选", ["全部"] + list(options.keys()))
wid = None if selected == "全部" else options[selected]

history = repo.list_recommendation_history(wid, limit=300)
if not history:
    st.info("暂无历史记录")
else:
    rows = []
    item_map = {i.id: i for i in items}
    for r in history:
        w = item_map.get(r.watchlist_id)
        sym = w.symbol if w else str(r.watchlist_id)
        rows.append(
            {
                "时间": r.created_at,
                "股票": sym,
                "策略": r.strategy_name,
                "建议": r.action,
                "金额": r.amount,
                "股数": r.shares,
                "强度": r.strength,
                "理由": r.reason,
            }
        )
    st.dataframe(rows, use_container_width=True)
