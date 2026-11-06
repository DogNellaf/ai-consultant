"""Storage: fragments with vectors, leads and the daily usage.

PgStore keeps vectors in PostgreSQL with pgvector (an HNSW index on cosine distance). MemoryStore
does the same with numpy and serves tests and a run without a database.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

import numpy as np

from .embed import DIM
from .kb import Chunk


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
        self._chunks: dict[str, list[Chunk]] = {}
        self._vecs: dict[str, np.ndarray] = {}
        self.leads: list[Lead] = []
        self._usage: dict[tuple[str, str], list[int]] = {}

    def replace_collection(self, collection: str, chunks: list[Chunk], vectors: np.ndarray) -> None:
        with self._lock:
            self._chunks[collection] = list(chunks)
            self._vecs[collection] = np.asarray(vectors, dtype=np.float32).reshape(-1, DIM)

    def delete_collection(self, collection: str) -> None:
        with self._lock:
            self._chunks.pop(collection, None)
            self._vecs.pop(collection, None)

    def delete_uploads(self) -> None:
        for col in [c for c in self._chunks if c.startswith("upload:")]:
            self.delete_collection(col)

    def chunks(self, collections: list[str]) -> list[Chunk]:
        return [c for col in collections for c in self._chunks.get(col, [])]

    def nearest(self, vector: np.ndarray, collections: list[str], k: int) -> list[tuple[Chunk, float]]:
        pairs = []
        for col in collections:
            if col in self._vecs and len(self._chunks[col]):
                sims = self._vecs[col] @ vector
                pairs += list(zip(self._chunks[col], sims.tolist(), strict=True))
        pairs.sort(key=lambda p: -p[1])
        return pairs[:k]

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

    def messages_today(self, visitor: str) -> int:
        return self._usage.get((date.today().isoformat(), visitor), [0, 0])[0]

    def tokens_today(self) -> int:
        today = date.today().isoformat()
        return sum(v[1] for (d, _), v in self._usage.items() if d == today)


SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS chunks (
    id text NOT NULL,
    collection text NOT NULL,
    source text NOT NULL,
    title text NOT NULL,
    body text NOT NULL,
    embedding vector({DIM}) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (collection, id)
);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
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
        from pgvector.psycopg import register_vector

        self._conn = psycopg.connect(url, autocommit=True)
        self._conn.execute(SCHEMA)
        register_vector(self._conn)
        self._lock = threading.Lock()

    def _q(self, sql: str, params=()):
        with self._lock:
            return self._conn.execute(sql, params)

    def replace_collection(self, collection: str, chunks: list[Chunk], vectors: np.ndarray) -> None:
        with self._lock, self._conn.transaction():
            self._conn.execute("DELETE FROM chunks WHERE collection = %s", (collection,))
            with self._conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (id, collection, source, title, body, embedding) VALUES (%s,%s,%s,%s,%s,%s)",
                    [
                        (c.id, collection, c.source, c.title, c.text, np.asarray(v, dtype=np.float32))
                        for c, v in zip(chunks, vectors, strict=True)
                    ],
                )

    def delete_collection(self, collection: str) -> None:
        self._q("DELETE FROM chunks WHERE collection = %s", (collection,))

    def delete_uploads(self) -> None:
        """Sessions live in memory: after a restart their files have no owner."""
        self._q("DELETE FROM chunks WHERE collection LIKE 'upload:%%'")

    def chunks(self, collections: list[str]) -> list[Chunk]:
        rows = self._q(
            "SELECT id, collection, source, title, body FROM chunks WHERE collection = ANY(%s) ORDER BY created_at, id",
            (collections,),
        ).fetchall()
        return [Chunk(id=r[0], collection=r[1], source=r[2], title=r[3], text=r[4]) for r in rows]

    def nearest(self, vector: np.ndarray, collections: list[str], k: int) -> list[tuple[Chunk, float]]:
        rows = self._q(
            "SELECT id, collection, source, title, body, 1 - (embedding <=> %s) AS sim FROM chunks"
            " WHERE collection = ANY(%s) ORDER BY embedding <=> %s LIMIT %s",
            (np.asarray(vector, dtype=np.float32), collections, np.asarray(vector, dtype=np.float32), k),
        ).fetchall()
        return [(Chunk(id=r[0], collection=r[1], source=r[2], title=r[3], text=r[4]), float(r[5])) for r in rows]

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

    def tokens_today(self) -> int:
        return self._q("SELECT coalesce(sum(tokens), 0) FROM usage WHERE day = %s", (date.today(),)).fetchone()[0]


def lead_dict(lead: Lead) -> dict:
    return asdict(lead)


def open_store(url: str):
    return PgStore(url) if url else MemoryStore()
