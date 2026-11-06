# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-11-06

### Added

- `DEMO_LEADS=1` for a public demo: the lead form runs to the end, but the lead is neither saved nor
  sent, the visitor sees the message the manager would get.

### Changed

- The demo page at `/` is the bakery site with the chat open, in the same look as the static build.
- The API takes about 480 MB of RAM instead of 800 MB: onnxruntime runs without its memory arena and
  the base is indexed eight fragments at a time.

## [0.1.0] - 2026-11-06

### Added

- Hybrid search over a Markdown knowledge base: the local multilingual-e5-small model (int8 ONNX) in
  PostgreSQL with pgvector plus a weighted word overlap, thresholds for an honest "don't know".
- Answers from the found fragment, or written by GigaChat or an OpenAI-compatible model from the top
  fragments, with the sources under the answer and the "how the answer is searched" switch.
- A lead form (name, phone, what to pass on) that saves the lead and sends it to the manager's
  Telegram chat with the dialog.
- The visitor's own .txt, .md or .pdf to ask about, kept for the session only.
- Limits: questions per visitor a day, a daily token budget that switches the model off, a queue of
  one for model calls.
- A widget for any site in one line, with a browser mode that runs the same search on the visitor's
  device (transformers.js), and a Telegram bot on the same engine.
- A static build of the browser mode (`scripts/build_static.py`) with precompressed files and no CDN.
- The made-up Kolosok bakery base and the acceptance smoke: 10 FAQ questions with their sources,
  3 off-topic questions with "don't know".
