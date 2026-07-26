(function () {
  const newTaskInput = document.getElementById("new-task-text");
  const addTaskBtn = document.getElementById("btn-add-task");
  const planStatus = document.getElementById("plan-status");
  const planEmpty = document.getElementById("plan-empty");
  const planList = document.getElementById("plan-list");

  const statsContent = document.getElementById("stats-content");
  const statsAds = document.getElementById("stats-ads");
  const statusSmmBody = document.getElementById("status-smm-body");
  const statusAdsBody = document.getElementById("status-ads-body");

  const gotoMetricsBtn = document.getElementById("btn-goto-metrics");
  const gotoAdsBtn = document.getElementById("btn-goto-ads");

  let lastTasks = null;
  let lastSummary = null;

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function naSpan() {
    return `<span class="na">${I18N.t("common.na")}</span>`;
  }

  function goToTab(tabName) {
    const btn = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
    if (btn) btn.click();
  }

  if (gotoMetricsBtn) gotoMetricsBtn.addEventListener("click", () => goToTab("metrics"));
  if (gotoAdsBtn) gotoAdsBtn.addEventListener("click", () => goToTab("ads"));

  // --- Мой план на день -----------------------------------------------------

  function showPlanError(message) {
    planStatus.textContent = message;
    planStatus.classList.add("show");
  }

  function hidePlanError() {
    planStatus.classList.remove("show");
  }

  function taskItemHtml(task) {
    const doneClass = task.done ? "plan-item done" : "plan-item";
    return `
      <li class="${doneClass}" data-id="${task.id}">
        <label class="plan-item-check">
          <input type="checkbox" class="plan-toggle" data-id="${task.id}" ${task.done ? "checked" : ""}>
        </label>
        <span class="plan-item-text" data-id="${task.id}">${escapeHtml(task.text)}</span>
        <span class="plan-item-actions">
          <button class="icon-btn plan-edit-btn" data-id="${task.id}" data-i18n="home.plan.edit_btn">${I18N.t("home.plan.edit_btn")}</button>
          <button class="icon-btn plan-delete-btn" data-id="${task.id}" data-i18n="home.plan.delete_btn">${I18N.t("home.plan.delete_btn")}</button>
        </span>
      </li>
    `;
  }

  function renderPlan(tasks) {
    if (!tasks.length) {
      planEmpty.style.display = "block";
      planList.innerHTML = "";
      return;
    }
    planEmpty.style.display = "none";
    planList.innerHTML = tasks.map(taskItemHtml).join("");
    wirePlanItemEvents();
  }

  function wirePlanItemEvents() {
    planList.querySelectorAll(".plan-toggle").forEach((cb) => {
      cb.addEventListener("change", async () => {
        try {
          await fetch(`/api/home/plan/${cb.dataset.id}/toggle`, { method: "POST" });
          hidePlanError();
          await loadPlan();
        } catch (e) {
          showPlanError(I18N.t("home.plan.msg.network_error"));
        }
      });
    });

    planList.querySelectorAll(".plan-delete-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/api/home/plan/${btn.dataset.id}`, { method: "DELETE" });
          hidePlanError();
          await loadPlan();
        } catch (e) {
          showPlanError(I18N.t("home.plan.msg.network_error"));
        }
      });
    });

    planList.querySelectorAll(".plan-edit-btn").forEach((btn) => {
      btn.addEventListener("click", () => startEditTask(btn.dataset.id));
    });
  }

  function startEditTask(taskId) {
    const li = planList.querySelector(`li[data-id="${taskId}"]`);
    if (!li) return;
    const textEl = li.querySelector(".plan-item-text");
    const currentText = textEl.textContent;

    textEl.outerHTML = `<input type="text" class="plan-edit-input" data-id="${taskId}" value="${escapeHtml(currentText)}">`;
    const input = li.querySelector(".plan-edit-input");
    input.focus();
    input.select();

    const commit = async () => {
      const newText = input.value.trim();
      if (!newText || newText === currentText) {
        await loadPlan();
        return;
      }
      try {
        await fetch(`/api/home/plan/${taskId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: newText }),
        });
        hidePlanError();
      } catch (e) {
        showPlanError(I18N.t("home.plan.msg.network_error"));
      }
      await loadPlan();
    };

    input.addEventListener("blur", commit);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") input.blur();
      if (e.key === "Escape") loadPlan();
    });
  }

  async function loadPlan() {
    try {
      const res = await fetch("/api/home/plan");
      const data = await res.json();
      hidePlanError();
      lastTasks = data.tasks || [];
      renderPlan(lastTasks);
    } catch (e) {
      showPlanError(I18N.t("home.plan.msg.network_error"));
    }
  }

  async function addTask() {
    const text = newTaskInput.value.trim();
    if (!text) return;
    addTaskBtn.disabled = true;
    try {
      const res = await fetch("/api/home/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) {
        const data = await res.json();
        showPlanError(data.error || I18N.t("home.plan.msg.network_error"));
      } else {
        newTaskInput.value = "";
        hidePlanError();
        await loadPlan();
      }
    } catch (e) {
      showPlanError(I18N.t("home.plan.msg.network_error"));
    } finally {
      addTaskBtn.disabled = false;
    }
  }

  addTaskBtn.addEventListener("click", addTask);
  newTaskInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") addTask();
  });

  // --- Быстрая статистика + статус по направлениям --------------------------

  function statTileHtml(label, valueHtml, sub) {
    return `
      <div class="top-card">
        <div class="label">${label}</div>
        <div class="value">${valueHtml}</div>
        ${sub ? `<div class="sub">${sub}</div>` : ""}
      </div>
    `;
  }

  function renderContentStats(content) {
    const days = content.period_days;
    const reachHtml = content.reach_total !== null && content.reach_total !== undefined
      ? fmtCompactCell(content.reach_total)
      : naSpan();
    const erHtml = content.engagement_rate_avg !== null && content.engagement_rate_avg !== undefined
      ? fmtPercent(content.engagement_rate_avg)
      : naSpan();
    const skipHtml = content.skip_rate_avg !== null && content.skip_rate_avg !== undefined
      ? fmtPercent(content.skip_rate_avg)
      : naSpan();

    let topReelTile;
    if (content.top_reel) {
      const tr = content.top_reel;
      const caption = tr.caption ? escapeHtml(tr.caption) : I18N.t("home.stats.top_reel_no_caption");
      const link = tr.permalink
        ? `<a href="${tr.permalink}" target="_blank" rel="noopener" style="color:inherit;">${caption}</a>`
        : caption;
      topReelTile = statTileHtml(
        I18N.t("home.stats.top_reel"),
        tr.engagement_rate !== null && tr.engagement_rate !== undefined ? fmtPercent(tr.engagement_rate) : naSpan(),
        link
      );
    } else {
      topReelTile = statTileHtml(I18N.t("home.stats.top_reel"), naSpan(), I18N.t("home.stats.no_data_period"));
    }

    statsContent.innerHTML = [
      statTileHtml(I18N.t("home.stats.reach", { days }), reachHtml, I18N.t("home.stats.posts_count", { count: content.posts_count })),
      statTileHtml(I18N.t("home.stats.er", { days }), erHtml),
      statTileHtml(I18N.t("home.stats.skip_rate", { days }), skipHtml),
      topReelTile,
    ].join("");
  }

  function renderAdsStats(ads) {
    if (!ads.available) {
      statsAds.innerHTML = `<div class="hint">${escapeHtml(ads.note || I18N.t("common.no_data"))}</div>`;
      return;
    }

    const spendHtml = ads.spend_today !== null && ads.spend_today !== undefined
      ? Number(ads.spend_today).toLocaleString(I18N.locale(), { maximumFractionDigits: 2 })
      : naSpan();

    let bestTile;
    if (ads.best_campaign) {
      const b = ads.best_campaign;
      bestTile = statTileHtml(
        I18N.t("home.stats.ads_best"),
        `${b.result_label || I18N.t("common.no_data")}: ${b.result_value ?? "—"}`,
        escapeHtml(b.name || "")
      );
    } else {
      bestTile = statTileHtml(I18N.t("home.stats.ads_best"), naSpan());
    }

    statsAds.innerHTML = [
      statTileHtml(I18N.t("home.stats.ads_spend"), spendHtml),
      statTileHtml(I18N.t("home.stats.ads_campaigns"), ads.campaigns_count ?? 0),
      bestTile,
    ].join("");
  }

  function renderSmmStatus(content) {
    let syncLine;
    if (content.synced_at) {
      const dt = new Date(content.synced_at).toLocaleString(I18N.locale(), { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
      syncLine = I18N.t("home.status.smm.last_sync", { date: dt });
    } else {
      syncLine = I18N.t("home.status.smm.never");
    }
    const dataLine = I18N.t("home.status.smm.data", { ok: content.insights_ok || 0, total: content.total_media || 0 });

    statusSmmBody.innerHTML = `<div>${syncLine}</div><div>${dataLine}</div>`;
  }

  function renderAdsStatus(ads) {
    if (!ads.available) {
      statusAdsBody.innerHTML = `<div>${escapeHtml(ads.note || I18N.t("common.no_data"))}</div>`;
      return;
    }
    const spendHtml = ads.spend_today !== null && ads.spend_today !== undefined
      ? Number(ads.spend_today).toLocaleString(I18N.locale(), { maximumFractionDigits: 2 })
      : I18N.t("common.no_data");
    statusAdsBody.innerHTML = `
      <div>${I18N.t("home.status.ads.active", { count: ads.campaigns_count || 0 })}</div>
      <div>${I18N.t("home.status.ads.spend", { spend: spendHtml })}</div>
    `;
  }

  async function loadSummary() {
    try {
      const res = await fetch("/api/home/summary");
      const data = await res.json();
      lastSummary = data;
      renderSummary();
    } catch (e) {
      statsContent.innerHTML = `<div class="hint">${I18N.t("home.stats.msg.network_error")}</div>`;
    }
  }

  function renderSummary() {
    if (!lastSummary) return;
    renderContentStats(lastSummary.content);
    renderAdsStats(lastSummary.ads);
    renderSmmStatus(lastSummary.content);
    renderAdsStatus(lastSummary.ads);
  }

  document.querySelector('.tab-btn[data-tab="home"]').addEventListener("click", () => {
    loadPlan();
    loadSummary();
  });

  document.addEventListener("langchange", () => {
    if (lastTasks) renderPlan(lastTasks);
    if (lastSummary) renderSummary();
  });

  loadPlan();
  loadSummary();
})();
