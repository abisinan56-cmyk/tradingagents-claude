"""Record-and-replay: freeze both LLM answers and data-tool outputs to SQLite.

On the first run every LLM call and every data-vendor call is stored. A second
run with the same ticker, date and settings reads them back instead of calling
out, so it reproduces the first run exactly and costs nothing. Live news and
social feeds no longer drift between the two runs.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from langchain_core.caches import BaseCache
from langchain_core.globals import get_llm_cache, set_llm_cache
from langchain_core.load import dumps, loads


class _Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()  # analysts run in parallel threads
        with self._lock:
            self._db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
            self._db.commit()

    def get(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, value))
            self._db.commit()

    def clear(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM kv")
            self._db.commit()


def _key(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


class SQLiteLLMCache(BaseCache):
    def __init__(self, store: _Store):
        self.store = store

    def lookup(self, prompt: str, llm_string: str):
        raw = self.store.get("llm:" + _key(prompt, llm_string))
        if not raw:
            return None
        with warnings.catch_warnings():  # loads() is beta; the data is our own
            warnings.simplefilter("ignore")
            return loads(raw)

    def update(self, prompt: str, llm_string: str, return_val) -> None:
        self.store.put("llm:" + _key(prompt, llm_string), dumps(return_val))

    def clear(self, **kwargs) -> None:
        self.store.clear()


# Every place the agents fetch outside data reaches it through one of these names.
# Patched where they are looked up (the importing module), not where defined.
DATA_ENTRY_POINTS = (
    ("tradingagents.agents.tools", "route_to_vendor"),                  # all vendor tools
    ("tradingagents.agents.tools", "build_verified_market_snapshot"),   # market analyst's price check
    ("tradingagents.agents.analysts.sentiment_analyst", "fetch_reddit_posts"),
    ("tradingagents.agents.analysts.sentiment_analyst", "fetch_stocktwits_messages"),
    ("tradingagents.agents.context", "get_company_profile"),            # instrument identity
    ("ta_claude.model", "fetch_daily_rows"),                            # deterministic technical snapshot
)


def _cached(store: _Store, name: str, fn):
    def wrapper(*args, **kwargs):
        key = "data:" + _key(name, args, kwargs)
        hit = store.get(key)
        if hit is not None:
            return json.loads(hit)
        result = fn(*args, **kwargs)
        try:  # cache only what round-trips through JSON unchanged
            encoded = json.dumps(result)
            if json.loads(encoded) == result:
                store.put(key, encoded)
        except (TypeError, ValueError):
            pass
        return result
    return wrapper


@contextmanager
def replay(path: str | Path):
    """Enable record-and-replay for the duration of the block."""
    import importlib

    store = _Store(Path(path))
    patched = []
    for module_name, attr in DATA_ENTRY_POINTS:
        module = importlib.import_module(module_name)
        original = getattr(module, attr)
        setattr(module, attr, _cached(store, f"{module_name}.{attr}", original))
        patched.append((module, attr, original))
    previous_cache = get_llm_cache()
    set_llm_cache(SQLiteLLMCache(store))
    try:
        yield store
    finally:
        for module, attr, original in patched:
            setattr(module, attr, original)
        set_llm_cache(previous_cache)
