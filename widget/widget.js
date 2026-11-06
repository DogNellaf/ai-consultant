/* AI consultant widget. One line on any site:
 *
 *   <script src="https://consultant.example.com/widget.js" defer></script>
 *
 * Options as data- attributes of the script tag:
 *   data-title       header title (default: the company from the server)
 *   data-target      CSS selector to mount inline instead of the floating button
 *   data-open        "1" opens the chat at once, except on a phone where it would cover the page
 *   data-mode        "api" (default) asks the server; "browser" searches on the visitor's device
 *                    with transformers.js and answers with the found fragment, nothing is sent
 *   data-index       browser mode: kb-index.json (scripts/export_index.py)
 *   data-model-path  browser mode: folder with multilingual-e5-small/ (default: Hugging Face)
 *   data-wasm-path   browser mode: onnxruntime-web .wasm folder (default: CDN)
 *   data-transformers browser mode: transformers.min.js URL
 *
 * Without a server the lead form still works: the widget shows the message the manager would
 * get in Telegram instead of sending it.
 *
 * Colours and font follow the site through custom properties on the page:
 *   :root { --consultant-accent: #2f170f; --consultant-accent-text: #fff; --consultant-font: ...; }
 *
 * window.AiConsultant: open(), ask(text) and forget(), which drops the saved conversation.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var ds = script ? script.dataset : {};
  var base = script ? new URL(".", script.src).href : "/";
  var MODE = ds.mode || "api";
  var MANAGER = "Позвать менеджера", CANCEL = "Отмена", KEEP = "Оставить как есть";
  var EXAMPLES = ["Сколько стоит доставка?", "За сколько дней заказать торт?", "Есть что-нибудь без глютена?"];
  var HANDOFF = /менеджер|оператор|живо[а-яё]* человек|перезвон|позвоните|свяж[а-яё]*ся|заказать звонок|оформить заказ/i;

  /* data- paths are relative to the page; transformers.js and onnxruntime resolve their own
   * paths against their script, so they are made absolute first. The model folder is the
   * exception: with a full URL as localModelPath transformers.js 4.3 skips the tokenizer
   * ("this.tokenizer is not a function"), so it gets a path from the site root. */
  function abs(url) {
    return url ? new URL(url, document.baseURI).href : url;
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  /* ---------------------------------------------------------------- engines */

  function apiEngine(saved) {
    var sessionId = saved || null;
    async function post(path, body, isForm) {
      var r = await fetch(base + path.replace(/^\//, ""), {
        method: "POST",
        headers: isForm ? undefined : { "Content-Type": "application/json" },
        body: isForm ? body : JSON.stringify(body),
      });
      var data = await r.json();
      sessionId = data.session_id || sessionId;
      return data;
    }
    return {
      ready: Promise.resolve(),
      greet: function () { return post("api/chat", { session_id: sessionId, text: "" }); },
      ask: function (text) { return post("api/chat", { session_id: sessionId, text: text }); },
      upload: function (file) {
        var f = new FormData();
        f.append("file", file);
        f.append("session_id", sessionId || "");
        return post("api/upload", f, true);
      },
      dropUpload: function () { return post("api/upload/delete", { session_id: sessionId }); },
      session: function () { return sessionId; },
      accept: ".txt,.md,.pdf",
    };
  }

  /* browser mode: the same steps as app/engine.py, on kb-search.js */
  function browserEngine(onProgress) {
    var kb = null, company = ds.title || "";
    var history = [], lead = null, lastQuestion = "", upload = "", leads = 0;
    var ready = (async function () {
      var index = await (await fetch(abs(ds.index))).json();
      company = ds.title || index.company;
      var embed = await window.KbSearch.loadEmbedder({
        transformers: abs(ds.transformers) || "https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.3.1/dist/transformers.min.js",
        modelPath: ds.modelPath && new URL(ds.modelPath, document.baseURI).pathname, wasmPaths: abs(ds.wasmPath), onProgress: onProgress,
      });
      kb = window.KbSearch.create(index, embed);
    })();

    function reply(kind, text, extra) {
      var r = { kind: kind, text: text, sources: [], search: [], buttons: [], mode: "fragments", upload: upload };
      for (var k in extra || {}) r[k] = extra[k];
      return r;
    }
    function hitDict(h) {
      return { source: h.chunk.source, title: h.chunk.title, text: h.chunk.text,
        dense: Math.round(h.dense * 1000) / 1000, lexical: Math.round(h.lexical * 100) / 100, score: Math.round(h.score * 1000) / 1000 };
    }
    function phone(text) {
      var d = text.trim().replace(/[\s().-]/g, "");
      if (d[0] === "+") return /^\+\d{10,15}$/.test(d) ? d : null;
      if (!/^\d+$/.test(d)) return null;
      if (d.length === 11 && "78".indexOf(d[0]) >= 0) return "+7" + d.slice(1);
      if (d.length === 10 && d[0] === "9") return "+7" + d;
      return null;
    }
    function managerText(l) {
      var lines = ["Заявка №" + l.id + " · виджет на сайте", "Имя: " + l.name, "Телефон: " + l.phone, "Вопрос: " + l.summary];
      var dialog = history.filter(function (m) { return m.content; }).slice(-12);
      if (dialog.length) {
        lines.push("", "Переписка");
        dialog.forEach(function (m) { lines.push((m.role === "user" ? "Клиент" : "Бот") + ": " + m.content.slice(0, 400)); });
      }
      return lines.join("\n");
    }
    function leadStep(text) {
      if (text === CANCEL || /^(отмена|\/cancel)$/i.test(text)) {
        lead = null;
        return reply("answer", "Хорошо, не передаю. Спрашивайте дальше.", { buttons: EXAMPLES });
      }
      if (lead.step === "name") {
        if (text.length < 2 || text.length > 60 || /\d/.test(text)) return reply("lead", "Напишите, пожалуйста, имя, без цифр.", { buttons: [CANCEL] });
        lead.name = text; lead.step = "phone";
        return reply("lead", text + ", оставьте телефон для связи, например +7 900 123-45-67. Он нужен только менеджеру, чтобы перезвонить.", { buttons: [CANCEL] });
      }
      if (lead.step === "phone") {
        var p = phone(text);
        if (!p) return reply("lead", "Не похоже на номер. Например: +7 900 123-45-67.", { buttons: [CANCEL] });
        lead.phone = p; lead.step = "summary";
        if (lead.question) return reply("lead", "Что передать менеджеру? Можно оставить ваш вопрос: «" + lead.question + "».", { buttons: [KEEP, CANCEL] });
        return reply("lead", "Что передать менеджеру? Пара слов о вопросе или заказе.", { buttons: [CANCEL] });
      }
      var summary = text === KEEP && lead.question ? lead.question : text;
      if (!summary) return reply("lead", "Напишите пару слов о вопросе.", { buttons: [CANCEL] });
      var l = { id: ++leads, name: lead.name, phone: lead.phone, summary: summary };
      var preview = managerText(l);
      lead = null;
      return reply("lead_done", "Готово, заявка №" + l.id + ". Это демо: заявка никуда не ушла, ниже то, что менеджер получил бы в Telegram.",
        { buttons: EXAMPLES, lead_id: l.id, manager_preview: preview });
    }
    async function answer(q) {
      lastQuestion = q;
      var hits = await kb.search(q);
      var search = hits.map(hitDict);
      if (kb.confident(hits[0])) {
        var shown = kb.shownSources(hits);
        return reply("answer", shown.map(function (h) { return h.chunk.text; }).join("\n\n"), { sources: shown.map(hitDict), search: search });
      }
      return reply("unknown", "В базе знаний нет ответа на этот вопрос, гадать не буду. Могу передать его менеджеру: он перезвонит и ответит.",
        { search: search, buttons: [MANAGER] });
    }
    async function ask(text) {
      text = (text || "").trim().slice(0, 1000);
      await ready;
      var r;
      if (lead) r = leadStep(text);
      else if (text === MANAGER || HANDOFF.test(text)) {
        lead = { step: "name", question: text === MANAGER ? lastQuestion : text };
        r = reply("lead", "Передам вопрос менеджеру вместе с нашей перепиской. Как к вам обращаться?", { buttons: [CANCEL] });
      } else r = await answer(text);
      history.push({ role: "user", content: text }, { role: "assistant", content: r.text });
      history = history.slice(-20);
      return r;
    }
    return {
      ready: ready,
      greet: async function () {
        await ready;
        return reply("greeting", "Здравствуйте! " + company + " на связи, я ИИ-консультант: отвечаю по прайсу, доставке и частым вопросам, " +
          "а под ответом показываю, откуда взял. Можно прислать свой текст и спросить по нему.", { buttons: EXAMPLES.concat([MANAGER]) });
      },
      ask: ask,
      upload: async function (file) {
        await ready;
        if (file.size > 300000) return reply("error", "Файл больше 300 КБ, пришлите поменьше.");
        if (!/\.(txt|md)$/i.test(file.name)) return reply("error", "В демо без сервера подойдёт .txt или .md, PDF читает серверная версия.");
        var text = (await file.text()).trim().slice(0, 30000);
        if (!text) return reply("error", "В файле нет текста. Если это скан, его сначала нужно распознать.");
        var n = await kb.addText(file.name, text);
        upload = file.name;
        return reply("upload", "Прочитал «" + file.name + "»: " + n + " " + plural(n, "фрагмент", "фрагмента", "фрагментов") +
          ". Теперь ищу и в нём, и в базе компании. Файл остаётся только в этой вкладке.", { upload: upload });
      },
      dropUpload: async function () {
        kb.dropText(); upload = "";
        return reply("upload", "Файл убран, ищу только по базе компании.", { upload: "" });
      },
      accept: ".txt,.md",
    };
  }

  function plural(n, one, few, many) {
    if (n % 10 === 1 && n % 100 !== 11) return one;
    if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14)) return few;
    return many;
  }

  /* -------------------------------------------------------------------- UI */

  /* Icons from Lucide (ISC license, lucide.dev), 24×24 stroke paths */
  var ICONS = {
    chat: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
    bot: '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
    close: '<path d="m6 9 6 6 6-6"/>',
    x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    clip: '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
    send: '<path d="M3.714 3.048a.498.498 0 0 0-.683.627l2.843 7.627a2 2 0 0 1 0 1.396l-2.842 7.627a.498.498 0 0 0 .682.627l18-8.5a.5.5 0 0 0 0-.904z"/><path d="M6 12h16"/>',
    file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    chevron: '<path d="m6 9 6 6 6-6"/>',
  };
  function icon(name, cls) {
    var span = document.createElement("span");
    span.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"' + (cls ? ' class="' + cls + '"' : "") + ">" + ICONS[name] + "</svg>";
    return span.firstChild;
  }
  function iconButton(name, cls, label) {
    var b = el("button", cls);
    b.type = "button";
    b.setAttribute("aria-label", label);
    b.title = label;
    b.append(icon(name));
    return b;
  }

  /* The conversation survives moving between pages of the site: the server keeps the session,
   * the tab keeps what was shown (sessionStorage, gone with the tab). Browser mode keeps its
   * state in memory, so there a new page starts a new chat. */
  var STORE_KEY = "ai-consultant:" + base;
  function loadState() {
    try { return JSON.parse(sessionStorage.getItem(STORE_KEY)) || null; } catch (e) { return null; }
  }
  function saveState(state) {
    try { sessionStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) { /* storage off */ }
  }
  function forget() {
    try { sessionStorage.removeItem(STORE_KEY); } catch (e) { /* storage off */ }
  }

  function mount() {
    var target = ds.target ? document.querySelector(ds.target) : null;
    var host = el("div", "aic-host");
    (target || document.body).appendChild(host);
    var root = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;
    var css = el("link");
    css.rel = "stylesheet";
    css.href = ds.css || base + "widget.css";
    root.appendChild(css);

    var wrap = el("div", "aic" + (target ? " aic-inline" : ""));
    var fab = el("button", "aic-fab");
    fab.type = "button";
    fab.setAttribute("aria-label", "Открыть консультанта");
    fab.append(icon("chat"));
    var panel = el("section", "aic-panel");
    panel.setAttribute("aria-label", "ИИ-консультант");

    var head = el("header", "aic-head");
    var avatar = el("div", "aic-avatar");
    avatar.append(icon("bot"));
    var title = el("div", "aic-title", ds.title || "Консультант");
    var status = el("div", "aic-status", MODE === "browser" ? "поиск на вашем устройстве" : "онлайн, отвечает сразу");
    var titles = el("div", "aic-titles");
    titles.append(title, status);
    var how = iconButton("search", "aic-icon-btn aic-how", "Как ищется ответ");
    how.setAttribute("aria-pressed", "false");
    var close = iconButton("close", "aic-icon-btn aic-close", "Свернуть");
    head.append(avatar, titles, how);
    if (!target) head.append(close);

    var log = el("div", "aic-log");
    log.setAttribute("role", "log");
    log.setAttribute("aria-live", "polite");
    var chips = el("div", "aic-chips");
    var fileBar = el("div", "aic-file");
    fileBar.hidden = true;
    var form = el("form", "aic-form");
    var attach = iconButton("clip", "aic-icon-btn aic-attach", "Прислать свой текст или PDF");
    var file = el("input");
    file.type = "file";
    file.hidden = true;
    var input = el("input", "aic-input");
    input.placeholder = "Напишите вопрос…";
    input.maxLength = 1000;
    input.setAttribute("aria-label", "Ваш вопрос");
    var send = el("button", "aic-send");
    send.type = "submit";
    send.setAttribute("aria-label", "Отправить");
    send.append(icon("send"));
    var remaining = el("div", "aic-remaining");
    form.append(attach, file, input, send);
    panel.append(head, log, chips, fileBar, form, remaining);
    wrap.append(panel);
    if (!target) wrap.append(fab);
    root.appendChild(wrap);

    var engine, started = false;
    var keep = MODE !== "browser";
    var state = { session: null, open: false, items: [] };

    function persist() {
      if (!keep) return;
      state.session = engine && engine.session ? engine.session() : state.session;
      state.items = state.items.slice(-60);
      saveState(state);
    }

    function scroll() { log.scrollTop = log.scrollHeight; }

    function bubble(role, text) {
      var b = el("div", "aic-msg aic-" + role);
      if (text != null) b.append(el("div", "aic-text", text));
      log.append(b);
      scroll();
      return b;
    }

    function userBubble(text) {
      bubble("user", text);
      state.items.push({ user: text });
    }

    function render(r) {
      state.items.push({ bot: r });
      var b = bubble("bot", r.text);
      b.classList.add("aic-" + r.kind);
      if (r.mode && r.mode !== "fragments" && r.kind === "answer") b.append(el("div", "aic-meta", "ответ написала модель " + r.mode + " по фрагментам"));
      (r.sources || []).forEach(function (s) {
        var d = el("details", "aic-source");
        var sum = el("summary");
        sum.append(icon("file"), el("span", null, s.title), icon("chevron", "aic-chev"));
        d.append(sum, el("p", null, s.text));
        b.append(d);
      });
      if (r.manager_preview) b.append(el("pre", "aic-preview", r.manager_preview));
      if (r.search && r.search.length) {
        var t = el("div", "aic-search");
        t.append(el("div", "aic-search-head", "Как искался ответ: " + (r.kind === "unknown" ? "ни один фрагмент не прошёл порог" : "лучший фрагмент прошёл порог")));
        r.search.forEach(function (h, i) {
          var row = el("div", "aic-hit");
          row.append(el("span", "aic-hit-n", String(i + 1)), el("span", "aic-hit-t", h.title),
            el("span", "aic-hit-s", "смысл " + h.dense.toFixed(3) + " · слова " + h.lexical.toFixed(2)));
          t.append(row);
        });
        b.append(t);
      }
      chips.textContent = "";
      (r.buttons || []).forEach(function (label) {
        var c = el("button", "aic-chip", label);
        c.type = "button";
        c.addEventListener("click", function () { submit(label); });
        chips.append(c);
      });
      if (typeof r.remaining === "number") remaining.textContent = "Осталось вопросов на сегодня: " + r.remaining;
      if ("upload" in r) {
        fileBar.hidden = !r.upload;
        fileBar.textContent = "";
        if (r.upload) {
          var x = iconButton("x", "aic-icon-btn", "Убрать файл");
          x.addEventListener("click", function () { run(function () { return engine.dropUpload(); }); });
          fileBar.append(icon("file"), el("span", null, r.upload), x);
        }
      }
      scroll();
    }

    // Calls go one after another: a question asked while the greeting loads waits for it
    var queue = Promise.resolve();
    function run(fn) {
      queue = queue.then(function () { return step(fn); });
      return queue;
    }

    async function step(fn) {
      send.disabled = true;
      var wait = bubble("bot aic-typing");
      wait.setAttribute("aria-label", "Консультант печатает");
      wait.append(el("i"), el("i"), el("i"));
      try {
        var r = await fn();
        wait.remove();
        render(r);
      } catch (e) {
        if (window.console) console.error("ai-consultant:", e);
        wait.remove();
        render({ kind: "error", text: "Не получилось ответить, попробуйте ещё раз." });
      } finally {
        send.disabled = false;
        persist();
      }
    }

    function submit(text) {
      text = (text || "").trim();
      if (!text) return;
      userBubble(text);
      input.value = "";
      run(function () { return engine.ask(text); });
    }

    function makeEngine() {
      if (MODE === "browser") {
        var load = bubble("bot", "Загружаю модель поиска на ваше устройство (≈ 120 МБ, один раз)…");
        engine = browserEngine(function (loaded, total) {
          load.firstChild.textContent = "Загружаю модель поиска на ваше устройство: " +
            Math.round(Math.min(loaded, total) / 1048576) + " из " + Math.round(total / 1048576) + " МБ…";
        });
        engine.ready.then(function () { load.remove(); }, function (err) {
          if (window.console) console.error("ai-consultant: model load failed", err);
          load.remove();
          bubble("bot aic-error", "Модель не загрузилась. Обновите страницу или попробуйте с компьютера.");
        });
      } else engine = apiEngine(state.session);
      file.accept = engine.accept;
    }

    function start() {
      if (started) return;
      started = true;
      makeEngine();
      run(function () { return engine.greet(); });
    }

    function restore(saved) {
      state = { session: saved.session, open: !!saved.open, items: [] };
      started = true;
      makeEngine();
      log.classList.add("aic-restored");
      saved.items.forEach(function (it) {
        if (it.user != null) userBubble(it.user);
        else render(it.bot);
      });
      setTimeout(function () { log.classList.remove("aic-restored"); }, 0);
    }

    function setOpen(on) {
      wrap.classList.toggle("aic-open", on);
      state.open = on;
      persist();
      if (on) scroll();
    }
    function open() { setOpen(true); start(); input.focus({ preventScroll: true }); }

    fab.addEventListener("click", open);
    close.addEventListener("click", function () { setOpen(false); });
    how.addEventListener("click", function () {
      var on = !wrap.classList.contains("aic-show-search");
      wrap.classList.toggle("aic-show-search", on);
      how.setAttribute("aria-pressed", String(on));
      scroll();
    });
    form.addEventListener("submit", function (e) { e.preventDefault(); submit(input.value); });
    attach.addEventListener("click", function () { file.click(); });
    file.addEventListener("change", function () {
      var f = file.files[0];
      file.value = "";
      if (!f) return;
      userBubble("📎 " + f.name);
      run(function () { return engine.upload(f); });
    });

    var saved = keep ? loadState() : null;
    if (saved && saved.items && saved.items.length) {
      restore(saved);
      if (saved.open || target) { wrap.classList.add("aic-open"); scroll(); }
    } else if (target || (ds.open === "1" && !window.matchMedia("(max-width: 480px)").matches)) open();
    // ask() from a button on the page: the question goes after the greeting if the chat was closed
    function ask(text) {
      open();
      queue.then(function () { submit(text); });
    }
    return { open: open, ask: ask, forget: forget };
  }

  function boot() { window.AiConsultant = mount(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
