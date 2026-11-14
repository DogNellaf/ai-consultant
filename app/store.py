"""Storage: leads and the daily usage. The fragments live in the searcher's memory (search.py).

PgStore keeps them in PostgreSQL, MemoryStore in memory for tests and a run without a database.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime


@dataclass
class Lead:
    name: str
    phone: str
    summary: str
    channel: str  # "widget" or "telegram"
    history: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    id: int | None = None


class MemoryStore:
    def __init__(self):
        self._lock = threading.Lock()
        self.leads: list[Lead] = []
        self._usage: dict[tuple[str, str], list[int]] = {}

    def save_lead(self, lead: Lead) -> int:
        with self._lock:
            lead.id = len(self.leads) + 1
            self.leads.append(lead)
            return lead.id

    def add_usage(self, visitor: str, messages: int, tokens: int, day: date | None = None) -> None:
        key = ((day or date.today()).isoformat(), visitor)
        with self._lock:
            row = self._usage.setdefault(key, [0, 0])
            row[0] += messages
            row[1] += tokens
            # yesterday's rows are of no use: the store does not grow day after day
            for k in [k for k in self._usage if k[0] < key[0]]:
                del self._usage[k]

    def messages_today(self, visitor: str) -> int:
        with self._lock:
            return self._usage.get((date.today().isoformat(), visitor), [0, 0])[0]

    def reserve_message(self, visitor: str, limit: int, day: date) -> bool:
        with self._lock:
            for key in [key for key in self._usage if key[0] < day.isoformat()]:
                del self._usage[key]
            row = self._usage.setdefault((day.isoformat(), visitor), [0, 0])
            if row[0] >= limit:
                return False
            row[0] += 1
            return True

    def tokens_today(self) -> int:
        today = date.today().isoformat()
        with self._lock:
            return sum(v[1] for (d, _), v in self._usage.items() if d == today)


SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id serial PRIMARY KEY,
    name text NOT NULL,
    phone text NOT NULL,
    summary text NOT NULL,
    channel text NOT NULL,
    history jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS usage (
    day date NOT NULL,
    visitor text NOT NULL,
    messages integer NOT NULL DEFAULT 0,
    tokens integer NOT NULL DEFAULT 0,
    PRIMARY KEY (day, visitor)
);
"""


class PgStore:
    def __init__(self, url: str):
        import psycopg

        self._conn = psycopg.connect(url, autocommit=True)
        self._conn.execute(SCHEMA)
        self._lock = threading.Lock()

    def _q(self, sql: str, params=()):
        with self._lock:
            return self._conn.execute(sql, params)

    def save_lead(self, lead: Lead) -> int:
        row = self._q(
            "INSERT INTO leads (name, phone, summary, channel, history) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (lead.name, lead.phone, lead.summary, lead.channel, json.dumps(lead.history, ensure_ascii=False)),
        ).fetchone()
        lead.id = row[0]
        return lead.id

    def add_usage(self, visitor: str, messages: int, tokens: int, day: date | None = None) -> None:
        self._q(
            "INSERT INTO usage (day, visitor, messages, tokens) VALUES (%s,%s,%s,%s)"
            " ON CONFLICT (day, visitor) DO UPDATE SET messages = usage.messages + EXCLUDED.messages,"
            " tokens = usage.tokens + EXCLUDED.tokens",
            (day or date.today(), visitor, messages, tokens),
        )

    def messages_today(self, visitor: str) -> int:
        row = self._q("SELECT messages FROM usage WHERE day = %s AND visitor = %s", (date.today(), visitor)).fetchone()
        return row[0] if row else 0

    def reserve_message(self, visitor: str, limit: int, day: date) -> bool:
        if limit <= 0:
            return False
        return (
            self._q(
                "INSERT INTO usage (day, visitor, messages, tokens) VALUES (%s,%s,1,0)"
                " ON CONFLICT (day, visitor) DO UPDATE SET messages = usage.messages + 1"
                " WHERE usage.messages < %s RETURNING messages",
                (day, visitor, limit),
            ).fetchone()
            is not None
        )

    def tokens_today(self) -> int:
        return self._q("SELECT coalesce(sum(tokens), 0) FROM usage WHERE day = %s", (date.today(),)).fetchone()[0]


def lead_dict(lead: Lead) -> dict:
    return asdict(lead)


def open_store(url: str):
    return PgStore(url) if url else MemoryStore()
