"""Wiring shared by the API and the bot: store, model, search, base index."""

from __future__ import annotations

import logging

from . import config, llm
from .engine import Consultant
from .kb import load_dir
from .notify import send_lead
from .search import Searcher
from .service import Service
from .store import open_store

log = logging.getLogger(__name__)


def build(store=None, model=..., notify=send_lead) -> Service:
    store = store if store is not None else open_store(config.DATABASE_URL)
    searcher = Searcher()
    n = searcher.index("kb", load_dir(config.KB_DIR))
    model = llm.from_config() if model is ... else model
    log.info("base %s: %d fragments, model %s", config.KB_DIR.name, n, model.name if model else "none")
    return Service(Consultant(searcher, store, model, notify))
