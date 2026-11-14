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
from contextlib import asynccontextmanager
from datetime import date

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


def expired_reply() -> Reply:
    return Reply(
        "session_expired",
        "Сессия завершилась. Новые данные не обработаны. "
        "Начните новый диалог; незавершённую заявку нужно заполнить заново.",
        buttons=["Начать новый диалог"],
    )


class Service:
    def __init__(self, consultant: Consultant):
        self.consultant = consultant
        self.store = consultant.store
        self.sessions: dict[str, tuple[Session, float]] = {}
        self._deleting: dict[str, Session] = {}
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

    def resolve(self, session_id: str | None, channel: str) -> Session | None:
        """An HTTP client's stale token must never silently become a new conversation."""
        self._expire()
        if session_id and session_id not in self.sessions:
            return None
        return self.session(session_id, channel)

    def _expire(self) -> None:
        now = time.time()
        for sid, (_s, seen) in list(self.sessions.items()):
            if not _s.operation.locked() and now - seen > config.SESSION_TTL:
                self.forget(sid)

    def forget(self, session_id: str | None) -> Session | None:
        entry = self.sessions.pop(session_id, None)
        s = entry[0] if entry else self._deleting.get(session_id)
        if s is not None:
            s.expired = True
            # Invalidate immediately; the operation's finally block removes any late writes.
            if s.operation.locked():
                self._deleting[s.id] = s
            else:
                self._clear(s)
            return s
        return None

    def _clear(self, s: Session) -> None:
        self.consultant.searcher.drop(f"upload:{s.id}")
        s.history.clear()
        s.lead = None
        s.upload = ""
        s.last_question = ""
        s.completed_lead_text, s.completed_lead = "", None
        if self._deleting.get(s.id) is s:
            del self._deleting[s.id]

    async def delete(self, session_id: str | None) -> None:
        s = self.forget(session_id)
        if s is not None:
            # Acknowledging deletion waits for workers, including indexing, to finish.
            async with s.operation:
                self._clear(s)

    @asynccontextmanager
    async def _operation(self, s: Session):
        async with s.operation:
            try:
                yield
            finally:
                if s.expired:
                    self._clear(s)
                elif s.id in self.sessions:
                    self.sessions[s.id] = (s, time.time())

    @staticmethod
    async def _thread(fn, *args):
        # Cancelling the HTTP task must not release the session lock while its worker writes.
        worker = asyncio.create_task(asyncio.to_thread(fn, *args))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            try:
                await worker
            finally:
                raise

    async def cleanup(self) -> None:
        while True:
            await asyncio.sleep(max(1, min(config.SESSION_TTL, 60)))
            self._expire()

    # questions ---------------------------------------------------------------------------------

    def remaining(self, visitor: str) -> int:
        return max(0, config.MESSAGES_PER_DAY - self.store.messages_today(visitor))

    async def ask(self, s: Session, visitor: str, text: str) -> Reply:
        async with self._operation(s):
            if s.expired:
                return expired_reply()
            reply = await self._ask(s, visitor, text)
            return expired_reply() if s.expired else reply

    async def _ask(self, s: Session, visitor: str, text: str) -> Reply:
        text = (text or "").strip()[:1000]
        if not text:
            return self.consultant.greeting()
        if s.lead is None and s.completed_lead is not None and text == s.completed_lead_text:
            return s.completed_lead
        # the lead form, and the request that starts it, stay open after the limit: the limit
        # message itself offers the manager
        question = s.lead is None and not wants_manager(text)
        day = date.today()
        reserved = question and self.store.reserve_message(visitor, config.MESSAGES_PER_DAY, day)
        if question and not reserved:
            return Reply(
                "limit",
                f"На сегодня лимит демо исчерпан: {config.MESSAGES_PER_DAY} вопросов в сутки. "
                "Возвращайтесь завтра или оставьте заявку менеджеру.",
                buttons=[MANAGER],
            )
        try:
            if question and self.consultant.llm is not None:
                if self._waiting >= config.QUEUE_MAX:
                    return Reply("busy", "Сейчас много вопросов, повторите через минуту.", buttons=EXAMPLES)
                self._waiting += 1
                try:
                    async with self._sem:
                        if s.expired:
                            return expired_reply()
                        use_model = self.store.tokens_today() < config.DAILY_TOKEN_BUDGET
                        reply = await self._thread(self.consultant.handle, s, text, use_model)
                        # Record tokens before releasing the model slot: the next waiter sees them.
                        if reply.tokens:
                            self.store.add_usage(visitor, 0, reply.tokens, day=day)
                finally:
                    self._waiting -= 1
            else:
                reply = await self._thread(self.consultant.handle, s, text, False)
            if reply.counted:
                reserved = False  # the reservation is now the completed question
            return reply
        finally:
            if reserved:
                self.store.add_usage(visitor, -1, 0, day=day)

    # uploads -----------------------------------------------------------------------------------

    async def upload(self, s: Session, filename: str, data: bytes) -> Reply:
        async with self._operation(s):
            if s.expired:
                return expired_reply()
            reply = await self._upload(s, filename, data)
            return expired_reply() if s.expired else reply

    async def _upload(self, s: Session, filename: str, data: bytes) -> Reply:
        try:
            text = extract_text(filename, data)
        except UploadError as e:
            return Reply("error", str(e))
        chunks = to_chunks(filename, text, s.id)
        if not chunks:
            return Reply(
                "error",
                "В файле нет текста для поиска. Добавьте текст под заголовками и повторите загрузку."
                + (" Предыдущий файл сохранён." if s.upload else ""),
            )
        n = await self._thread(self.consultant.searcher.index, f"upload:{s.id}", chunks)
        if s.expired:
            return expired_reply()
        s.upload = filename
        return Reply(
            "upload",
            f"Прочитал «{filename}»: {n} {plural(n, 'фрагмент', 'фрагмента', 'фрагментов')}. "
            "Теперь ищу и в нём, и в базе компании. "
            "Файл хранится только до конца сессии.",
        )

    async def drop_upload(self, s: Session) -> Reply:
        async with self._operation(s):
            if s.expired:
                return expired_reply()
            if s.upload:
                self.consultant.searcher.drop(f"upload:{s.id}")
                s.upload = ""
            return Reply("upload", "Файл убран, ищу только по базе компании.")
