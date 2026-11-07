"""PgStore against a real PostgreSQL. Runs when TEST_DATABASE_URL is set (CI starts postgres:16 as
a service), skipped otherwise."""

import os

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
