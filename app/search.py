"""Search without a model: the question's words and the pieces of its words, in every fragment.

Each fragment gets two numbers: the share of the question's words it has, weighted by rarity
(lexical.py), and the share of the question's character 4-grams (grams.py), which catches changed
endings and typos. The score is words plus half the 4-grams. A base of a few dozen fragments, or a
visitor's PDF of a hundred, is scored whole in a millisecond; nothing is downloaded, nothing sits
in memory but the texts.

With a model the best fragments go to it, and the model itself says when they have no answer.
Without one the best fragment is the answer, so the bar is higher: most of the question's words,
or a good share of them backed by the 4-grams.
"""

from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass

from . import config
from .grams import containment, grams
from .kb import Chunk
from .lexical import idf, overlap, stems

GRAMS_WEIGHT = 0.5


@dataclass
class Hit:
    chunk: Chunk
    lexical: float
    grams: float

    @property
    def score(self) -> float:
        return self.lexical + GRAMS_WEIGHT * self.grams

    def as_dict(self) -> dict:
        return {
            "source": self.chunk.source,
            "title": self.chunk.title,
            "text": self.chunk.text,
            "lexical": round(self.lexical, 2),
            "grams": round(self.grams, 2),
            "score": round(self.score, 3),
        }


@dataclass
class _Indexed:
    chunk: Chunk
    stems: list[str]
    grams: Counter


class Searcher:
    """Fragments by collection: "kb" for the base, "upload:<session>" for a visitor's file."""

    def __init__(self):
        self._lock = threading.Lock()
        self._collections: dict[str, list[_Indexed]] = {}

    def index(self, collection: str, chunks: list[Chunk]) -> int:
        items = [_Indexed(c, stems(c.passage), grams(c.passage)) for c in chunks]
        with self._lock:
            self._collections[collection] = items
        return len(items)

    def drop(self, collection: str) -> None:
        with self._lock:
            self._collections.pop(collection, None)

    def chunks(self, collections: list[str]) -> list[Chunk]:
        return [i.chunk for col in collections for i in self._collections.get(col, [])]

    def search(self, question: str, collections: list[str], k: int | None = None) -> list[Hit]:
        items = [i for col in collections for i in self._collections.get(col, [])]
        q, qg = stems(question), grams(question)
        weights = idf(q, [i.stems for i in items])
        hits = [Hit(i.chunk, overlap(q, i.stems, weights), containment(qg, i.grams)) for i in items]
        hits.sort(key=lambda h: -h.score)
        return hits[: k or config.TOP_K]


def confident(hit: Hit | None, with_model: bool) -> bool:
    if hit is None:
        return False
    if with_model:
        return hit.score >= config.MIN_SCORE_LLM
    return hit.lexical >= config.MIN_LEXICAL_ALONE or (
        hit.lexical >= config.MIN_LEXICAL and hit.grams >= config.MIN_GRAMS
    )


def shown_sources(hits: list[Hit]) -> list[Hit]:
    """The best fragment, plus the second one when it is almost as good
    ("сколько стоит доставка" is answered by both the city and the out-of-town price)."""
    if not hits:
        return []
    out = [hits[0]]
    if len(hits) > 1 and hits[0].score - hits[1].score <= config.SECOND_SOURCE_GAP and hits[1].lexical > 0:
        out.append(hits[1])
    return out
