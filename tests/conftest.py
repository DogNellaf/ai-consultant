import hashlib

import numpy as np
import pytest

from app import config
from app.embed import DIM
from app.engine import Consultant
from app.kb import load_dir
from app.lexical import stems
from app.search import Searcher
from app.service import Service
from app.store import MemoryStore


class FakeEmbedder:
    """Bag of word stems hashed into 384 numbers: similar words, similar vectors, no model."""

    def embed(self, texts, kind):
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for i, t in enumerate(texts):
            for s in stems(t):
                out[i, int(hashlib.md5(s[:4].encode()).hexdigest(), 16) % DIM] += 1
            out[i, 0] += 0.5  # keeps every vector non-zero
        return out / np.linalg.norm(out, axis=1, keepdims=True)


class FakeLLM:
    name = "fake"

    def __init__(self, answer="Доставка по городу стоит 250 ₽.", tokens=120, error=None):
        self.answer, self.tokens, self.error, self.calls = answer, tokens, error, []

    def complete(self, system, messages):
        from app.llm import Completion

        self.calls.append((system, messages))
        if self.error:
            raise self.error
        return Completion(self.answer, self.tokens)


@pytest.fixture(autouse=True)
def fake_thresholds(monkeypatch):
    # FakeEmbedder similarities are lower than e5 ones; the real thresholds are checked in test_smoke
    monkeypatch.setattr(config, "MIN_DENSE", 0.2)


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def searcher(store):
    s = Searcher(store, FakeEmbedder())
    s.index("kb", load_dir(config.KB_DIR))
    return s


@pytest.fixture
def sent():
    return []


@pytest.fixture
def consultant(searcher, store, sent):
    return Consultant(searcher, store, None, notify=lambda lead: sent.append(lead) or True)


@pytest.fixture
def service(consultant):
    return Service(consultant)
