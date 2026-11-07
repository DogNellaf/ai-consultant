import pytest

from app import config
from app.engine import Consultant
from app.kb import load_dir
from app.search import Searcher
from app.service import Service
from app.store import MemoryStore


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


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def searcher():
    s = Searcher()
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
