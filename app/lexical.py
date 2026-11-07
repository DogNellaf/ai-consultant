"""Word overlap between a question and a fragment, weighted by rarity: the main half of the search.

A question that shares no meaningful word with the best fragment is almost always off topic, so
the overlap decides the "don't know" when there is no model. The stemming is a crude prefix cut
on purpose: doc-check uses the same file, so both projects agree on every number.
"""

from __future__ import annotations

import math
import re

STEM = 5  # "доставка", "доставки" -> "доста"
MIN_MATCH = 4  # a shorter common prefix is not a match ("пост" still matches "постные")

STOPWORDS = set(
    """
    а без более бы был была были было быть в вам вас ваш ваша ваше ваши весь во вот все всё всего
    вы где да даже для до его ее её если есть еще ещё же за и из или им их к как какая какие какой
    когда кто ли либо мне мной мы на над надо не него нее неё нет ни них но ну о об однако он она
    они оно от очень по под при про с со так также такой там те тем то того тоже той только том
    ты у уже хотя чего чей чем что чтобы чье чьё эта эти это этот я можно нужно сколько почему
    будет будут могу может могут хочу хотим подскажите скажите пожалуйста здравствуйте привет
    the a an is are of to in on for and or what how when where can do does
    """.split()
)

_WORD = re.compile(r"[a-zа-я]+")


def stems(text: str) -> list[str]:
    words = _WORD.findall(text.lower().replace("ё", "е"))
    out = []
    for w in words:
        if len(w) < 3 or w in STOPWORDS:
            continue
        s = w[:STEM]
        if s not in out:
            out.append(s)
    return out


def _match(a: str, b: str) -> bool:
    if min(len(a), len(b)) < MIN_MATCH:
        return a == b
    return a.startswith(b) or b.startswith(a)


def idf(question_stems: list[str], corpus: list[list[str]]) -> dict[str, float]:
    """Rarer words weigh more: "стоит" is in many price fragments, "медовик" in one.
    A word the base does not have at all gets the highest weight."""
    n = len(corpus)
    out = {}
    for q in question_stems:
        df = sum(1 for doc in corpus if any(_match(q, p) for p in doc))
        out[q] = math.log((n + 1) / (df + 1)) + 1
    return out


def overlap(question_stems: list[str], passage_stems: list[str], weights: dict[str, float]) -> float:
    """Weighted share of the question's words found in the fragment, 0..1."""
    total = sum(weights[q] for q in question_stems)
    if not total:
        return 0.0
    hit = sum(weights[q] for q in question_stems if any(_match(q, p) for p in passage_stems))
    return hit / total
