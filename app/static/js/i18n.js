/* Лёгкий i18n-слой без сборки: словари ru/uk встроены в страницу сервером
   (window.__I18N__, см. index.html) — так переводы применяются синхронно,
   до того как остальные скрипты успеют отрисовать динамический контент.
   Переключение языка сохраняется в localStorage и применяется мгновенно,
   без перезагрузки страницы (см. setLanguage/langchange). */
(function () {
  const STORAGE_KEY = "dashboard_lang";
  const DICTS = window.__I18N__ || { ru: {}, uk: {} };

  let currentLang = localStorage.getItem(STORAGE_KEY) || "ru";
  if (!DICTS[currentLang]) currentLang = "ru";

  function t(key, vars) {
    const dict = DICTS[currentLang] || {};
    let text = dict[key];
    if (text === undefined) text = (DICTS.ru || {})[key];
    if (text === undefined) return key;
    if (vars) {
      Object.keys(vars).forEach((k) => {
        text = text.replace(new RegExp(`\\{${k}\\}`, "g"), vars[k]);
      });
    }
    return text;
  }

  function applyTranslations(root) {
    root = root || document;
    root.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    root.querySelectorAll("[data-i18n-html]").forEach((el) => {
      el.innerHTML = t(el.getAttribute("data-i18n-html"));
    });
    root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.setAttribute("placeholder", t(el.getAttribute("data-i18n-placeholder")));
    });
    root.querySelectorAll("[data-i18n-title]").forEach((el) => {
      el.setAttribute("title", t(el.getAttribute("data-i18n-title")));
    });
  }

  function setLanguage(lang) {
    if (!DICTS[lang]) return;
    currentLang = lang;
    localStorage.setItem(STORAGE_KEY, lang);
    document.documentElement.lang = lang === "uk" ? "uk" : "ru";
    applyTranslations();
    document.dispatchEvent(new CustomEvent("langchange", { detail: { lang } }));
  }

  // Автоматически прокидываем текущий язык интерфейса на бэкенд (заголовок X-Lang),
  // не трогая ни один из ~40 существующих fetch()-вызовов по всем вкладкам.
  const nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    init = init || {};
    let headers;
    if (input instanceof Request) {
      headers = new Headers(input.headers);
    } else {
      headers = new Headers(init.headers || {});
    }
    headers.set("X-Lang", currentLang);
    init.headers = headers;
    return nativeFetch(input, init);
  };

  function locale() {
    return currentLang === "uk" ? "uk-UA" : "ru-RU";
  }

  document.documentElement.lang = currentLang === "uk" ? "uk" : "ru";
  window.I18N = { t, applyTranslations, setLanguage, getLang: () => currentLang, locale };
  applyTranslations();

  // Переключатель РУС/УКР в шапке — общий для index.html и onboarding.html, поэтому живёт
  // здесь, а не в app.js (который тянет за собой логику вкладок, ненужную мастеру настройки).
  document.addEventListener("DOMContentLoaded", () => {
    const langButtons = document.querySelectorAll(".lang-btn");
    function syncLangButtons() {
      langButtons.forEach((b) => b.classList.toggle("active", b.dataset.lang === currentLang));
    }
    langButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        setLanguage(btn.dataset.lang);
        syncLangButtons();
      });
    });
    syncLangButtons();
  });
})();
