"""Hybrid search: e5 similarity picks candidates, word overlap reranks them and decides
whether the base has an answer at all.

widget/kb-search.js repeats this file step by step for the browser mode.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import config
from .kb import Chunk
from .lexical import idf, overlap, stems

CANDIDATES = 12
LEXICAL_WEIGHT = 0.1


@dataclass
class Hit:
    chunk: Chunk
    dense: float
    lexical: float

    @property
    def score(self) -> float:
        return self.dense + LEXICAL_WEIGHT * self.lexical

    def as_dict(self) -> dict:
        return {
            "source": self.chunk.source,
            "title": self.chunk.title,
            "text": self.chunk.text,
            "dense": round(self.dense, 3),
            "lexical": round(self.lexical, 2),
            "score": round(self.score, 3),
        }


class Searcher:
    def __init__(self, store, embedder):
        self.store = store
        self.embedder = embedder
        self._stems: dict[tuple[str, ...], list[list[str]]] = {}

    def index(self, collection: str, chunks: list[Chunk]) -> int:
        vectors = self.embedder.embed([c.passage for c in chunks], "passage")
        self.store.replace_collection(collection, chunks, vectors)
        self._stems.clear()
        return len(chunks)

    def drop(self, collection: str) -> None:
        self.store.delete_collection(collection)
        self._stems.clear()

    def _corpus(self, collections: list[str]) -> list[list[str]]:
        key = tuple(sorted(collections))
        if key not in self._stems:
            self._stems[key] = [stems(c.passage) for c in self.store.chunks(collections)]
        return self._stems[key]

    def search(self, question: str, collections: list[str], k: int | None = None) -> list[Hit]:
        vec = self.embedder.embed([question], "query")[0]
        cands = self.store.nearest(vec, collections, CANDIDATES)
        q = stems(question)
        weights = idf(q, self._corpus(collections))
        hits = [Hit(c, dense, overlap(q, stems(c.passage), weights)) for c, dense in cands]
        hits.sort(key=lambda h: -h.score)
        return hits[: k or config.TOP_K]


def confident(hit: Hit | None, with_model: bool) -> bool:
    if hit is None or hit.dense < config.MIN_DENSE:
        return False
    return hit.lexical >= (config.MIN_LEXICAL_LLM if with_model else config.MIN_LEXICAL)


def shown_sources(hits: list[Hit]) -> list[Hit]:
    """The best fragment, plus the second one when it is almost as good
    ("сколько стоит доставка" is answered by both the city and the out-of-town price)."""
    if not hits:
        return []
    out = [hits[0]]
    if len(hits) > 1 and hits[0].score - hits[1].score <= config.SECOND_SOURCE_GAP and hits[1].lexical > 0:
        out.append(hits[1])
    return out
