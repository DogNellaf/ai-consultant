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

Open http://localhost:8000/ for the widget on the server, http://localhost:8000/browser.html for the
mode where the search runs on the visitor's device. Nothing to configure: without a model key the
answers are the found fragments.

The bot needs `TELEGRAM_BOT_TOKEN` in `.env` (see `.env.example`): `docker compose --profile bot up`.

On the site:

```html
<script src="https://consultant.example.com/widget.js" defer></script>
```

## How it answers

1. **Base.** Markdown files in `knowledge/<company>/`, each `## ` section is a fragment, titles in
   front ("Delivery and payment › Pickup"). An uploaded `.txt`, `.md` or `.pdf` (up to 300 KB and 20
   pages) is cut the same way and kept for the session only.
2. **Search.** Hybrid. The local `multilingual-e5-small` model (int8 ONNX, 118 MB, about 10 ms per
   question on a CPU, no API) finds 12 candidates in PostgreSQL with pgvector. Then each candidate gets
   the weighted share of the question's words it contains, rare words weighing more, and the two numbers
   are combined.
3. **Answer or "don't know".** The best fragment must pass both thresholds: meaning ≥ 0.79 and words ≥ 0.40.
   Without a model the answer is the fragment itself, plus the second one when it is almost as good
   ("how much is delivery" gets both the city and the out-of-town price). With a model (GigaChat or any
   OpenAI-compatible API) the words threshold drops to 0.20 and the model writes the answer from the top
   three fragments, replying `НЕ_ЗНАЮ` when they do not have it.
4. **Manager.** "Call a manager", or a phrase like "call me back", starts a short form: name, phone
   (checked and normalized), what to pass on. The lead is saved first, then sent to `MANAGER_CHAT_ID`.
   A Telegram failure does not lose it.

The "how the answer is searched" switch shows every candidate with both numbers, so a client sees why
the consultant answered or refused.

### Why hybrid

e5 similarity alone does not separate "not in the base". On the demo base the weakest question that is
in the base ("Почём медовик?") scored 0.802, and "how much is an iPhone 15 repair" scored 0.812. The
words do separate them: the iPhone question shares only "how much" with the base, and "how much" is in
many price fragments, so it weighs little. The thresholds are tuned on 21 questions in
`knowledge/kolosok/smoke.json` and the eval during development.

The honest cost is a few refusals where the base does have the answer in other words: "Привезёте торт
завтра?" (will you deliver a cake tomorrow) shares too few words with the delivery fragments, so the
consultant offers a manager. With a model on, the lower words threshold lets these through.

## Browser mode

`data-mode="browser"` runs the same search on the visitor's device with transformers.js and the same
ONNX file, so the demo costs nothing and nothing leaves the device. `scripts/export_index.py` writes
`kb-index.json` with the fragments, their vectors, the thresholds and the stop words, and
`widget/kb-search.js` repeats `app/lexical.py` and `app/search.py` step by step. On the 21 test
questions both modes reach the same answer-or-refuse decision; the vectors differ in the third decimal
place because the browser runs a different onnxruntime build. In this mode there is no model, PDF reading
or sending of leads: the widget shows the message the manager would get.

```html
<script src="kb-search.js"></script>
<script src="widget.js" data-mode="browser" data-index="kb-index.json" data-model-path="/models/" defer></script>
```

### Static build

`python scripts/build_static.py dist/` makes a folder any web server can host: the demo bakery page
with the widget open, the index, and `Build/` with transformers.js, the onnxruntime-web WebAssembly and
the model, each with a ready `.gz` for nginx `gzip_static` (163 MB on disk, about 92 MB over the wire).
Nothing is loaded from a CDN. The page needs a CSP with `'wasm-unsafe-eval'` and `worker-src 'self' blob:`.

transformers.js 4.3 skips the tokenizer when `localModelPath` is a full URL, so the widget passes the
model folder as a path from the site root.

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
demo is one container without PostgreSQL. It takes about 480 MB of RAM: the tokenizer of the
multilingual model is about 285 MB, the model about 130 MB. This is how the demo runs on
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
certificates of the Russian Trusted Root CA: download the bundle from Gosuslugi and set
`GIGACHAT_CA_BUNDLE`.

## Data

The demo base is made up. Leads (name, phone, dialog) are kept in PostgreSQL on the client's server, and
usage rows store only a salted hash of the visitor. An uploaded file lives in memory and in the session's
collection and is dropped with the session (1 hour). With GigaChat the questions and fragments stay in
Russia; with the browser mode they stay on the visitor's device.

## Development

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt
python scripts/download_model.py
pytest                                   # 59 tests; the smoke runs on the real model
TEST_DATABASE_URL=postgresql://... pytest tests/test_pgstore.py
ruff check . && ruff format --check .
uvicorn app.api:app --reload             # in-memory store without DATABASE_URL
```

`tests/test_smoke.py` is the acceptance check: 10 questions from the FAQ must find their fragment and 3
off-topic ones must get "don't know".

## Layout

```
app/embed.py      e5 on onnxruntime          app/engine.py     answer, "don't know", lead form
app/kb.py         Markdown → fragments       app/service.py    sessions, limits, queue, uploads
app/lexical.py    word overlap, IDF          app/api.py        widget API (FastAPI)
app/search.py     hybrid search, thresholds  app/bot.py        Telegram bot (aiogram)
app/store.py      pgvector / memory          app/llm.py        GigaChat, OpenAI-compatible
widget/           widget.js, kb-search.js, demo pages        knowledge/kolosok/  the demo base
```
