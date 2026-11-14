/* AI consultant widget. One line on any site:
 *
 *   <script src="https://consultant.example.com/widget.js" defer></script>
 *
 * Options as data- attributes of the script tag:
 *   data-title       header title (default: the company from the server)
 *   data-target      CSS selector to mount inline instead of the floating button
 *   data-open        "1" opens the chat at once, except on a phone where it would cover the page
 *
 * In the server's demo mode (DEMO_LEADS=1) the lead form runs to the end and the widget shows the
 * message the manager would get in Telegram instead of sending it.
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
      var controller = new AbortController();
      var timeout = setTimeout(function () { controller.abort(); }, 90000);
      try {
      if (!isForm && ds.channel === "telegram") body.channel = "telegram";
      var r = await fetch(base + path.replace(/^\//, ""), {
        method: "POST",
        signal: controller.signal,
        headers: isForm ? undefined : { "Content-Type": "application/json" },
        body: isForm ? body : JSON.stringify(body),
      });
      var data = await r.json();
      if (!r.ok && data.kind !== "error") throw new Error("HTTP " + r.status);
      sessionId = data.kind === "session_expired" ? null : (data.session_id || sessionId);
      return data;
      } finally { clearTimeout(timeout); }
    }
    return {
      ready: Promise.resolve(),
      greet: function () { return post("api/chat", { session_id: sessionId, text: "" }); },
      resume: function () { return post("api/session", { session_id: sessionId }); },
      restart: function () { sessionId = null; return this.greet(); },
      ask: function (text) { return post("api/chat", { session_id: sessionId, text: text }); },
      upload: function (file) {
        var f = new FormData();
        f.append("file", file);
        f.append("session_id", sessionId || "");
        return post("api/upload", f, true);
      },
      dropUpload: function () { return post("api/upload/delete", { session_id: sessionId }); },
      forget: async function () {
        if (sessionId) await post("api/session/delete", { session_id: sessionId });
        sessionId = null;
      },
      session: function () { return sessionId; },
      accept: ".txt,.md,.pdf",
    };
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
   * the tab keeps what was shown (sessionStorage, gone with the tab). */
  var STORE_KEY = "ai-consultant:" + base + ":" + (ds.channel || "widget");
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
    if (target) { host.style.display = "block"; host.style.height = "100%"; host.style.minHeight = "0"; }
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
    var status = el("div", "aic-status", ds.channel === "telegram" ? "Браузерный предпросмотр бота" : "Ответы по базе компании");
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

    var engine, started = false, needsRestart = false, generation = 0;
    var state = { session: null, open: false, items: [] };

    function persist() {
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
      if (r.kind === "session") { renderControls(r); return; }
      if (r.kind === "session_expired") {
        generation += 1;
        needsRestart = true;
        state.items = [];
        state.session = null;
        log.textContent = "";
        input.value = "";
        input.disabled = attach.disabled = true;
      }
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
        var reasons = {
          model_refusal: "Модель просмотрела найденные фрагменты и не нашла в них ответа.",
          weak_match: "Недостаточно надёжное совпадение с базой для ответа.",
          provider_unavailable: "Модель недоступна. Использован поиск по базе без модели.",
          model_answer: "Модель составила ответ по найденным фрагментам.",
          retrieved: "Показан подходящий фрагмент базы без генерации."
        };
        t.append(el("div", "aic-search-head", reasons[r.decision] || "Найденные фрагменты базы знаний"));
        r.search.forEach(function (h, i) {
          var row = el("div", "aic-hit");
          row.append(el("span", "aic-hit-n", String(i + 1)), el("span", "aic-hit-t", h.title),
            el("span", "aic-hit-s", "слова " + h.lexical.toFixed(2) + " · буквы " + h.grams.toFixed(2)));
          t.append(row);
        });
        b.append(t);
      }
      chips.textContent = "";
      (r.buttons || []).forEach(function (label) {
        var shortLabels = { "Сколько стоит доставка?": "Доставка", "За сколько дней заказать торт?": "Заказ торта", "Есть что-нибудь без глютена?": "Без глютена", "Позвать менеджера": "Менеджер" };
        var c = el("button", "aic-chip", shortLabels[label] || label);
        c.type = "button";
        c.setAttribute("aria-label", label);
        c.title = label;
        c.addEventListener("click", function () {
          if (label === "Начать новый диалог" && needsRestart) restart();
          else submit(label);
        });
        chips.append(c);
      });
      renderControls(r);
      scroll();
    }

    function renderControls(r) {
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
    }

    // Calls go one after another: a question asked while the greeting loads waits for it
    var queue = Promise.resolve();
    function run(fn) {
      var version = generation;
      queue = queue.then(function () { if (version === generation) return step(fn, version); });
      return queue;
    }

    async function step(fn, version) {
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
        var error = { kind: "error", text: "Не удалось получить ответ. Проверьте связь и повторите запрос." };
        render(error);
        var retry = el("button", "aic-chip", "Повторить запрос");
        retry.type = "button";
        retry.addEventListener("click", function () {
          retry.remove();
          if (version === generation) run(fn);
        });
        log.lastElementChild.append(retry);
        scroll();
      } finally {
        send.disabled = needsRestart;
        persist();
      }
    }

    function submit(text) {
      if (needsRestart) return;
      text = (text || "").trim();
      if (!text) return;
      userBubble(text);
      input.value = "";
      run(function () { return engine.ask(text); });
    }

    function makeEngine() {
      engine = apiEngine(state.session);
      file.accept = engine.accept;
    }

    function start() {
      if (started) return;
      started = true;
      makeEngine();
      run(function () { return engine.greet(); });
    }

    function restart() {
      generation += 1;
      needsRestart = false;
      input.disabled = attach.disabled = false;
      log.textContent = "";
      chips.textContent = "";
      state.items = [];
      state.session = null;
      run(function () { return engine.restart(); });
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
      if (state.session) run(function () { return engine.resume(); });
      send.disabled = needsRestart;
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

    var saved = loadState();
    if (saved && saved.items && saved.items.length) {
      restore(saved);
      if (saved.open || target) { wrap.classList.add("aic-open"); scroll(); }
    } else if (target || (ds.open === "1" && !window.matchMedia("(max-width: 480px)").matches)) open();
    // ask() from a button on the page: the question goes after the greeting if the chat was closed
    function ask(text) {
      open();
      queue.then(function () { submit(text); });
    }
    return { open: open, ask: ask, forget: async function () {
      await queue;
      if (engine) await engine.forget();
      forget();
    } };
  }

  function boot() { window.AiConsultant = mount(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
