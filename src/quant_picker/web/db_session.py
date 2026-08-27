"""One database session per browser session, released on every rerun.

Streamlit re-executes the whole script on each interaction, so building a
Session at page scope creates a new one per run and abandons the previous. An
abandoned Session keeps its connection checked out with a transaction still
open, which PostgreSQL reports as "idle in transaction". Those hold table locks
long enough to block a schema migration and, once the pool is drained, the app
stops responding entirely.

Reusing one Session and closing it at the start of each run keeps a browser tab
to a single connection, held only while a run is actually executing.
"""

from __future__ import annotations

import streamlit as st
from sqlalchemy.orm import Session

from quant_picker.storage.db import get_session_factory

_SESSION_KEY = "_db_session"


def web_session() -> Session:
    """The current browser session's database session.

    Schema setup is not done here: every page runs require_login() first, and
    that already calls init_db() behind a cache.
    """
    session = st.session_state.get(_SESSION_KEY)
    if session is None:
        # get_session_factory() memoises the sessionmaker itself, so there is no
        # cache_resource layer here that could outlive a rebuilt engine.
        session = get_session_factory()()
        st.session_state[_SESSION_KEY] = session
    return session


def release_web_session() -> None:
    """End the previous run's transaction and return its connection to the pool.

    ``Session.close()`` leaves the object reusable: the next query starts a
    fresh transaction. Called by ``require_login()``, which every page runs
    before touching the database.
    """
    session = st.session_state.get(_SESSION_KEY)
    if session is None:
        return
    try:
        session.close()
    except Exception:  # noqa: BLE001 - a dead connection must not block the page
        st.session_state.pop(_SESSION_KEY, None)
