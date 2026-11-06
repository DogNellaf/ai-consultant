"""What the widget API and the bot call: sessions, limits, the model queue and uploads.

- a visitor has MESSAGES_PER_DAY questions a day (the lead form does not count), then the
  consultant stops politely until tomorrow;
- when the day's tokens reach DAILY_TOKEN_BUDGET the model is switched off and the answers come
  from the fragments, which cost nothing;
- model calls wait in a queue of LLM_CONCURRENCY (GigaChat gives individuals one stream);
  more than QUEUE_MAX waiting and the visitor is asked to repeat in a minute.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid

from . import config
from .engine import EXAMPLES, MANAGER, Consultant, Reply, Session, wants_manager
from .uploads import UploadError, extract_text, to_chunks


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def visitor_key(raw: str) -> str:
    """IP or Telegram id, salted and hashed: usage rows carry no address."""
    return hashlib.sha256(f"{config.QUOTA_SALT}|{raw}".encode()).hexdigest()[:24]


class Service:
    def __init__(self, consultant: Consultant):
        self.consultant = consultant
        self.store = consultant.store
        self.sessions: dict[str, tuple[Session, float]] = {}
        self._sem = asyncio.Semaphore(config.LLM_CONCURRENCY)
        self._waiting = 0

    # sessions ----------------------------------------------------------------------------------

    def session(self, session_id: str | None, channel: str) -> Session:
        self._expire()
        if session_id and session_id in self.sessions:
            s = self.sessions[session_id][0]
        else:
            s = Session(id=session_id or uuid.uuid4().hex, channel=channel)
        self.sessions[s.id] = (s, time.time())
        return s

    def _expire(self) -> None:
        now = time.time()
        for sid, (s, seen) in list(self.sessions.items()):
            if now - seen > config.SESSION_TTL:
                if s.upload:
                    self.consultant.searcher.drop(f"upload:{sid}")
                del self.sessions[sid]

    # questions ---------------------------------------------------------------------------------

    def remaining(self, visitor: str) -> int:
        return max(0, config.MESSAGES_PER_DAY - self.store.messages_today(visitor))

    async def ask(self, s: Session, visitor: str, text: str) -> Reply:
        text = (text or "").strip()[:1000]
        if not text:
            return self.consultant.greeting()
        # the lead form, and the request that starts it, stay open after the limit: the limit
        # message itself offers the manager
        question = s.lead is None and not wants_manager(text)
        if question and self.remaining(visitor) <= 0:
            return Reply(
                "limit",
                f"На сегодня лимит демо исчерпан: {config.MESSAGES_PER_DAY} вопросов в сутки. "
                "Возвращайтесь завтра или оставьте заявку менеджеру.",
                buttons=[MANAGER],
            )
        use_model = self.consultant.llm is not None and self.store.tokens_today() < config.DAILY_TOKEN_BUDGET
        if question and use_model:
            if self._waiting >= config.QUEUE_MAX:
                return Reply("busy", "Сейчас много вопросов, повторите через минуту.", buttons=EXAMPLES)
            self._waiting += 1
            try:
                async with self._sem:
                    reply = await asyncio.to_thread(self.consultant.handle, s, text, True)
            finally:
                self._waiting -= 1
        else:
            reply = await asyncio.to_thread(self.consultant.handle, s, text, False)
        if reply.counted or reply.tokens:
            self.store.add_usage(visitor, 1 if reply.counted else 0, reply.tokens)
        return reply

    # uploads -----------------------------------------------------------------------------------

    async def upload(self, s: Session, filename: str, data: bytes) -> Reply:
        try:
            text = extract_text(filename, data)
        except UploadError as e:
            return Reply("error", str(e))
        chunks = to_chunks(filename, text, s.id)
        n = await asyncio.to_thread(self.consultant.searcher.index, f"upload:{s.id}", chunks)
        s.upload = filename
        return Reply(
            "upload",
            f"Прочитал «{filename}»: {n} {plural(n, 'фрагмент', 'фрагмента', 'фрагментов')}. "
            "Теперь ищу и в нём, и в базе компании. "
            "Файл хранится только до конца сессии.",
        )

    def drop_upload(self, s: Session) -> Reply:
        if s.upload:
            self.consultant.searcher.drop(f"upload:{s.id}")
            s.upload = ""
        return Reply("upload", "Файл убран, ищу только по базе компании.")
