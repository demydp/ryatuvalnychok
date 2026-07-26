/*
  Розділи, що згортаються/розгортаються (глобальний редизайн) — замість ручного редагування
  розмітки в ~15 шаблонах, ця функція один раз при завантаженні сторінки проходить по всіх
  верхньорівневих .card усіх вкладок (вони всі вже в DOM одразу, .tab-panel лише ховає неактивні
  через display:none — див. app/static/css/style.css) і перетворює ті з них, у яких перший
  елемент — h2 (або h2 всередині першого .toolbar, патерн "заголовок + кнопка праворуч") — на
  розділ, що згортається: заголовок стає клікабельним (.sec-head), решта вмісту картки
  переїжджає в обгортку .sec-body (max-height/opacity анімація в CSS).

  Картки БЕЗ явного h2-заголовка (дрібні картки-статистики, картки-кнопки без назви) свідомо не
  займаються — вони і так компактні, робити їх розділами нема сенсу. Так само не займаються
  картки, вкладені в грід-контейнери (charts-grid, post-lists-grid, top-cards, model-cards,
  direction-status-grid, detail-grid) — вони вже дрібні тайли всередині групи, а не самостійні
  верхньорівневі блоки.

  ВАЖЛИВО: це суто перестановка існуючих DOM-вузлів (moveNode, не clone) — усі id/значення
  полів/обробники подій на дочірніх елементах лишаються живими, дані не губляться при
  згортанні (max-height:0 — не display:none, поля форм лишаються в DOM і читаються JS як завжди).
*/
(function () {
  const STORAGE_KEY = "dashboard_sections_state";
  const SKIP_PARENT_CLASSES = [
    "charts-grid",
    "post-lists-grid",
    "top-cards",
    "model-cards",
    "direction-status-grid",
    "detail-grid",
  ];
  const IGNORE_CLICK_SELECTOR = "button, a, input, select, textarea, .info-icon, label";

  function loadState() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
    } catch (e) {
      return {};
    }
  }

  function saveState(state) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (e) {
      // localStorage недоступний (приватний режим тощо) — стан просто не переживе перезавантаження,
      // не критично, розділ і так лишається робочим у поточній сесії.
    }
  }

  function sectionKey(tabPanel, heading, fallbackIndex) {
    const withI18n = heading.hasAttribute("data-i18n") ? heading : heading.querySelector("[data-i18n]");
    const i18nKey = withI18n ? withI18n.getAttribute("data-i18n") : null;
    return `${tabPanel.id || "tab"}__${i18nKey || "idx" + fallbackIndex}`;
  }

  function findHeader(card) {
    const first = card.firstElementChild;
    if (!first) return null;
    if (first.tagName === "H2") return { headEl: first, heading: first };
    if (first.classList.contains("toolbar")) {
      const h2 = first.querySelector(":scope > h2");
      if (h2) return { headEl: first, heading: h2 };
    }
    return null;
  }

  function toggle(card, key, state) {
    const open = card.classList.toggle("open");
    state[key] = open;
    saveState(state);
  }

  function sectionize() {
    const state = loadState();
    let fallbackCounter = 0;

    document.querySelectorAll(".tab-panel").forEach((tabPanel) => {
      const cards = tabPanel.querySelectorAll(".card");
      cards.forEach((card) => {
        if (card.parentElement.closest(".card")) return; // не верхнього рівня
        if (SKIP_PARENT_CLASSES.some((cls) => card.parentElement.classList.contains(cls))) return;

        const found = findHeader(card);
        if (!found) return;
        const { headEl, heading } = found;

        const key = sectionKey(tabPanel, heading, fallbackCounter++);

        const chev = document.createElement("span");
        chev.className = "chev";
        chev.textContent = "⌄";
        heading.appendChild(chev);

        const body = document.createElement("div");
        body.className = "sec-body";
        Array.from(card.children)
          .filter((el) => el !== headEl)
          .forEach((el) => body.appendChild(el));
        card.appendChild(body);

        headEl.classList.add("sec-head");
        card.classList.add("sec");
        card.dataset.secKey = key;

        const isOpen = key in state ? state[key] : true;
        card.classList.toggle("open", isOpen);

        headEl.addEventListener("click", (e) => {
          if (e.target.closest(IGNORE_CLICK_SELECTOR)) return;
          toggle(card, key, state);
        });
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", sectionize);
  } else {
    sectionize();
  }
})();
