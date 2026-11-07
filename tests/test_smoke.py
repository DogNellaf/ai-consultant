"""The acceptance smoke on the real base and the real thresholds (knowledge/kolosok/smoke.json).

- every question from the base finds its fragment first: that is what goes to the model;
- without a model the fragment itself is the answer, except the questions marked "needs_model":
  a paraphrase with few shared words, which the search ranks right but cannot vouch for alone;
- every question outside the base gets an honest "don't know" without a model, and with a model
  it either does not reach the model at all or reaches it with fragments that do not answer it.
"""

import json

import pytest

from app import config
from app.engine import Consultant, Session
from app.kb import load_dir
from app.search import Searcher, confident
from app.store import MemoryStore

SMOKE = json.loads((config.KB_DIR / "smoke.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real():
    searcher = Searcher()
    searcher.index("kb", load_dir(config.KB_DIR))
    return searcher, Consultant(searcher, MemoryStore())


@pytest.mark.parametrize("item", SMOKE["in_base"], ids=lambda i: i["q"])
def test_question_finds_its_fragment_first(real, item):
    searcher, _ = real
    hits = searcher.search(item["q"], ["kb"], config.TOP_K_LLM)
    assert hits[0].chunk.title == item["title"], [h.as_dict() for h in hits[:3]]
    assert confident(hits[0], with_model=True)


@pytest.mark.parametrize("item", [i for i in SMOKE["in_base"] if not i.get("needs_model")], ids=lambda i: i["q"])
def test_answer_without_a_model(real, item):
    _, consultant = real
    r = consultant.handle(Session("smoke", "widget"), item["q"], False)
    assert r.kind == "answer", r.search[0]
    assert item["title"] in [s["title"] for s in r.sources]


@pytest.mark.parametrize("q", SMOKE["off_base"])
def test_off_base_question_is_unknown(real, q):
    _, consultant = real
    r = consultant.handle(Session("smoke", "widget"), q, False)
    assert r.kind == "unknown", r.search[0]
