# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2026-11-07

### Fixed

- The image no longer runs `chown -R` over `/app`: it copied the 118 MB model into one more layer, and
  on a small server with swap in use the build hung on it for over 17 minutes. The app only reads
  its files.

## [0.3.0] - 2026-11-07

### Added

- The demo bakery is a site of five pages on the Business Casual template (Start Bootstrap, MIT) with
  photos from Wikimedia Commons; prices, hours and delivery on it come from the knowledge base.
- The conversation stays when the visitor moves to another page, until the tab is closed.
- The widget follows the site's colours and font through `--consultant-*` custom properties, and pages
  can call `AiConsultant.open()` and `AiConsultant.ask()`.

### Changed

- The widget's look: Lucide icons instead of emoji, an avatar with an online mark, a typing indicator,
  a full-screen chat on phones, and `data-open` no longer covers the page on a phone.
- The greeting reads "Пекарня «Колосок» на связи, я ИИ-консультант".
- The static build carries the same site pages in the browser mode.

### Fixed

- A question asked from a page button before the greeting arrived came out above the greeting.

## [0.2.1] - 2026-11-06

### Fixed

- Fragments are embedded one at a time. The model is quantized dynamically, so in a batch a vector
  depended on its neighbours and the padding (up to 0.015 apart); now it does not, and
  `kb-index.json` is rebuilt. The acceptance smoke and the browser mode give the same decisions.

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
