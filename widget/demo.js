(function () {
  "use strict";
  var telegram = new URLSearchParams(location.search).get("channel") === "telegram";
  if (telegram) {
    document.body.classList.add("telegram");
    document.querySelector(".brand").textContent = "Колосок · Telegram-бот";
    document.querySelector(".demo-label").textContent = "Предпросмотр в браузере";
    document.querySelector(".eyebrow").textContent = "ЕДИНАЯ БАЗА ДЛЯ ДВУХ КАНАЛОВ";
    document.querySelector("h1").textContent = "Тот же консультант в диалоге с ботом";
    document.querySelector("#context-description").textContent = "В исходном проекте Telegram-бот использует тот же поиск, модель и анкету. Здесь можно пройти этот сценарий в браузере — без подключения к Telegram.";
    document.querySelector("#channel-note").textContent = "Это браузерный предпросмотр канала, а не окно Telegram. Ответы даёт настоящий API; в предпросмотре заявки будет указан Telegram. В Telegram сообщения и заявки не отправляются.";
  }
  var widget = document.createElement("script");
  widget.src = "widget.js";
  widget.dataset.target = "#consultant";
  widget.dataset.title = telegram ? "Колосок · бот" : "Консультант «Колоска»";
  widget.dataset.channel = telegram ? "telegram" : "widget";
  document.body.append(widget);
  document.querySelectorAll("[data-question]").forEach(function (button) {
    button.addEventListener("click", function () {
      if (window.AiConsultant) window.AiConsultant.ask(button.dataset.question);
    });
  });
})();
