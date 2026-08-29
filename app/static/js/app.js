if (window.Chart) {
  Chart.defaults.color = "#9d98a8";
  Chart.defaults.borderColor = "rgba(255,255,255,0.08)";
  Chart.defaults.font.family = "Jost, system-ui, sans-serif";
}

document.addEventListener("DOMContentLoaded", () => {
  const tabButtons = document.querySelectorAll(".tab-btn");
  const panels = document.querySelectorAll(".tab-panel");

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabButtons.forEach((b) => b.classList.remove("active"));
      panels.forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    });
  });

  loadTokenStatusPill();
  applyUrlTabParams(tabButtons, panels);
});

/** Обробка редіректу назад із TikTok OAuth (app/routes/tiktok.py::callback): ?tab=settings
    відкриває потрібну вкладку, ?tiktok=connected|error(&tiktok_message=...) показує короткий
    статус там-таки. Прибираємо параметри з адресного рядка одразу після зчитування, щоб
    перезавантаження сторінки не показувало банер повторно. */
function applyUrlTabParams(tabButtons, panels) {
  const params = new URLSearchParams(window.location.search);
  const tab = params.get("tab");
  if (tab && document.getElementById(`tab-${tab}`)) {
    tabButtons.forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    panels.forEach((p) => p.classList.toggle("active", p.id === `tab-${tab}`));
  }

  const tiktokStatus = params.get("tiktok");
  if (tiktokStatus) {
    const message =
      tiktokStatus === "connected"
        ? I18N.t("tiktok.msg.connected_banner")
        : I18N.t("tiktok.msg.error_banner", { message: params.get("tiktok_message") || "" });
    window.__TIKTOK_OAUTH_RESULT__ = { status: tiktokStatus, message };
    document.dispatchEvent(new CustomEvent("tiktok-oauth-result", { detail: window.__TIKTOK_OAUTH_RESULT__ }));
  }

  if (tab || tiktokStatus) {
    const url = new URL(window.location.href);
    url.search = "";
    window.history.replaceState({}, "", url.toString());
  }
}

/** Пилюля статуса токена в шапке — видна на любой вкладке, не только в Настройках, чтобы
    истечение токена не стало сюрпризом, когда пользователь давно не заходил в Настройки. */
async function loadTokenStatusPill() {
  const pill = document.getElementById("token-status-pill");
  if (!pill) return;
  const dot = pill.querySelector(".dot");
  const text = pill.querySelector(".text");

  try {
    const res = await fetch("/api/settings/token-status");
    const data = await res.json();

    if (data.is_valid === null && !data.expires_at) {
      pill.style.display = "none";
      return;
    }

    pill.style.display = "inline-flex";

    if (data.is_valid === false) {
      pill.className = "token-status-pill error";
      text.textContent = I18N.t("header.token.invalid");
      return;
    }
    if (!data.expires_at) {
      pill.className = "token-status-pill ok";
      text.textContent = I18N.t("header.token.ok");
      return;
    }
    const daysLeft = Math.ceil((new Date(data.expires_at) - new Date()) / 86400000);
    if (daysLeft <= 10) {
      pill.className = "token-status-pill error";
      text.textContent = I18N.t("header.token.expiring", { days: daysLeft });
    } else if (daysLeft <= 21) {
      pill.className = "token-status-pill warn";
      text.textContent = I18N.t("header.token.expiring", { days: daysLeft });
    } else {
      pill.className = "token-status-pill ok";
      text.textContent = I18N.t("header.token.ok");
    }
  } catch (e) {
    pill.style.display = "none";
  }
}

/** «обновлено N мин/ч/дн назад» для меток последнего синка (метрики/реклама) — единая
    логика, используется и metrics.js, и ads.js, чтобы фоновое авто-обновление
    (см. app/scheduler.py) было видно на вкладке без ручного нажатия «Синхронизировать». */
