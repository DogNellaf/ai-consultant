"""The acceptance smoke on the real model: 10 questions from the FAQ answered from the right
fragment, 3 questions outside the base answered with an honest "don't know".

Needs the model (python scripts/download_model.py), skipped without it.
"""

import json

import pytest

from app import config
from app.engine import Consultant, Session
from app.kb import load_dir
from app.search import Searcher
from app.store import MemoryStore

SMOKE = json.loads((config.KB_DIR / "smoke.json").read_text(encoding="utf-8"))
needs_model = pytest.mark.skipif(
    not (config.MODEL_DIR / "onnx" / "model_quantized.onnx").exists(), reason="no model, run scripts/download_model.py"
)


@pytest.fixture(scope="module")
def real_consultant():
    from app.embed import E5Embedder

    store = MemoryStore()
    searcher = Searcher(store, E5Embedder(config.MODEL_DIR))
    searcher.index("kb", load_dir(config.KB_DIR))
    return Consultant(searcher, store)


@pytest.fixture(autouse=True)
def fake_thresholds():
    """Overrides the conftest fixture: the smoke runs on the real thresholds."""


@needs_model
@pytest.mark.parametrize("item", SMOKE["in_base"], ids=lambda i: i["q"])
def test_faq_question_finds_its_source(real_consultant, item):
    r = real_consultant.handle(Session("smoke", "widget"), item["q"], False)
    assert r.kind == "answer", r.search[0]
    assert item["title"] in [s["title"] for s in r.sources]


@needs_model
@pytest.mark.parametrize("q", SMOKE["off_base"])
def test_off_base_question_is_unknown(real_consultant, q):
    r = real_consultant.handle(Session("smoke", "widget"), q, False)
    assert r.kind == "unknown", r.search[0]
