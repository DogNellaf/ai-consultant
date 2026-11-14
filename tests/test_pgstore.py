"""PgStore against a real PostgreSQL. Runs when TEST_DATABASE_URL is set (CI starts postgres:16 as
a service), skipped otherwise."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from app.store import Lead, PgStore

URL = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL is not set")


@pytest.fixture
def pg():
    store = PgStore(URL)
    store._q("TRUNCATE leads, usage RESTART IDENTITY")
    return store


def test_leads_and_usage(pg):
    lead = Lead("Анна", "+79001234567", "Торт", "widget", history=[{"role": "user", "content": "Привет"}])
    assert pg.save_lead(lead) == 1
    pg.add_usage("v1", 1, 100)
    pg.add_usage("v1", 1, 50)
    pg.add_usage("v2", 0, 10)
    assert pg.messages_today("v1") == 2
    assert pg.tokens_today() == 160


def test_quota_reservation_across_independent_connections(pg):
    stores = [PgStore(URL) for _ in range(6)]
    try:
        pg.add_usage("concurrent", 9, 0)
        with ThreadPoolExecutor(max_workers=6) as pool:
            accepted = list(pool.map(lambda store: store.reserve_message("concurrent", 10, date.today()), stores))
        assert sum(accepted) == 1
        assert pg.messages_today("concurrent") == 10
    finally:
        for store in stores:
            store._conn.close()
