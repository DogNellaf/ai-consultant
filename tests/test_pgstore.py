"""PgStore against a real PostgreSQL with pgvector. Runs when TEST_DATABASE_URL is set
(CI starts pgvector/pgvector:pg16 as a service), skipped otherwise."""

import os

import numpy as np
import pytest

from app import config
from app.kb import load_dir
from app.search import Searcher
from app.store import Lead, PgStore
from tests.conftest import FakeEmbedder

URL = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL is not set")


@pytest.fixture
def pg():
    store = PgStore(URL)
    store._q("TRUNCATE chunks, leads, usage RESTART IDENTITY")
    return store


def test_search_on_pgvector_matches_memory(pg, searcher):
    pg_searcher = Searcher(pg, FakeEmbedder())
    pg_searcher.index("kb", load_dir(config.KB_DIR))
    q = "Можно забрать заказ самому?"
    a = [(h.chunk.title, round(h.score, 4)) for h in pg_searcher.search(q, ["kb"])]
    b = [(h.chunk.title, round(h.score, 4)) for h in searcher.search(q, ["kb"])]
    assert a == b


def test_collections_are_separate_and_replaced(pg):
    s = Searcher(pg, FakeEmbedder())
    s.index("kb", load_dir(config.KB_DIR))
    from app.kb import parse_plain

    s.index("upload:x", parse_plain("Пирог с тыквой по пятницам.", "menu.txt", "upload:x"))
    assert len(pg.chunks(["upload:x"])) == 1
    assert {c.collection for c in pg.chunks(["kb", "upload:x"])} == {"kb", "upload:x"}
    s.drop("upload:x")
    assert pg.chunks(["upload:x"]) == []
    s.index("upload:y", parse_plain("Ещё файл.", "a.txt", "upload:y"))
    pg.delete_uploads()
    assert pg.chunks(["upload:y"]) == [] and pg.chunks(["kb"])
    vec = np.zeros(384, dtype=np.float32)
    vec[0] = 1
    assert all(c.collection == "kb" for c, _ in pg.nearest(vec, ["kb"], 5))


def test_leads_and_usage(pg):
    lead = Lead("Анна", "+79001234567", "Торт", "widget", history=[{"role": "user", "content": "Привет"}])
    assert pg.save_lead(lead) == 1
    pg.add_usage("v1", 1, 100)
    pg.add_usage("v1", 1, 50)
    pg.add_usage("v2", 0, 10)
    assert pg.messages_today("v1") == 2
    assert pg.tokens_today() == 160
