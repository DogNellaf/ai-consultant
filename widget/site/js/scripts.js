/*!
* Start Bootstrap - Business Casual v7.0.9 (https://startbootstrap.com/theme/business-casual)
* Copyright 2013-2023 Start Bootstrap
* Licensed under MIT (https://github.com/StartBootstrap/startbootstrap-business-casual/blob/master/LICENSE)
*/
window.addEventListener('DOMContentLoaded', () => {
    // Highlights today in the opening hours. The list starts on Monday, getDay() on Sunday.
    const days = document.body.querySelectorAll('.list-hours li');
    if (days.length === 7) days[(new Date().getDay() + 6) % 7].classList.add('today');

    // Buttons that talk to the consultant widget (widget.js)
    document.body.querySelectorAll('[data-open-chat]').forEach((button) => {
        button.addEventListener('click', () => window.AiConsultant && window.AiConsultant.open());
    });
    document.body.querySelectorAll('[data-ask]').forEach((button) => {
        button.addEventListener('click', () => window.AiConsultant && window.AiConsultant.ask(button.dataset.ask));
    });
});
