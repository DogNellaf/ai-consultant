"""How much of a question is in a fragment, by character 4-grams.

The word overlap (lexical.py) compares stems; this compares pieces of words, so a question still
meets its fragment through a changed ending or a typo: «доставляете» and «доставка», «почём» and
«цена» do not share a stem, «доставка» and «доставки» share most of their 4-grams. The share of the
question's 4-grams found in the fragment is a number from 0 to 1, cheap to count for a whole base.
"""

from __future__ import annotations

import re
from collections import Counter

_NON_WORD = re.compile(r"[^\w%]+")
N = 4


def grams(text: str) -> Counter:
    t = " " + " ".join(_NON_WORD.sub(" ", text.lower().replace("ё", "е")).split()) + " "
    return Counter(t[i : i + N] for i in range(len(t) - N + 1))


def containment(question: Counter, passage: Counter) -> float:
    total = sum(question.values())
    if not total:
        return 0.0
    return sum(min(c, passage.get(g, 0)) for g, c in question.items()) / total
