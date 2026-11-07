# ai-consultant

English · [Русский](README.ru.md)

An AI consultant that answers a company's customers from its price list and FAQ. One engine, two
entry points: a widget that goes on a site with one line, and a Telegram bot. Every answer shows the
fragment it came from. When the base has no answer, the consultant says so instead of making one up and
offers a manager, who gets the lead in Telegram with the whole dialog.

The demo base is Kolosok, a made-up bakery: prices, delivery and payment, frequent questions.

## Quick start

```bash
docker compose up --build
```

Open http://localhost:8000/ for the demo bakery site with the widget. Nothing to configure: without a
model key the answers are the found fragments. With a GigaChat key in `.env` the model writes them.

The bot needs `TELEGRAM_BOT_TOKEN` in `.env` (see `.env.example`): `docker compose --profile bot up`.

On the site:

```html
<script src="https://consultant.example.com/widget.js" defer></script>
```

The widget takes the site's colours from custom properties on the page (`--consultant-accent`,
`--consultant-accent-text`, `--consultant-font`). The conversation stays when the visitor moves to
another page of the site, until the tab is closed. Buttons on the page can open it or ask a question:
`AiConsultant.open()`, `AiConsultant.ask("...")`.

### The demo site

`widget/` holds the made-up Kolosok bakery: home, about, menu, delivery and address. It is built on
the [Business Casual](https://github.com/StartBootstrap/startbootstrap-business-casual) template by
Start Bootstrap (MIT) with Bootstrap 5.2.3, the Lora and Raleway fonts (OFL) are served from the
site, and the photos come from Wikimedia Commons under CC0 and CC BY 2.0 (authors on
`credits.html`). Every price, hour and rule on the pages is taken from `knowledge/kolosok/`, so the
site and the consultant never disagree.

## How it answers

1. **Base.** Markdown files in `knowledge/<company>/`, each `## ` section is a fragment, titles in
   front ("Delivery and payment › Pickup"). An uploaded `.txt`, `.md` or `.pdf` (up to 300 KB and 20
   pages) is cut the same way and kept for the session only.
2. **Search.** No neural model and nothing to download. Each fragment gets two numbers: the share of
   the question's words it has, rare words weighing more ("медовик" is in one fragment, "стоит" in
   many), and the share of the question's character 4-grams, which survive changed endings and typos.
   The score is words plus half the 4-grams. The base is scored whole in about a millisecond.
3. **Answer or "don't know".** With a model (GigaChat or any OpenAI-compatible API) the five best
   fragments go to it, numbered, whenever the best one scores 0.25; the model writes the answer, names
   the fragments it used (they are shown under the answer) and replies `НЕ_ЗНАЮ` when they do not have
   it. A question that shares nothing with the base never reaches the model. Without a model the best
   fragment is the answer when it has 60 % of the question's words, or 40 % of them and 30 % of the
   4-grams, plus the second fragment when it is almost as good ("how much is delivery" gets both the
   city and the out-of-town price).
4. **Manager.** "Call a manager", or a phrase like "call me back", starts a short form: name, phone
   (checked and normalized), what to pass on. The lead is saved first, then sent to `MANAGER_CHAT_ID`.
   A Telegram failure does not lose it.

The "how the answer is searched" switch shows every candidate with both numbers, so a client sees why
the consultant answered or refused.

### Why no neural model

Up to version 0.3 the search ran `multilingual-e5-small` on onnxruntime, and the container took about
480 MB of memory, most of it the multilingual tokenizer. On a small base the words and their pieces
rank the right fragment first just as well: all 16 questions from the base in
`knowledge/kolosok/smoke.json` find their fragment first, and all 7 off-topic ones get "don't know"
without a model. What a neural search did better was a paraphrase with few shared words ("Вы работаете
в воскресенье?" for the opening hours): the search still ranks it first, but cannot vouch for it
alone, so without a model it gets "don't know", and with one the model answers it. Such questions are
marked `needs_model` in the smoke file.

## Limits

| Setting | Default | What happens |
|---|---|---|
| `MESSAGES_PER_DAY` | 10 | questions per visitor a day (IP or Telegram id, salted hash), then a polite stop with the manager button; the lead form stays open |
| `DAILY_TOKEN_BUDGET` | 200 000 | the model is switched off for the rest of the day, answers come from the fragments |
| `LLM_CONCURRENCY` | 1 | model calls wait in a queue; GigaChat gives individuals one stream |
| `QUEUE_MAX` | 20 | more waiting and the visitor is asked to repeat in a minute |

## Public demo

`DEMO_LEADS=1` is for a demo open to anyone: the lead form runs to the end, but the lead is neither
saved nor sent, and the visitor sees the message the manager would get. Strangers' names and phones are
not kept anywhere. With an empty `DATABASE_URL` the base, sessions and uploads live in memory, so the
demo is one container without PostgreSQL. It takes about 40 MB of memory and starts in a few
seconds. This is how the demo runs on
[dognellaf.com](https://dognellaf.com/case/ai-consultant/).

```bash
docker build -t ai-consultant .
docker run -d -p 8000:8000 -e DEMO_LEADS=1 -e QUOTA_SALT=$(openssl rand -hex 16) ai-consultant
```

## Models

`LLM_PROVIDER=none` (default), `gigachat` or `openai`. The provider is behind one `complete()` call
(`app/llm.py`), switching is a change in `.env`.

GigaChat terms matter here: the freemium for individuals (365M tokens a year) is for personal
non-commercial use only. A consultant on a client's site needs a paid package (from 1,300 ₽ a month for
20M GigaChat 2 Lite tokens for individuals) or the client's own company contract. GigaChat uses
certificates of the Russian Trusted Root CA; the repository carries it in `certs/` and uses it by
default (`GIGACHAT_CA_BUNDLE` points elsewhere if needed). A question with five fragments costs about
1 500–2 000 tokens.

## Data

The demo base is made up. Leads (name, phone, dialog) are kept in PostgreSQL on the client's server, and
usage rows store only a salted hash of the visitor. An uploaded file lives in memory and in the session's
collection and is dropped with the session (1 hour). With GigaChat the questions and fragments stay in
Russia; without a model nothing leaves the server.

## Development

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt
pytest                                   # the smoke runs on the real base and thresholds
TEST_DATABASE_URL=postgresql://... pytest tests/test_pgstore.py
ruff check . && ruff format --check .
uvicorn app.api:app --reload             # in-memory store without DATABASE_URL
```

`tests/test_smoke.py` is the acceptance check: 16 questions from the base must find their fragment
first, 12 of them must be answered without a model, and 7 off-topic ones must get "don't know".

## Layout

```
app/kb.py         Markdown → fragments       app/engine.py     answer, "don't know", lead form
app/lexical.py    word overlap, IDF          app/service.py    sessions, limits, queue, uploads
app/grams.py      character 4-grams          app/api.py        widget API (FastAPI)
app/search.py     search, thresholds         app/bot.py        Telegram bot (aiogram)
app/store.py      leads, usage: PostgreSQL / memory          app/llm.py  GigaChat, OpenAI-compatible
widget/           widget.js, demo pages      knowledge/kolosok/  the demo base
```
