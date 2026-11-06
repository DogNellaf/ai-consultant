"""The consultant: one engine for the site widget and the Telegram bot.

A question goes through the hybrid search. Without a model the answer is the found fragment
itself; with a model it is written from the top fragments, and the model must say НЕ_ЗНАЮ when
they have no answer. Either way a weak match gets an honest "don't know" and an offer to pass
the question to a manager, who then gets a lead with the whole dialog.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from . import config
from .llm import LLM, SYSTEM, UNKNOWN, LLMError, fragments_block
from .notify import lead_text
from .search import Hit, Searcher, confident, shown_sources
from .store import Lead

log = logging.getLogger(__name__)

MANAGER = "Позвать менеджера"
CANCEL = "Отмена"
KEEP = "Оставить как есть"
EXAMPLES = ["Сколько стоит доставка?", "За сколько дней заказать торт?", "Есть что-нибудь без глютена?"]

HANDOFF = re.compile(
    r"менеджер|оператор|живо\w* человек|перезвон|позвоните|свяж\w*ся|заказать звонок|оформить заказ",
    re.IGNORECASE,
)
PHONE_CHARS = re.compile(r"[\s()\-.]")


@dataclass
class Reply:
    kind: str  # greeting | answer | unknown | lead | lead_done | limit | busy | upload | error
    text: str
    sources: list[dict] = field(default_factory=list)
    search: list[dict] = field(default_factory=list)  # every fragment the search looked at, for "how it searched"
    buttons: list[str] = field(default_factory=list)
    mode: str = ""  # "fragments" or the model name
    tokens: int = 0
    counted: bool = False  # took one of the visitor's daily messages
    lead_id: int | None = None
    manager_preview: str = ""  # DEMO_LEADS: what the manager would get in Telegram

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d.pop("counted")
        return d


@dataclass
class LeadForm:
    step: str = "name"  # name -> phone -> summary
    name: str = ""
    phone: str = ""
    question: str = ""


@dataclass
class Session:
    id: str
    channel: str  # "widget" or "telegram"
    history: list[dict] = field(default_factory=list)  # {"role": "user"|"assistant", "content": ...}
    lead: LeadForm | None = None
    upload: str = ""  # file name, its fragments live in the "upload:<id>" collection
    last_question: str = ""

    @property
    def collections(self) -> list[str]:
        return ["kb", f"upload:{self.id}"] if self.upload else ["kb"]


def wants_manager(text: str) -> bool:
    return text == MANAGER or bool(HANDOFF.search(text))


def normalize_phone(text: str) -> str | None:
    digits = PHONE_CHARS.sub("", text.strip())
    if digits.startswith("+"):
        rest = digits[1:]
        return digits if rest.isdigit() and 10 <= len(rest) <= 15 else None
    if not digits.isdigit():
        return None
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10 and digits[0] == "9":
        return "+7" + digits
    return None


class Consultant:
    def __init__(self, searcher: Searcher, store, llm: LLM | None = None, notify=None):
        self.searcher = searcher
        self.store = store
        self.llm = llm
        self.notify = notify or (lambda lead: False)
        self.demo_leads = 0

    def greeting(self) -> Reply:
        return Reply(
            "greeting",
            f"Здравствуйте! {config.COMPANY} на связи, я ИИ-консультант: отвечаю по прайсу, доставке и частым "
            "вопросам, а под ответом показываю, откуда взял. Можно прислать свой текст или PDF и спросить по нему.",
            buttons=EXAMPLES + [MANAGER],
        )

    # one message from the visitor -----------------------------------------------------------

    def handle(self, s: Session, text: str, use_model: bool = True) -> Reply:
        text = text.strip()
        if s.lead:
            reply = self._lead_step(s, text)
        elif wants_manager(text):
            reply = self._lead_start(s, text)
        else:
            reply = self._answer(s, text, use_model)
        s.history.append({"role": "user", "content": text})
        s.history.append({"role": "assistant", "content": reply.text})
        del s.history[:-20]
        return reply

    def _answer(self, s: Session, question: str, use_model: bool) -> Reply:
        s.last_question = question
        hits = self.searcher.search(question, s.collections)
        search = [h.as_dict() for h in hits]
        best = hits[0] if hits else None
        model = self.llm if use_model else None

        if model and confident(best, with_model=True):
            try:
                return self._model_answer(s, question, hits, model, search)
            except LLMError as e:
                log.warning("model failed, answering from fragments: %s", e)
        if confident(best, with_model=False):
            shown = shown_sources(hits)
            return Reply(
                "answer",
                "\n\n".join(h.chunk.text for h in shown),
                sources=[h.as_dict() for h in shown],
                search=search,
                mode="fragments",
                counted=True,
            )
        return self._unknown(search, counted=True)

    def _model_answer(self, s: Session, question: str, hits: list[Hit], model: LLM, search: list[dict]) -> Reply:
        system = SYSTEM.format(company=config.COMPANY, fragments=fragments_block(hits))
        messages = [m for m in s.history[-6:]] + [{"role": "user", "content": question}]
        done = model.complete(system, messages)
        if UNKNOWN in done.text or not done.text:
            reply = self._unknown(search, counted=True)
        else:
            shown = shown_sources(hits)
            reply = Reply("answer", done.text, sources=[h.as_dict() for h in shown], search=search, counted=True)
        reply.mode, reply.tokens = model.name, done.tokens
        return reply

    def _unknown(self, search: list[dict], counted: bool) -> Reply:
        return Reply(
            "unknown",
            "В базе знаний нет ответа на этот вопрос, гадать не буду. Могу передать его менеджеру: "
            "он перезвонит и ответит.",
            search=search,
            buttons=[MANAGER],
            mode="fragments",
            counted=counted,
        )

    # lead form ---------------------------------------------------------------------------------

    def _lead_start(self, s: Session, text: str) -> Reply:
        question = s.last_question if text == MANAGER else text
        s.lead = LeadForm(question=question)
        return Reply(
            "lead",
            "Передам вопрос менеджеру вместе с нашей перепиской. Как к вам обращаться?",
            buttons=[CANCEL],
        )

    def _lead_step(self, s: Session, text: str) -> Reply:
        form = s.lead
        if text == CANCEL or text.lower() in ("отмена", "/cancel"):
            s.lead = None
            return Reply("answer", "Хорошо, не передаю. Спрашивайте дальше.", buttons=EXAMPLES)
        if form.step == "name":
            if not (2 <= len(text) <= 60) or any(ch.isdigit() for ch in text):
                return Reply("lead", "Напишите, пожалуйста, имя, без цифр.", buttons=[CANCEL])
            form.name, form.step = text, "phone"
            return Reply(
                "lead",
                f"{text}, оставьте телефон для связи, например +7 900 123-45-67. "
                "Он нужен только менеджеру, чтобы перезвонить.",
                buttons=[CANCEL],
            )
        if form.step == "phone":
            phone = normalize_phone(text)
            if not phone:
                return Reply("lead", "Не похоже на номер. Например: +7 900 123-45-67.", buttons=[CANCEL])
            form.phone, form.step = phone, "summary"
            if form.question:
                return Reply(
                    "lead",
                    f"Что передать менеджеру? Можно оставить ваш вопрос: «{form.question}».",
                    buttons=[KEEP, CANCEL],
                )
            return Reply("lead", "Что передать менеджеру? Пара слов о вопросе или заказе.", buttons=[CANCEL])
        summary = form.question if text == KEEP and form.question else text
        if not summary:
            return Reply("lead", "Напишите пару слов о вопросе.", buttons=[CANCEL])
        lead = Lead(form.name, form.phone, summary, s.channel, history=list(s.history))
        if config.DEMO_LEADS:
            self.demo_leads += 1
            lead.id = self.demo_leads
            s.lead = None
            return Reply(
                "lead_done",
                f"Готово, заявка №{lead.id}. Это демо: заявка никуда не ушла, "
                "ниже то, что менеджер получил бы в Telegram.",
                buttons=EXAMPLES,
                lead_id=lead.id,
                manager_preview=lead_text(lead, html=False),
            )
        lead_id = self.store.save_lead(lead)
        sent = False
        try:
            sent = bool(self.notify(lead))
        except Exception:  # the lead is saved, a Telegram hiccup must not lose the visitor's reply
            log.exception("lead %s: notification failed", lead_id)
        s.lead = None
        if sent:
            tail = f"Менеджер уже получил её и перезвонит на {form.phone}."
        else:
            tail = f"Она сохранена, менеджер перезвонит на {form.phone}."
        return Reply(
            "lead_done",
            f"Готово, заявка №{lead_id}. {tail}",
            buttons=EXAMPLES,
            lead_id=lead_id,
        )