function timeAgoText(iso) {
  if (!iso) return "";
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return I18N.t("common.updated_just_now");
  if (minutes < 60) return I18N.t("common.updated_minutes_ago", { minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return I18N.t("common.updated_hours_ago", { hours });
  const days = Math.floor(hours / 24);
  return I18N.t("common.updated_days_ago", { days });
}

function fmtNumber(value) {
  if (value === null || value === undefined) {
    return `<span class="na">${I18N.t("common.no_data")}</span>`;
  }
  return Number(value).toLocaleString(I18N.locale());
}

function fmtPercent(value) {
  if (value === null || value === undefined) {
    return `<span class="na">${I18N.t("common.no_data")}</span>`;
  }
  return `${value}%`;
}

/** Компактный вид (12.3K) для узких колонок таблицы; точное число — в title (наведение курсора). */
function fmtCompactCell(value) {
  if (value === null || value === undefined) {
    return `<span class="na">${I18N.t("common.na")}</span>`;
  }
  const num = Number(value);
  const exact = num.toLocaleString(I18N.locale());
  const compact = new Intl.NumberFormat(I18N.locale(), { notation: "compact", maximumFractionDigits: 1 }).format(num);
  return `<span title="${exact}">${compact}</span>`;
}

/** Instagram Insights отдаёт время просмотра в миллисекундах — переводим в секунды для чтения,
    точное значение в мс оставляем в title для сверки. */
function fmtMsAsSeconds(valueMs) {
  if (valueMs === null || valueMs === undefined) return `<span class="na">${I18N.t("common.no_data")}</span>`;
  const seconds = Number(valueMs) / 1000;
  return `<span title="${valueMs} мс">${seconds.toLocaleString(I18N.locale(), { maximumFractionDigits: 1 })} сек</span>`;
}

/** Иконка ⓘ рядом с названием метрики — клик открывает полное объяснение (см. metric-info.js),
    title даёт короткую подсказку при наведении мышью без лишнего кода. */
function infoIcon(metricId, shortHint) {
  const hint = shortHint ? ` title="${shortHint}"` : "";
  return `<span class="info-icon" data-metric="${metricId}"${hint}>ⓘ</span>`;
}

/** Тип хука хранится в данных канонической строкой на русском ("вопрос", "боль" и т.п.) —
    так его сравнивает бэкенд (генератор скриптов, классификатор). Тут только перевод ДЛЯ ПОКАЗА,
    само значение в данных не меняется. */
const HOOK_TYPE_KEYS = {
  "вопрос": "hook_type.question",
  "боль": "hook_type.pain",
  "провокация": "hook_type.provocation",
  "провокація": "hook_type.provocation",
  "цифра": "hook_type.number",
  "утверждение": "hook_type.statement",
};

function hookTypeLabel(type) {
  if (!type) return type;
  const key = HOOK_TYPE_KEYS[type];
  return key ? I18N.t(key) : type;
}

/** Стадия/температура лестницы Ханта тоже хранится канонической строкой на русском
    (см. app/hunt_classifier.py) — те же правила перевода, что для hookTypeLabel. */
const HUNT_STAGE_KEYS = {
  "не осознаёт": "hooks.hunt.stage.unaware",
  "осознаёт проблему": "hooks.hunt.stage.problem_aware",
  "ищет решение": "hooks.hunt.stage.solution_seeking",
  "выбирает": "hooks.hunt.stage.comparing",
  "покупает": "hooks.hunt.stage.buying",
};
const HUNT_TEMP_KEYS = {
  "холодная": "hooks.hunt.temp.cold",
  "тёплая": "hooks.hunt.temp.warm",
  "горячая": "hooks.hunt.temp.hot",
};

function huntStageLabel(stage) {
  if (!stage) return stage;
  const key = HUNT_STAGE_KEYS[stage];
  return key ? I18N.t(key) : stage;
}

function huntTempLabel(temp) {
  if (!temp) return temp;
  const key = HUNT_TEMP_KEYS[temp];
  return key ? I18N.t(key) : temp;
}
