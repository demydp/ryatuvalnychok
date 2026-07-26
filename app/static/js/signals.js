(function () {
  const listEl = document.getElementById("signals-list");
  const emptyEl = document.getElementById("signals-empty");
  const metaEl = document.getElementById("signals-meta");
  const refreshBtn = document.getElementById("btn-signals-refresh");
  const countRed = document.getElementById("signals-count-red");
  const countYellow = document.getElementById("signals-count-yellow");
  const countGreen = document.getElementById("signals-count-green");
  const resolvedWrap = document.getElementById("signals-resolved-wrap");
  const resolvedToggleBtn = document.getElementById("btn-signals-show-resolved");
  const resolvedList = document.getElementById("signals-resolved-list");

  const homeBadge = document.getElementById("home-signals-badge");
  const homePreview = document.getElementById("home-signals-preview");
  const homeEmpty = document.getElementById("home-signals-empty");
  const homeAllBtn = document.getElementById("btn-home-signals-all");

  const PREVIEW_LIMIT = 3;

  let lastData = null;
  let resolvedShown = false;

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function goToTab(tabName) {
    const btn = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
    if (btn) btn.click();
  }

  function signalCardHtml(s) {
    const actionsHtml = s.status === "new"
      ? `
        <div class="signal-card-actions">
          <button class="btn secondary signal-view-btn" data-tab="${s.tab}">${I18N.t("signals.action.view")}</button>
          <button class="btn secondary signal-done-btn" data-id="${escapeHtml(s.id)}">${I18N.t("signals.action.done")}</button>
          <button class="btn secondary signal-dismiss-btn" data-id="${escapeHtml(s.id)}">${I18N.t("signals.action.dismiss")}</button>
        </div>`
      : `<div class="signal-card-actions"><span class="signal-status-label">${I18N.t(`signals.status.${s.status}`)}</span></div>`;

    return `
      <div class="card signal-card signal-level-${s.level}" data-id="${escapeHtml(s.id)}">
        <div class="signal-card-header">
          <span class="signal-level-badge signal-level-badge-${s.level}">${I18N.t(`signals.level.${s.level}`)}</span>
          <span class="signal-group-badge">${I18N.t(`signals.group.${s.group}`)}</span>
        </div>
        <div class="signal-title">${escapeHtml(s.title)}</div>
        <div class="signal-reason">${escapeHtml(s.reason)}</div>
        <div class="signal-action">→ ${escapeHtml(s.action)}</div>
        ${actionsHtml}
      </div>
    `;
  }

  function wireCardActions(root) {
    if (!root) return;
    root.querySelectorAll(".signal-view-btn").forEach((btn) => {
      btn.addEventListener("click", () => goToTab(btn.dataset.tab));
    });
    root.querySelectorAll(".signal-done-btn").forEach((btn) => {
      btn.addEventListener("click", () => actOnSignal(btn.dataset.id, "done"));
    });
    root.querySelectorAll(".signal-dismiss-btn").forEach((btn) => {
      btn.addEventListener("click", () => actOnSignal(btn.dataset.id, "dismiss"));
    });
  }

  async function actOnSignal(id, action) {
    try {
      await fetch(`/api/signals/${encodeURIComponent(id)}/${action}`, { method: "POST" });
      await load();
    } catch (e) {
      if (metaEl) metaEl.textContent = I18N.t("common.network_error", { message: e.message });
    }
  }

  function render() {
    if (!lastData) return;
    const active = lastData.signals.filter((s) => s.status === "new");
    const resolved = lastData.signals.filter((s) => s.status !== "new");

    if (listEl) {
      listEl.innerHTML = active.map(signalCardHtml).join("");
      wireCardActions(listEl);
      if (emptyEl) emptyEl.style.display = active.length ? "none" : "block";

      if (resolvedWrap) {
        if (resolved.length) {
          resolvedWrap.style.display = "block";
          resolvedToggleBtn.textContent = I18N.t("signals.show_resolved_btn", { count: resolved.length });
        } else {
          resolvedWrap.style.display = "none";
        }
        resolvedList.innerHTML = resolved.map(signalCardHtml).join("");
        resolvedList.style.display = resolvedShown ? "block" : "none";
        wireCardActions(resolvedList);
      }

      if (countRed) countRed.textContent = `${I18N.t("signals.level.red")}: ${lastData.counts.red}`;
      if (countYellow) countYellow.textContent = `${I18N.t("signals.level.yellow")}: ${lastData.counts.yellow}`;
      if (countGreen) countGreen.textContent = `${I18N.t("signals.level.green")}: ${lastData.counts.green}`;
    }

    if (homePreview) {
      const preview = active.slice(0, PREVIEW_LIMIT);
      homePreview.innerHTML = preview.map(signalCardHtml).join("");
      wireCardActions(homePreview);
      if (homeEmpty) homeEmpty.style.display = active.length ? "none" : "block";
    }

    if (homeBadge) {
      if (lastData.active_count > 0) {
        homeBadge.style.display = "inline-flex";
        homeBadge.textContent = lastData.active_count;
      } else {
        homeBadge.style.display = "none";
      }
    }
  }

  async function load() {
    if (metaEl) metaEl.textContent = I18N.t("signals.msg.loading");
    try {
      const res = await fetch("/api/signals");
      const data = await res.json();
      lastData = data;
      render();
      if (metaEl) metaEl.textContent = I18N.t("ads.msg.loaded_at", { time: new Date().toLocaleTimeString(I18N.locale()) });
    } catch (e) {
      if (metaEl) metaEl.textContent = I18N.t("common.network_error", { message: e.message });
    }
  }

  if (refreshBtn) refreshBtn.addEventListener("click", load);
  if (resolvedToggleBtn) {
    resolvedToggleBtn.addEventListener("click", () => {
      resolvedShown = !resolvedShown;
      resolvedList.style.display = resolvedShown ? "block" : "none";
    });
  }
  if (homeAllBtn) homeAllBtn.addEventListener("click", () => goToTab("signals"));

  document.addEventListener("langchange", () => render());

  const signalsTabBtn = document.querySelector('.tab-btn[data-tab="signals"]');
  if (signalsTabBtn) signalsTabBtn.addEventListener("click", load);

  // Головна показує прев'ю сигналів разом з рештою своїх карток — довантажуємо на той самий клік.
  const homeTabBtn = document.querySelector('.tab-btn[data-tab="home"]');
  if (homeTabBtn) homeTabBtn.addEventListener("click", load);

  load();
})();
