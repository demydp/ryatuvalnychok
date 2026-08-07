(function () {
  const periodBtns = document.querySelectorAll(".period-btn");
  const customRange = document.getElementById("ads-custom-range");
  const dateFromInput = document.getElementById("ads-date-from");
  const dateToInput = document.getElementById("ads-date-to");
  const loadBtn = document.getElementById("btn-ads-load");
  const meta = document.getElementById("ads-meta");
  const updatedAgo = document.getElementById("ads-updated-ago");
  const content = document.getElementById("ads-content");
  const emptyState = document.getElementById("ads-empty");
  const accountCard = document.getElementById("ads-account-card");
  const rawTable = document.getElementById("ads-raw-table");
  const structureMeta = document.getElementById("ads-structure-meta");
  const campaignsEl = document.getElementById("ads-campaigns");
  const todayNote = document.getElementById("ads-today-note");
  const rawMeta = document.getElementById("ads-raw-meta");

  const kpiObjectiveSelect = document.getElementById("kpi-objective-select");
  const kpiInputs = {
    target_cpl: document.getElementById("kpi-target-cpl"),
    target_cpm: document.getElementById("kpi-target-cpm"),
    target_ctr: document.getElementById("kpi-target-ctr"),
    target_roas: document.getElementById("kpi-target-roas"),
    target_cost_per_result: document.getElementById("kpi-target-cost-per-result"),
  };
  const kpiSaveBtn = document.getElementById("btn-save-kpi");
  const kpiSaveStatus = document.getElementById("kpi-save-status");
  const kpiSavedList = document.getElementById("kpi-saved-list");
  const kpiBenchmarksEl = document.getElementById("kpi-benchmarks");

  let period = "maximum";
  let lastData = null;
  const entityContext = new Map(); // entityId -> {type, objective, targeting}
  const activeCharts = {};
  let kpiState = { targets: {}, objectives: {}, benchmarks: {} };

  function audienceDimLabels() {
    return {
      age: I18N.t("ads.dim.age"),
      gender: I18N.t("ads.dim.gender"),
      country: I18N.t("ads.dim.country"),
      region: I18N.t("ads.dim.region"),
      publisher_platform: I18N.t("ads.dim.publisher_platform"),
      platform_position: I18N.t("ads.dim.platform_position"),
      impression_device: I18N.t("ads.dim.impression_device"),
    };
  }

  periodBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      periodBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      period = btn.dataset.period;
      customRange.style.display = period === "custom" ? "inline-flex" : "none";
      todayNote.style.display = period === "today" ? "block" : "none";
    });
  });

  function naSpan(reason) {
    return `<span class="na">${reason || I18N.t("common.no_data")}</span>`;
  }

  function fmtMoney(value, currency) {
    if (value === null || value === undefined) return naSpan();
    return `${Number(value).toLocaleString(I18N.locale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency || ""}`;
  }

  function fmtRatio(value, digits) {
    if (value === null || value === undefined) return naSpan();
    return Number(value).toFixed(digits === undefined ? 2 : digits);
  }

  function statusBadgeClass(effectiveStatus) {
    const s = (effectiveStatus || "").toUpperCase();
    if (s === "ACTIVE") return "status-active";
    if (["DISAPPROVED", "WITH_ISSUES", "PENDING_BILLING_INFO"].includes(s)) return "status-issue";
    return "status-paused";
  }

  function statusBadge(status, effectiveStatus) {
    const label = effectiveStatus || status || "?";
    return `<span class="badge ${statusBadgeClass(effectiveStatus)}">${label}</span>`;
  }

  const KPI_VERDICT_CLASS = { success: "verdict-good", ok: "verdict-neutral", fail: "verdict-bad" };

  function kpiVerdictLabel(v) {
    if (v === "success") return I18N.t("ads.kpi_verdict.success");
    if (v === "ok") return I18N.t("ads.kpi_verdict.ok");
    if (v === "fail") return I18N.t("ads.kpi_verdict.fail");
    return I18N.t("common.no_data");
  }

  function kpiVerdictHtml(verdicts, currency) {
    if (!verdicts || !verdicts.length) return "";
    return `
      <div class="ads-result-block">
        <div class="k" style="margin-bottom:8px;">${I18N.t("ads.fact_vs_kpi")}</div>
        <div style="display:flex; flex-wrap:wrap; gap:8px;">
          ${verdicts
            .map((v) => {
              const factStr = v.fact !== null && v.fact !== undefined ? Number(v.fact).toLocaleString(I18N.locale(), { maximumFractionDigits: 2 }) : I18N.t("common.no_data");
              const targetStr = Number(v.target).toLocaleString(I18N.locale(), { maximumFractionDigits: 2 });
              const cls = KPI_VERDICT_CLASS[v.verdict] || "verdict-neutral";
              const label = kpiVerdictLabel(v.verdict);
              return `<span class="verdict-badge ${cls}">${I18N.t("ads.kpi_verdict_line", { metric: v.metric, fact: factStr, target: targetStr, label })}</span>`;
            })
            .join("")}
        </div>
      </div>
    `;
  }

  function resultBlockHtml(result, currency) {
    if (!result || !result.label) {
      return `<div class="ads-result-block">${naSpan(result && result.note)}</div>`;
    }
    const parts = [];
    parts.push(`<div><span class="k">${result.label}</span>: <strong>${result.value !== null && result.value !== undefined ? Number(result.value).toLocaleString(I18N.locale()) : naSpan()}</strong></div>`);
    parts.push(`<div><span class="k">${I18N.t("ads.field.cost_per_result")}</span>: <strong>${fmtMoney(result.cost_per_result, currency)}</strong></div>`);
    if (result.roas !== null && result.roas !== undefined) {
      parts.push(`<div><span class="k">ROAS</span>: <strong>${result.roas.toFixed(2)}x</strong></div>`);
    }
    if (result.note) {
      parts.push(`<div style="margin-top:4px;">${naSpan(result.note)}</div>`);
    }
    return `<div class="ads-result-block">${parts.join("")}</div>`;
  }

  function metricsGridHtml(metrics, currency) {
    const rows = [
      [I18N.t("ads.field.spend"), fmtMoney(metrics.spend, currency), "spend"],
      [I18N.t("ads.field.impressions"), fmtNumber(metrics.impressions), "impressions"],
      [I18N.t("ads.field.reach"), fmtNumber(metrics.reach), "ads_reach"],
      [I18N.t("ads.field.frequency"), fmtRatio(metrics.frequency), "frequency"],
      ["CPM", fmtMoney(metrics.cpm, currency), "cpm"],
      [I18N.t("ads.field.clicks_all"), fmtNumber(metrics.clicks), "clicks"],
      [I18N.t("ads.field.link_clicks"), fmtNumber(metrics.link_clicks), "link_clicks"],
      [I18N.t("ads.field.ctr_all"), metrics.ctr !== null && metrics.ctr !== undefined ? fmtPercent(metrics.ctr) : naSpan(), "ctr"],
      [I18N.t("ads.field.ctr_link"), metrics.ctr_link !== null && metrics.ctr_link !== undefined ? fmtPercent(metrics.ctr_link) : naSpan(), "ctr_link"],
      ["CPC", fmtMoney(metrics.cpc, currency), "cpc"],
      [I18N.t("ads.field.cost_per_link_click"), fmtMoney(metrics.cost_per_link_click, currency), "cost_per_link_click"],
      [I18N.t("ads.field.video_3s"), fmtNumber(metrics.video_3s_views), "video_3s"],
      ["ThruPlay", fmtNumber(metrics.thruplay), "thruplay"],
      [I18N.t("ads.field.video_p25"), fmtNumber(metrics.video_p25), "video_p25"],
      [I18N.t("ads.field.video_p50"), fmtNumber(metrics.video_p50), "video_p50"],
      [I18N.t("ads.field.video_p75"), fmtNumber(metrics.video_p75), "video_p75"],
      [I18N.t("ads.field.video_p100"), fmtNumber(metrics.video_p100), "video_p100"],
      [I18N.t("ads.field.video_avg_watch"), fmtRatio(metrics.video_avg_watch_sec, 1), "video_avg_watch"],
    ];
    return `<div class="detail-grid">${rows
      .map(([label, value, metricId]) => `<div><div class="k">${label}${infoIcon(metricId)}</div><div class="v">${value}</div></div>`)
      .join("")}</div>`;
  }

  function budgetLabel(budget, currency) {
    if (budget.daily_budget !== null && budget.daily_budget !== undefined) {
      return I18N.t("ads.budget.daily", { amount: fmtMoney(budget.daily_budget, currency) });
    }
    if (budget.lifetime_budget !== null && budget.lifetime_budget !== undefined) {
      return I18N.t("ads.budget.lifetime", { amount: fmtMoney(budget.lifetime_budget, currency) });
    }
    return naSpan(I18N.t("ads.budget.not_at_this_level"));
  }

  function creativeHtml(creative, currency) {
    const thumb = creative.thumbnail_url
      ? `<img class="ads-creative-thumb" src="${creative.thumbnail_url}" alt="">`
      : "";
    const rows = [
      [I18N.t("ads.creative.format"), creative.type || naSpan()],
      ["Primary text", creative.primary_text || naSpan()],
      [I18N.t("ads.creative.headline"), creative.headline || naSpan()],
      [I18N.t("ads.creative.cta"), creative.cta || naSpan()],
      [I18N.t("ads.creative.link"), creative.link ? `<a href="${creative.link}" target="_blank" rel="noopener">${creative.link}</a>` : naSpan()],
    ];
    return `
      <div style="display:flex; gap:14px; align-items:flex-start;">
        ${thumb}
        <div class="detail-grid" style="flex:1;">
          ${rows.map(([label, value]) => `<div><div class="k">${label}</div><div class="v">${value}</div></div>`).join("")}
        </div>
      </div>
      ${creative.note ? `<div style="margin-top:8px;">${naSpan(creative.note)}</div>` : ""}
    `;
  }

  function targetingHtml(t) {
    const audiences = [];
    if (t.custom_audiences.length) audiences.push(`Custom: ${t.custom_audiences.join(", ")}`);
    if (t.lookalike_audiences.length) audiences.push(`Lookalike: ${t.lookalike_audiences.join(", ")}`);
    const rows = [
      [I18N.t("ads.field.age"), t.age],
      [I18N.t("ads.field.gender"), t.gender],
      [I18N.t("ads.field.geo"), t.geo],
      [I18N.t("ads.field.interests"), t.interests.length ? t.interests.join(", ") : I18N.t("ads.targeting.interests_none")],
      [I18N.t("ads.field.audiences"), audiences.length ? audiences.join(" • ") : I18N.t("ads.targeting.audiences_none")],
      [I18N.t("ads.field.placement"), t.placement],
    ];
    return `<div class="detail-grid">${rows.map(([label, value]) => `<div><div class="k">${label}</div><div class="v">${value}</div></div>`).join("")}
      ${t.interests_note ? `<div style="grid-column:1/-1;">${naSpan(t.interests_note)}</div>` : ""}
    </div>`;
  }

  function adHtml(ad, objective, currency, adsetId, adsetOptimizationGoal) {
    entityContext.set(ad.id, { type: "ad", objective, targeting: null, adsetId, name: ad.name || "", optimizationGoal: adsetOptimizationGoal });
    return `
      <div class="card ads-node ads-node-ad">
        <div class="acc-header">
          <strong>${ad.name || I18N.t("ads.no_name")}</strong>
          ${statusBadge(ad.status, ad.effective_status)}
        </div>
        <div class="detail-grid" style="border-top:none; padding-top:0; margin-top:10px;">
          <div style="grid-column:1/-1;">${creativeHtml(ad.creative, currency)}</div>
        </div>
        ${metricsGridHtml(ad.metrics, currency)}
        ${resultBlockHtml(ad.result, currency)}
        ${fatiguePanelHtml(ad.id)}
        ${placementPanelHtml(ad.id)}
        ${creativeVerdictPanelHtml(ad.id)}
      </div>
    `;
  }

  function adsetHtml(adset, campaignBudgetType, campaignObjective, currency) {
    const adsHtml = adset.ads.map((ad) => adHtml(ad, campaignObjective, currency, adset.id, adset.optimization_goal)).join("");
    entityContext.set(adset.id, { type: "adset", objective: campaignObjective, targeting: adset.targeting, optimizationGoal: adset.optimization_goal });
    return `
      <div class="card ads-node ads-node-adset">
        <div class="acc-header" data-toggle="1">
          <span class="expand-toggle">▸</span>
          <strong>${adset.name || I18N.t("ads.no_name")}</strong>
          ${statusBadge(adset.status, adset.effective_status)}
          <span class="meta">${campaignBudgetType === "CBO" ? I18N.t("ads.budget.from_campaign") : budgetLabel(adset.budget, currency)} • ${I18N.t("ads.optimization_goal")}: ${adset.optimization_goal || I18N.t("common.no_data")} • ${I18N.t("ads.ads_count", { count: adset.ads.length })}</span>
        </div>
        <div class="detail-grid">
          <div><div class="k">${I18N.t("ads.field.bid_strategy")}</div><div class="v">${adset.bid_strategy || naSpan()}</div></div>
          <div><div class="k">${I18N.t("ads.field.bid_amount")}</div><div class="v">${adset.bid_amount !== null && adset.bid_amount !== undefined ? fmtMoney(adset.bid_amount, currency) : naSpan(I18N.t("ads.field.bid_auto"))}</div></div>
          <div><div class="k">Billing event</div><div class="v">${adset.billing_event || naSpan()}</div></div>
          <div><div class="k">${I18N.t("ads.field.schedule")}</div><div class="v">${adset.start_time ? new Date(adset.start_time).toLocaleDateString(I18N.locale()) : "?"} — ${adset.end_time ? new Date(adset.end_time).toLocaleDateString(I18N.locale()) : I18N.t("ads.field.no_end_date")}</div></div>
          <div><div class="k">${I18N.t("ads.field.attribution_window")}</div><div class="v">${adset.attribution}</div></div>
        </div>
        ${targetingHtml(adset.targeting)}
        ${metricsGridHtml(adset.metrics, currency)}
        ${resultBlockHtml(adset.result, currency)}
        ${kpiVerdictHtml(adset.kpi_verdicts, currency)}
        ${audiencePanelHtml(adset.id)}
        ${audienceVerdictPanelHtml(adset.id)}
        <div class="ads-children" style="display:none;">${adsHtml}</div>
      </div>
    `;
  }

  function campaignHtml(campaign, currency) {
    const adsetsHtml = campaign.adsets
      .map((a) => adsetHtml(a, campaign.budget_type, campaign.objective, currency))
      .join("");
    entityContext.set(campaign.id, { type: "campaign", objective: campaign.objective, targeting: null });
    return `
      <div class="card ads-node ads-node-campaign">
        <div class="acc-header" data-toggle="1">
          <span class="expand-toggle">▸</span>
          <strong>${campaign.name || I18N.t("ads.no_name")}</strong>
          ${statusBadge(campaign.status, campaign.effective_status)}
          <span class="meta">${campaign.objective_label} • ${campaign.budget_type} ${campaign.budget_type === "CBO" ? budgetLabel(campaign.budget, currency) : ""} • ${I18N.t("ads.adsets_count", { count: campaign.adsets.length })}</span>
        </div>
        <div class="detail-grid">
          <div><div class="k">${I18N.t("ads.field.objective_raw")}</div><div class="v" title="${campaign.objective || ""}">${campaign.objective || naSpan()}</div></div>
          <div><div class="k">${I18N.t("ads.field.bid_strategy")}</div><div class="v">${campaign.bid_strategy || naSpan()}</div></div>
          <div><div class="k">${I18N.t("ads.field.buying_type")}</div><div class="v">${campaign.buying_type || naSpan()}</div></div>
          <div><div class="k">${I18N.t("ads.field.schedule")}</div><div class="v">${campaign.start_time ? new Date(campaign.start_time).toLocaleDateString(I18N.locale()) : "?"} — ${campaign.stop_time ? new Date(campaign.stop_time).toLocaleDateString(I18N.locale()) : I18N.t("ads.field.no_end_date")}</div></div>
          <div style="grid-column:1/-1;"><div class="k">${I18N.t("ads.field.result_meaning")}</div><div class="v">${campaign.result_explanation}</div></div>
        </div>
        ${metricsGridHtml(campaign.metrics, currency)}
        ${resultBlockHtml(campaign.result, currency)}
        ${kpiVerdictHtml(campaign.kpi_verdicts, currency)}
        ${audiencePanelHtml(campaign.id)}
        ${recommendationsPanelHtml(campaign.id)}
        <div class="ads-children" style="display:none;">${adsetsHtml}</div>
      </div>
    `;
  }

  function attachToggleHandlers(root) {
    root.querySelectorAll(".acc-header[data-toggle]").forEach((header) => {
      header.addEventListener("click", () => {
        header.classList.toggle("expanded");
        const children = header.parentElement.querySelector(":scope > .ads-children");
        if (children) children.style.display = children.style.display === "none" ? "block" : "none";
      });
    });
  }

  function audiencePanelHtml(entityId) {
    return `
      <div class="ads-audience">
        <button class="btn secondary btn-audience-toggle" data-entity="${entityId}">${I18N.t("ads.btn.audience")}</button>
        <div class="ads-audience-content" style="display:none;"></div>
      </div>
    `;
  }

  function fatiguePanelHtml(entityId) {
    return `
      <div class="ads-audience">
        <button class="btn secondary btn-fatigue-toggle" data-entity="${entityId}">${I18N.t("ads.btn.fatigue")}</button>
        <div class="ads-fatigue-content" style="display:none;"></div>
      </div>
    `;
  }

  function placementPanelHtml(entityId) {
    return `
      <div class="ads-audience">
        <button class="btn secondary btn-placement-toggle" data-entity="${entityId}">${I18N.t("ads.btn.placement")}</button>
        <div class="ads-placement-content" style="display:none;"></div>
      </div>
    `;
  }

  function creativeVerdictPanelHtml(entityId) {
    return `
      <div class="ads-audience">
        <button class="btn secondary btn-creative-verdict-toggle" data-entity="${entityId}">${I18N.t("ads.btn.creative_verdict")}</button>
        <div class="ads-creative-verdict-content" style="display:none;"></div>
      </div>
    `;
  }

  function audienceVerdictPanelHtml(entityId) {
    return `
      <div class="ads-audience">
        <button class="btn secondary btn-audience-verdict-toggle" data-entity="${entityId}">${I18N.t("ads.btn.audience_verdict")}</button>
        <div class="ads-audience-verdict-content" style="display:none;"></div>
      </div>
    `;
  }

  function recommendationsPanelHtml(entityId) {
    return `
      <div class="ads-audience">
        <button class="btn btn-recommendations-refresh" data-entity="${entityId}">${I18N.t("ads.btn.recommendations_refresh")}</button>
        <div class="ads-recommendations-content" style="display:none;"></div>
      </div>
    `;
  }

  function breakdownTableHtml(rows, currency) {
    if (!rows || !rows.length) return `<div class="hint">${naSpan(I18N.t("ads.msg.no_data_for_period"))}</div>`;
    const sorted = [...rows].sort((a, b) => (b.metrics.spend || 0) - (a.metrics.spend || 0));
    return `
      <div class="table-scroll">
        <table>
          <thead><tr><th>${I18N.t("ads.field.segment")}</th><th>${I18N.t("ads.field.spend")}</th><th>${I18N.t("ads.field.impressions")}</th><th>CTR</th><th>CPC</th><th>${I18N.t("ads.field.result")}</th><th>${I18N.t("ads.field.cost_per_result")}</th></tr></thead>
          <tbody>
            ${sorted
              .map(
                (r) => `<tr>
              <td>${r.label}</td>
              <td>${fmtMoney(r.metrics.spend, currency)}</td>
              <td>${fmtNumber(r.metrics.impressions)}</td>
              <td>${r.metrics.ctr !== null && r.metrics.ctr !== undefined ? fmtPercent(r.metrics.ctr) : naSpan()}</td>
              <td>${fmtMoney(r.metrics.cpc, currency)}</td>
              <td>${r.result && r.result.value !== null && r.result.value !== undefined ? Number(r.result.value).toLocaleString(I18N.locale()) : naSpan(r.result && r.result.note)}</td>
              <td>${fmtMoney(r.result && r.result.cost_per_result, currency)}</td>
            </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  function audienceVerdictHtml(breakdowns, targeting, currency) {
    if (!targeting) {
      return `<div class="hint">${naSpan(I18N.t("ads.msg.compare_targeting_adset_only"))}</div>`;
    }
    const candidates = [...(breakdowns.age || []), ...(breakdowns.gender || [])].filter(
      (r) => r.metrics.spend && r.result && r.result.cost_per_result !== null && r.result.cost_per_result !== undefined
    );
    if (!candidates.length) {
      return `<div class="hint">${naSpan(I18N.t("ads.msg.not_enough_result_data"))}</div>`;
    }
    const totalSpend = candidates.reduce((s, r) => s + r.metrics.spend, 0);
    const threshold = (totalSpend / 2) * 0.05; // /2, т.к. age и gender вместе дают ~2x покрытие общего расхода
    const meaningful = candidates.filter((r) => r.metrics.spend >= threshold);
    if (!meaningful.length) {
      return `<div class="hint">${naSpan(I18N.t("ads.msg.no_segments_with_enough_spend"))}</div>`;
    }
    const cheapest = meaningful.reduce((a, b) => (b.result.cost_per_result < a.result.cost_per_result ? b : a));
    return `
      <div class="ads-result-block">
        <div>${I18N.t("ads.audience_verdict.cheapest", { label: cheapest.label, cost: fmtMoney(cheapest.result.cost_per_result, currency), spend: fmtMoney(cheapest.metrics.spend, currency) })}</div>
        <div style="margin-top:6px;">${I18N.t("ads.audience_verdict.targeting_line", { age: targeting.age, gender: targeting.gender })}</div>
        <div style="margin-top:6px;"><strong>${I18N.t("ads.audience_verdict.conclusion_label")}</strong> ${I18N.t("ads.audience_verdict.conclusion_text", { label: cheapest.label })}</div>
      </div>
    `;
  }

  function trendHtml(trend) {
    if (!trend.available) {
      return `<div class="hint">${naSpan(trend.note)}</div>`;
    }
    const rows = [
      [I18N.t("ads.field.frequency"), trend.frequency],
      ["CTR", trend.ctr],
      ["CPM", trend.cpm],
    ];
    const rowsHtml = rows
      .map(
        ([label, t]) =>
          `<div><div class="k">${label}</div><div class="v">${t.direction_label || naSpan()}${t.change_pct !== null && t.change_pct !== undefined ? ` (${t.change_pct > 0 ? "+" : ""}${t.change_pct}%)` : ""}</div></div>`
      )
      .join("");
    return `
      <div class="detail-grid">${rowsHtml}</div>
      ${trend.saturation_note ? `<div class="status-box show error" style="margin-top:10px; display:block;">${trend.saturation_note}</div>` : ""}
    `;
  }

  function renderTimeseriesCharts(containerEl, entityId, timeseries, currency) {
    if (!timeseries.length) {
      containerEl.innerHTML = `<div class="hint">${naSpan(I18N.t("ads.msg.no_data_for_period"))}</div>`;
      return;
    }
    const labels = timeseries.map((d) => new Date(d.date_start).toLocaleDateString(I18N.locale(), { day: "2-digit", month: "2-digit" }));
    const charts = [
      [I18N.t("ads.field.spend"), `spend-${entityId}`, timeseries.map((d) => d.metrics.spend), "#bd94eb"],
      [I18N.t("ads.chart.ctr_all"), `ctr-${entityId}`, timeseries.map((d) => d.metrics.ctr), "#9d6fd9"],
      ["CPM", `cpm-${entityId}`, timeseries.map((d) => d.metrics.cpm), "#6b6b6b"],
      [I18N.t("ads.field.cost_per_result"), `cost-${entityId}`, timeseries.map((d) => (d.result ? d.result.cost_per_result : null)), "#c0392b"],
    ];
    containerEl.innerHTML = `
      <div class="charts-grid">
        ${charts.map(([title, id]) => `<div class="chart-card"><h2>${title}</h2><canvas id="chart-${id}"></canvas></div>`).join("")}
      </div>
    `;
    charts.forEach(([title, id, data, color]) => {
      const canvasId = `chart-${id}`;
      if (activeCharts[canvasId]) activeCharts[canvasId].destroy();
      const ctx = document.getElementById(canvasId);
      activeCharts[canvasId] = new Chart(ctx, {
        type: "line",
        data: {
          labels,
          datasets: [
            {
              label: title,
              data,
              borderColor: color,
              backgroundColor: color + "26",
              fill: true,
              tension: 0.25,
              pointRadius: 2,
              spanGaps: true,
            },
          ],
        },
        options: {
          responsive: true,
          plugins: { legend: { display: false } },
          scales: { y: { beginAtZero: true } },
        },
      });
    });
  }

  async function loadAudiencePanel(entityId, ctx, currency, contentEl, btn) {
    const originalLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = I18N.t("ads.msg.loading");
    try {
      const params = new URLSearchParams({ entity_id: entityId, period });
      if (ctx.objective) params.set("objective", ctx.objective);
      if (ctx.optimizationGoal) params.set("optimization_goal", ctx.optimizationGoal);
      if (period === "custom") {
        params.set("date_from", dateFromInput.value);
        params.set("date_to", dateToInput.value);
      }
      const res = await fetch(`/api/ads/insights-detail?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        contentEl.innerHTML = `<div class="hint">${naSpan(data.error || I18N.t("ads.msg.load_failed"))}</div>`;
        contentEl.style.display = "block";
        return;
      }

      const breakdownsHtml = Object.entries(audienceDimLabels())
        .map(([dim, label]) => {
          const reason = data.unsupported_breakdowns[dim];
          return `
            <div style="margin-bottom:16px;">
              <h2 style="margin:0 0 8px; font-size:14px;">${label}</h2>
              ${reason ? `<div class="hint">${naSpan(reason)}</div>` : breakdownTableHtml(data.breakdowns[dim], currency)}
            </div>
          `;
        })
        .join("");

      contentEl.innerHTML = `
        <div class="ads-audience-section">
          <h2 style="font-size:14px;">${I18N.t("ads.section.saturation")}</h2>
          ${trendHtml(data.trend)}
        </div>
        <div class="ads-audience-section">
          <h2 style="font-size:14px;">${I18N.t("ads.section.real_audience_vs_targeting")}</h2>
          ${audienceVerdictHtml(data.breakdowns, ctx.targeting, currency)}
        </div>
        <div class="ads-audience-section">
          <h2 style="font-size:14px;">${I18N.t("ads.section.daily_dynamics")}</h2>
          <div class="ads-timeseries-charts"></div>
        </div>
        <div class="ads-audience-section">
          <h2 style="font-size:14px;">${I18N.t("ads.section.audience_breakdowns")}</h2>
          ${breakdownsHtml}
        </div>
      `;
      renderTimeseriesCharts(contentEl.querySelector(".ads-timeseries-charts"), entityId, data.timeseries, currency);
      contentEl.style.display = "block";
      contentEl.dataset.loaded = "1";
    } catch (e) {
      contentEl.innerHTML = `<div class="hint">${naSpan(I18N.t("common.network_error", { message: e.message }))}</div>`;
      contentEl.style.display = "block";
    } finally {
      btn.disabled = false;
      btn.textContent = originalLabel;
    }
  }

  function attachAudienceHandlers(root, currency) {
    root.querySelectorAll(".btn-audience-toggle").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const panel = btn.closest(".ads-audience");
        const contentEl = panel.querySelector(".ads-audience-content");
        if (contentEl.dataset.loaded === "1") {
          contentEl.style.display = contentEl.style.display === "none" ? "block" : "none";
          return;
        }
        const ctx = entityContext.get(btn.dataset.entity);
        await loadAudiencePanel(btn.dataset.entity, ctx, currency, contentEl, btn);
      });
    });
  }

  function fatigueFlagHtml(fatigue) {
    if (fatigue.note) {
      return `<div class="hint">${naSpan(fatigue.note)}</div>`;
    }
    if (fatigue.fatigued) {
      const date = new Date(fatigue.since_date).toLocaleDateString(I18N.locale());
      return `<div class="status-box show error">${I18N.t("ads.fatigue.detected", { date, reason: fatigue.reason })}</div>`;
    }
    return `<div class="status-box show ok">${I18N.t("ads.fatigue.not_detected")}</div>`;
  }

  function videoTrendHtml(videoTrend) {
    if (!videoTrend.available) {
      return `<div class="hint">${naSpan(videoTrend.note)}</div>`;
    }
    const rows = [
      [I18N.t("ads.field.hook_rate"), videoTrend.hook_rate],
      [I18N.t("ads.field.thruplay_rate"), videoTrend.thruplay_rate],
    ].filter(([, t]) => t.direction !== null);
    if (!rows.length) return `<div class="hint">${naSpan()}</div>`;
    return `<div class="detail-grid">${rows
      .map(
        ([label, t]) =>
          `<div><div class="k">${label}</div><div class="v">${t.direction_label}${t.change_pct !== null ? ` (${t.change_pct > 0 ? "+" : ""}${t.change_pct}%)` : ""}</div></div>`
      )
      .join("")}</div>`;
  }

  async function loadFatiguePanel(entityId, ctx, contentEl, btn) {
    const originalLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = I18N.t("ads.msg.loading");
    try {
      const params = new URLSearchParams({ entity_id: entityId, period });
      if (ctx.objective) params.set("objective", ctx.objective);
      if (period === "custom") {
        params.set("date_from", dateFromInput.value);
        params.set("date_to", dateToInput.value);
      }
      const res = await fetch(`/api/ads/fatigue?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        contentEl.innerHTML = `<div class="hint">${naSpan(data.error || I18N.t("ads.msg.load_failed"))}</div>`;
        contentEl.style.display = "block";
        return;
      }
      contentEl.innerHTML = `
        <div class="ads-audience-section">
          <h2 style="font-size:14px;">${I18N.t("ads.section.fatigue_signal")}</h2>
          ${fatigueFlagHtml(data.fatigue)}
        </div>
        <div class="ads-audience-section">
          <h2 style="font-size:14px;">${I18N.t("ads.section.video_trend")}</h2>
          ${videoTrendHtml(data.video_trend)}
        </div>
      `;
      contentEl.style.display = "block";
      contentEl.dataset.loaded = "1";
    } catch (e) {
      contentEl.innerHTML = `<div class="hint">${naSpan(I18N.t("common.network_error", { message: e.message }))}</div>`;
      contentEl.style.display = "block";
    } finally {
      btn.disabled = false;
      btn.textContent = originalLabel;
    }
  }

  function attachFatigueHandlers(root) {
    root.querySelectorAll(".btn-fatigue-toggle").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const panel = btn.closest(".ads-audience");
        const contentEl = panel.querySelector(".ads-fatigue-content");
        if (contentEl.dataset.loaded === "1") {
          contentEl.style.display = contentEl.style.display === "none" ? "block" : "none";
          return;
        }
        const ctx = entityContext.get(btn.dataset.entity);
        await loadFatiguePanel(btn.dataset.entity, ctx, contentEl, btn);
      });
    });
  }

  function placementRuleSummaryHtml(verdict, currency) {
    if (!verdict.available) {
      return `<div class="hint">${naSpan(verdict.note)}</div>`;
    }
    const metricLabel = verdict.metric_used === "cost_per_result" ? verdict.result_label : verdict.metric_used.toUpperCase();
    const fmtVal = (v) => (verdict.metric_used === "ctr" ? fmtPercent(v) : fmtMoney(v, currency));
    return `
      <div class="ads-result-block">
        <div>${I18N.t("ads.placement.best", { label: verdict.best.label, metric: metricLabel, value: fmtVal(verdict.best.value) })}</div>
        <div style="margin-top:6px;">${I18N.t("ads.placement.worst", { label: verdict.worst.label, metric: metricLabel, value: fmtVal(verdict.worst.value) })}</div>
        ${verdict.diff_pct !== null && verdict.diff_pct !== undefined ? `<div style="margin-top:6px;">${I18N.t("ads.placement.diff", { pct: verdict.diff_pct })}</div>` : ""}
        ${verdict.note ? `<div style="margin-top:6px;">${naSpan(verdict.note)}</div>` : ""}
      </div>
    `;
  }

  function placementVerdictHtml(data, currency) {
    const opusBlock = data.opus_summary
      ? `<div class="status-box show ok" style="white-space:pre-wrap;">${escapeHtml(data.opus_summary)}</div>`
      : `<div class="hint">${naSpan(data.opus_note)}</div>`;
    const modeLine = data.placement_label
      ? `<div class="hint" style="margin-bottom:10px;">${I18N.t("ads.placement.mode_prefix")}: ${escapeHtml(data.placement_label)}</div>`
      : "";
    return `
      <div class="ads-audience-section">
        <h2 style="font-size:14px;">${I18N.t("ads.section.opus_summary")}</h2>
        ${modeLine}
        ${opusBlock}
      </div>
      <div class="ads-audience-section">
        <h2 style="font-size:14px;">${I18N.t("ads.section.placement")}</h2>
        ${breakdownTableHtml(data.rows, currency)}
      </div>
      <div class="ads-audience-section">
        ${placementRuleSummaryHtml(data.verdict, currency)}
      </div>
    `;
  }

  async function loadPlacementPanel(entityId, ctx, currency, contentEl, btn) {
    const originalLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = I18N.t("ads.msg.analyzing");
    try {
      const params = new URLSearchParams({ ad_id: entityId, period });
      if (ctx.objective) params.set("objective", ctx.objective);
      if (ctx.adsetId) params.set("adset_id", ctx.adsetId);
      if (ctx.name) params.set("ad_name", ctx.name);
      if (period === "custom") {
        params.set("date_from", dateFromInput.value);
        params.set("date_to", dateToInput.value);
      }
      const res = await fetch(`/api/ads/placement-breakdown?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        contentEl.innerHTML = `<div class="hint">${naSpan(data.error || I18N.t("ads.msg.load_failed"))}</div>`;
        contentEl.style.display = "block";
        return;
      }
      contentEl.innerHTML = placementVerdictHtml(data, currency);
      contentEl.style.display = "block";
      contentEl.dataset.loaded = "1";
    } catch (e) {
      contentEl.innerHTML = `<div class="hint">${naSpan(I18N.t("common.network_error", { message: e.message }))}</div>`;
      contentEl.style.display = "block";
    } finally {
      btn.disabled = false;
      btn.textContent = originalLabel;
    }
  }

  function attachPlacementHandlers(root, currency) {
    root.querySelectorAll(".btn-placement-toggle").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const panel = btn.closest(".ads-audience");
        const contentEl = panel.querySelector(".ads-placement-content");
        if (contentEl.dataset.loaded === "1") {
          contentEl.style.display = contentEl.style.display === "none" ? "block" : "none";
          return;
        }
        const ctx = entityContext.get(btn.dataset.entity);
        await loadPlacementPanel(btn.dataset.entity, ctx, currency, contentEl, btn);
      });
    });
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str === null || str === undefined ? "" : str;
    return div.innerHTML;
  }

  const VERDICT_BADGE_CLASS = {
    audience_working: "verdict-good",
    narrow_to_segment: "verdict-neutral",
    wrong_change_to: "verdict-bad",
    not_audience_its_creative: "verdict-bad",
    insufficient_data: "verdict-neutral",
  };

  function adsDiagnosticsTableHtml(adsDiagnostics, currency) {
    if (!adsDiagnostics || !adsDiagnostics.length) return `<div class="hint">${naSpan(I18N.t("ads.msg.no_ads_in_adset"))}</div>`;
    return `
      <div class="table-scroll">
        <table>
          <thead><tr><th>${I18N.t("ads.field.ad")}</th><th>CTR</th><th>${I18N.t("ads.field.spend")}</th><th>${I18N.t("ads.field.result")}</th><th>Quality</th><th>Engagement</th><th>Conversion</th></tr></thead>
          <tbody>
            ${adsDiagnostics
              .map((ad) => {
                const m = ad.metrics || {};
                const r = ad.result || {};
                const rk = ad.rankings || {};
                return `<tr>
                <td>${escapeHtml(ad.name) || I18N.t("ads.no_name")}</td>
                <td>${m.ctr !== null && m.ctr !== undefined ? fmtPercent(m.ctr) : naSpan()}</td>
                <td>${fmtMoney(m.spend, currency)}</td>
                <td>${r.value !== null && r.value !== undefined ? Number(r.value).toLocaleString(I18N.locale()) : naSpan(r.note)}</td>
                <td>${rk.quality || naSpan()}</td>
                <td>${rk.engagement_rate || naSpan()}</td>
                <td>${rk.conversion_rate || naSpan()}</td>
              </tr>`;
              })
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  function audienceVerdictContentHtml(data, currency) {
    const v = data.verdict;
    const cls = VERDICT_BADGE_CLASS[v.verdict] || "verdict-neutral";
    const reasoningHtml = v.reasoning.map((r) => `<li>${escapeHtml(r)}</li>`).join("");
    const opusBlock = data.opus_summary
      ? `<div class="status-box show ok" style="white-space:pre-wrap;">${escapeHtml(data.opus_summary)}</div>`
      : `<div class="hint">${naSpan(data.opus_note)}</div>`;
    return `
      <div class="ads-audience-section">
        <span class="verdict-badge ${cls}" style="font-size:14px; padding:8px 14px;">${escapeHtml(v.verdict_label)}</span>
      </div>
      <div class="ads-audience-section">
        <h2 style="font-size:14px;">${I18N.t("ads.section.reasoning")}</h2>
        <ul class="rec-list">${reasoningHtml}</ul>
        <div class="hint" style="margin-top:8px;">${I18N.t("ads.learning_stage")}: ${data.learning_stage || naSpan()}</div>
      </div>
      <div class="ads-audience-section">
        <h2 style="font-size:14px;">${I18N.t("ads.section.opus_summary")}</h2>
        ${opusBlock}
      </div>
      <div class="ads-audience-section">
        <h2 style="font-size:14px;">${I18N.t("ads.section.ads_in_adset")}</h2>
        ${adsDiagnosticsTableHtml(data.ads_diagnostics, currency)}
      </div>
    `;
  }

  async function loadAudienceVerdictPanel(entityId, ctx, currency, contentEl, btn) {
    const originalLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = I18N.t("ads.msg.analyzing");
    try {
      const params = new URLSearchParams({ adset_id: entityId, period });
      if (ctx.objective) params.set("objective", ctx.objective);
      if (period === "custom") {
        params.set("date_from", dateFromInput.value);
        params.set("date_to", dateToInput.value);
      }
      const res = await fetch(`/api/ads/audience-verdict?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        contentEl.innerHTML = `<div class="hint">${naSpan(data.error || I18N.t("ads.msg.load_failed"))}</div>`;
        contentEl.style.display = "block";
        return;
      }
      contentEl.innerHTML = audienceVerdictContentHtml(data, currency);
      contentEl.style.display = "block";
      contentEl.dataset.loaded = "1";
    } catch (e) {
      contentEl.innerHTML = `<div class="hint">${naSpan(I18N.t("common.network_error", { message: e.message }))}</div>`;
      contentEl.style.display = "block";
    } finally {
      btn.disabled = false;
      btn.textContent = originalLabel;
    }
  }

  function attachAudienceVerdictHandlers(root, currency) {
    root.querySelectorAll(".btn-audience-verdict-toggle").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const panel = btn.closest(".ads-audience");
        const contentEl = panel.querySelector(".ads-audience-verdict-content");
        if (contentEl.dataset.loaded === "1") {
          contentEl.style.display = contentEl.style.display === "none" ? "block" : "none";
          return;
        }
        const ctx = entityContext.get(btn.dataset.entity);
        await loadAudienceVerdictPanel(btn.dataset.entity, ctx, currency, contentEl, btn);
      });
    });
  }

  // Ті самі 5 категорій хука, що app/transcription.py::classify_hook / hooks.js — невеликий
  // локальний дублікат мапи класів-для-бейджа (переклад міток бере глобальний hookTypeLabel()
  // з app.js), так само, як хуки/аудиторія вже дублюють короткі локальні мапи в цьому файлі.
  const HOOK_TYPE_CLASS = {
    "вопрос": "hook-question",
    "боль": "hook-pain",
    "провокация": "hook-provocation",
    "цифра": "hook-number",
    "утверждение": "hook-other",
  };
  const HUNT_TEMP_CLASS = { "холодная": "hunt-cold", "тёплая": "hunt-warm", "горячая": "hunt-hot" };

  function hookBadgeInline(type) {
    if (!type) return "";
    const cls = HOOK_TYPE_CLASS[type] || "hook-other";
    return `<span class="badge ${cls}">${hookTypeLabel(type)}</span>`;
  }

  function huntBadgeInline(tr) {
    if (!tr.hunt_stage && !tr.hunt_temperature) return "";
    const undetermined = "не определено";
    const stageOk = tr.hunt_stage && tr.hunt_stage !== undetermined;
    const tempOk = tr.hunt_temperature && tr.hunt_temperature !== undetermined;
    const tempCls = tempOk ? HUNT_TEMP_CLASS[tr.hunt_temperature] || "hunt-unknown" : "hunt-unknown";
    const stageBadge = `<span class="badge hunt-unknown">${stageOk ? huntStageLabel(tr.hunt_stage) : I18N.t("hooks.hunt.undetermined")}</span>`;
    const tempBadge = tempOk ? `<span class="badge ${tempCls}" style="margin-left:4px;">${huntTempLabel(tr.hunt_temperature)}</span>` : "";
    return `${stageBadge}${tempBadge}`;
  }

  const CREATIVE_COMPONENT_SYMBOL = { better: "✓", worse: "✕", near: "≈" };
  const CREATIVE_COMPONENT_CLASS = { better: "verdict-good", worse: "verdict-bad", near: "verdict-neutral" };

  function componentCardHtml(c) {
    const badge = c.class
      ? `<span class="verdict-badge ${CREATIVE_COMPONENT_CLASS[c.class]}">${CREATIVE_COMPONENT_SYMBOL[c.class]}</span>`
      : `<span class="verdict-badge verdict-neutral">${I18N.t("common.no_data")}</span>`;
    return `
      <div class="ads-result-block" style="margin-bottom:8px;">
        <div style="display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:4px;">
          <strong>${escapeHtml(c.label)}</strong>
          ${badge}
        </div>
        <div class="hint">${escapeHtml(c.reasoning)}</div>
      </div>
    `;
  }

  function transcriptBlockHtml(data) {
    const tr = data.transcript;
    if (!tr) {
      const btn = data.source_instagram_media_id
        ? `<div style="margin-top:8px;"><button class="btn secondary btn-transcribe-for-verdict" data-media-id="${data.source_instagram_media_id}">${I18N.t("hooks.transcribe_one_btn")}</button></div>`
        : "";
      return `<div class="hint">${naSpan(I18N.t("ads.msg.no_transcript"))}</div>${btn}`;
    }
    return `
      <div class="ads-result-block">
        <div>${escapeHtml(tr.hook_text || "")}</div>
        <div style="margin-top:6px;">${hookBadgeInline(tr.hook_type)} ${huntBadgeInline(tr)}</div>
        ${tr.low_confidence ? `<div class="hint" style="margin-top:6px;">${naSpan(tr.quality_reason)}</div>` : ""}
      </div>
    `;
  }

  const CREATIVE_VERDICT_BADGE_CLASS = { good: "verdict-good", bad: "verdict-bad", neutral: "verdict-neutral", insufficient_data: "verdict-neutral" };

  function creativeVerdictContentHtml(data) {
    const v = data.verdict;
    const cls = CREATIVE_VERDICT_BADGE_CLASS[v.verdict] || "verdict-neutral";
    const componentsHtml = Object.values(v.components).map(componentCardHtml).join("");
    const opusBlock = data.opus_summary
      ? `<div class="status-box show ok" style="white-space:pre-wrap;">${escapeHtml(data.opus_summary)}</div>`
      : `<div class="hint">${naSpan(data.opus_note)}</div>`;
    return `
      <div class="ads-audience-section">
        <span class="verdict-badge ${cls}" style="font-size:14px; padding:8px 14px;">${escapeHtml(v.verdict_label)}</span>
      </div>
      <div class="ads-audience-section">
        <h2 style="font-size:14px;">${I18N.t("ads.section.creative_components")}</h2>
        ${componentsHtml}
      </div>
      <div class="ads-audience-section">
        <h2 style="font-size:14px;">${I18N.t("ads.section.creative_transcript")}</h2>
        ${transcriptBlockHtml(data)}
      </div>
      <div class="ads-audience-section">
        <h2 style="font-size:14px;">${I18N.t("ads.section.opus_summary")}</h2>
        ${opusBlock}
      </div>
    `;
  }

  function attachTranscribeHandler(contentEl, entityId, ctx, toggleBtn) {
    const transcribeBtn = contentEl.querySelector(".btn-transcribe-for-verdict");
    if (!transcribeBtn) return;
    transcribeBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const mediaId = transcribeBtn.dataset.mediaId;
      const original = transcribeBtn.textContent;
      transcribeBtn.disabled = true;
      transcribeBtn.textContent = I18N.t("ads.msg.transcribing");
      try {
        const res = await fetch(`/api/hooks/transcribe/${mediaId}`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) {
          alert(data.error || I18N.t("ads.msg.load_failed"));
          transcribeBtn.disabled = false;
          transcribeBtn.textContent = original;
          return;
        }
        contentEl.dataset.loaded = "";
        await loadCreativeVerdictPanel(entityId, ctx, contentEl, toggleBtn);
      } catch (err) {
        alert(I18N.t("common.network_error", { message: err.message }));
        transcribeBtn.disabled = false;
        transcribeBtn.textContent = original;
      }
    });
  }

  async function loadCreativeVerdictPanel(entityId, ctx, contentEl, btn) {
    const originalLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = I18N.t("ads.msg.analyzing");
    try {
      const params = new URLSearchParams({ ad_id: entityId, adset_id: ctx.adsetId, period });
      if (ctx.objective) params.set("objective", ctx.objective);
      if (period === "custom") {
        params.set("date_from", dateFromInput.value);
        params.set("date_to", dateToInput.value);
      }
      const res = await fetch(`/api/ads/creative-verdict?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        contentEl.innerHTML = `<div class="hint">${naSpan(data.error || I18N.t("ads.msg.load_failed"))}</div>`;
        contentEl.style.display = "block";
        return;
      }
      contentEl.innerHTML = creativeVerdictContentHtml(data);
      attachTranscribeHandler(contentEl, entityId, ctx, btn);
      contentEl.style.display = "block";
      contentEl.dataset.loaded = "1";
    } catch (e) {
      contentEl.innerHTML = `<div class="hint">${naSpan(I18N.t("common.network_error", { message: e.message }))}</div>`;
      contentEl.style.display = "block";
    } finally {
      btn.disabled = false;
      btn.textContent = originalLabel;
    }
  }

  function attachCreativeVerdictHandlers(root) {
    root.querySelectorAll(".btn-creative-verdict-toggle").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const panel = btn.closest(".ads-audience");
        const contentEl = panel.querySelector(".ads-creative-verdict-content");
        if (contentEl.dataset.loaded === "1") {
          contentEl.style.display = contentEl.style.display === "none" ? "block" : "none";
          return;
        }
        const ctx = entityContext.get(btn.dataset.entity);
        await loadCreativeVerdictPanel(btn.dataset.entity, ctx, contentEl, btn);
      });
    });
  }

  function recommendationsContentHtml(data) {
    return `
      <div class="ads-audience-section">
        <div class="script-text" style="white-space:pre-wrap;">${escapeHtml(data.recommendations)}</div>
      </div>
      <div class="ads-audience-section">
        <details>
          <summary style="cursor:pointer; font-size:12.5px; color:var(--muted);">${I18N.t("ads.recommendations.show_context")}</summary>
          <pre style="white-space:pre-wrap; font-size:11.5px; margin-top:8px; color:var(--muted);">${escapeHtml(data.context_used)}</pre>
        </details>
      </div>
    `;
  }

  async function loadRecommendationsPanel(entityId, contentEl, btn) {
    const originalLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = I18N.t("ads.msg.collecting_recommendations");
    contentEl.innerHTML = `<div class="hint">${I18N.t("ads.msg.opus_analyzing")}</div>`;
    contentEl.style.display = "block";
    try {
      const params = new URLSearchParams({ campaign_id: entityId, period });
      if (period === "custom") {
        params.set("date_from", dateFromInput.value);
        params.set("date_to", dateToInput.value);
      }
      const res = await fetch(`/api/ads/recommendations?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        contentEl.innerHTML = `<div class="hint">${naSpan(data.error || I18N.t("ads.msg.load_failed"))}</div>`;
        return;
      }
      contentEl.innerHTML = recommendationsContentHtml(data);
    } catch (e) {
      contentEl.innerHTML = `<div class="hint">${naSpan(I18N.t("common.network_error", { message: e.message }))}</div>`;
    } finally {
      btn.disabled = false;
      btn.textContent = originalLabel;
    }
  }

  function attachRecommendationsHandlers(root) {
    root.querySelectorAll(".btn-recommendations-refresh").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const panel = btn.closest(".ads-audience");
        const contentEl = panel.querySelector(".ads-recommendations-content");
        await loadRecommendationsPanel(btn.dataset.entity, contentEl, btn);
      });
    });
  }

  function renderRawTable(campaigns, currency) {
    const top = [...campaigns].sort((a, b) => (b.metrics.spend || 0) - (a.metrics.spend || 0)).slice(0, 2);
    const cols = [
      [I18N.t("ads.field.campaign"), (c) => c.name],
      [I18N.t("ads.field.spend"), (c) => fmtMoney(c.metrics.spend, currency)],
      [I18N.t("ads.field.impressions"), (c) => fmtNumber(c.metrics.impressions)],
      [I18N.t("ads.field.reach"), (c) => fmtNumber(c.metrics.reach)],
      [I18N.t("ads.field.frequency"), (c) => fmtRatio(c.metrics.frequency)],
      ["CPM", (c) => fmtMoney(c.metrics.cpm, currency)],
      [I18N.t("ads.field.clicks"), (c) => fmtNumber(c.metrics.clicks)],
      [I18N.t("ads.field.link_clicks"), (c) => fmtNumber(c.metrics.link_clicks)],
      ["CTR", (c) => (c.metrics.ctr !== null && c.metrics.ctr !== undefined ? fmtPercent(c.metrics.ctr) : naSpan())],
      [I18N.t("ads.field.ctr_link"), (c) => (c.metrics.ctr_link !== null && c.metrics.ctr_link !== undefined ? fmtPercent(c.metrics.ctr_link) : naSpan())],
      ["CPC", (c) => fmtMoney(c.metrics.cpc, currency)],
      [I18N.t("ads.field.result"), (c) => (c.result.value !== null && c.result.value !== undefined ? `${c.result.label}: ${Number(c.result.value).toLocaleString(I18N.locale())}` : naSpan(c.result.note))],
      [I18N.t("ads.field.cost_per_result"), (c) => fmtMoney(c.result.cost_per_result, currency)],
      ["ROAS", (c) => (c.result.roas !== null && c.result.roas !== undefined ? `${c.result.roas.toFixed(2)}x` : naSpan())],
      [I18N.t("ads.field.video_3s_short"), (c) => fmtNumber(c.metrics.video_3s_views)],
      ["ThruPlay", (c) => fmtNumber(c.metrics.thruplay)],
    ];

    const thead = rawTable.querySelector("thead");
    const tbody = rawTable.querySelector("tbody");
    thead.innerHTML = `<tr>${cols.map(([label]) => `<th>${label}</th>`).join("")}</tr>`;
    tbody.innerHTML = top
      .map((c) => `<tr>${cols.map(([, fn]) => `<td>${fn(c)}</td>`).join("")}</tr>`)
      .join("") || `<tr><td colspan="${cols.length}" class="na">${I18N.t("ads.msg.no_campaigns_for_period")}</td></tr>`;
  }

  function render(data) {
    lastData = data;
    const currency = data.account.currency;

    accountCard.innerHTML = `
      <h2 style="margin:0 0 10px;">${data.account.name} <span class="badge status-active" style="margin-left:6px;">${data.account.account_status_label}</span></h2>
      <div class="detail-grid">
        <div><div class="k">${I18N.t("ads.field.account_id")}</div><div class="v">${data.account.id}</div></div>
        <div><div class="k">${I18N.t("ads.field.currency")}</div><div class="v">${currency}</div></div>
        <div><div class="k">${I18N.t("ads.field.timezone")}</div><div class="v">${data.account.timezone_name || naSpan()}</div></div>
        <div><div class="k">${I18N.t("ads.field.amount_spent")}</div><div class="v">${fmtMoney(data.account.amount_spent, currency)}</div></div>
        <div><div class="k">${I18N.t("ads.field.balance")}</div><div class="v">${data.account.balance != null ? fmtMoney(data.account.balance, currency) : naSpan()}</div></div>
        <div><div class="k">${I18N.t("ads.field.spend_cap")}</div><div class="v">${data.account.spend_cap != null ? fmtMoney(data.account.spend_cap, currency) : naSpan()}</div></div>
      </div>
    `;

    renderRawTable(data.campaigns, currency);
    rawMeta.textContent = I18N.t("ads.raw.meta", { period: periodLabel(data) })
      + (data.period === "today" ? ` — ${I18N.t("ads.period.today_delay_note")}` : "");

    entityContext.clear();
    const syncedLabel = data.synced_at
      ? I18N.t("ads.msg.loaded_at", { time: new Date(data.synced_at).toLocaleTimeString(I18N.locale(), { hour: "2-digit", minute: "2-digit" }) })
      : "";
    structureMeta.textContent = I18N.t("ads.structure_meta", { count: data.campaigns.length, period: periodLabel(data) }) + (syncedLabel ? ` • ${syncedLabel}` : "");
    campaignsEl.innerHTML = data.campaigns.map((c) => campaignHtml(c, currency)).join("") ||
      `<div class="empty-state">${I18N.t("ads.msg.no_campaigns_found")}</div>`;
    attachToggleHandlers(campaignsEl);
    attachAudienceHandlers(campaignsEl, currency);
    attachFatigueHandlers(campaignsEl);
    attachPlacementHandlers(campaignsEl, currency);
    attachAudienceVerdictHandlers(campaignsEl, currency);
    attachRecommendationsHandlers(campaignsEl);
    attachCreativeVerdictHandlers(campaignsEl);

    content.style.display = "block";
    emptyState.style.display = "none";
    updateAdsAgo();
  }

  function updateAdsAgo() {
    updatedAgo.textContent = lastData && lastData.synced_at ? timeAgoText(lastData.synced_at) : "";
  }

  function periodLabel(data) {
    const labels = {
      today: I18N.t("ads.period.today"),
      last_7d: I18N.t("ads.period.last_7d"),
      last_14d: I18N.t("ads.period.last_14d"),
      last_30d: I18N.t("ads.period.last_30d"),
      maximum: I18N.t("ads.period.maximum"),
    };
    if (data.period === "custom") return `${data.date_from} — ${data.date_to}`;
    return labels[data.period] || data.period;
  }

  loadBtn.addEventListener("click", async () => {
    loadBtn.disabled = true;
    loadBtn.textContent = I18N.t("ads.msg.loading");
    meta.textContent = I18N.t("ads.msg.loading_structure");
    try {
      const params = new URLSearchParams({ period });
      if (period === "custom") {
        if (!dateFromInput.value || !dateToInput.value) {
          meta.textContent = I18N.t("ads.msg.specify_both_dates");
          return;
        }
        params.set("date_from", dateFromInput.value);
        params.set("date_to", dateToInput.value);
      }
      const res = await fetch(`/api/ads/structure?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        meta.textContent = I18N.t("common.error") + ": " + (data.error || I18N.t("ads.msg.load_failed"));
        content.style.display = "none";
        emptyState.style.display = "block";
        return;
      }
      meta.textContent = I18N.t("ads.msg.loaded_at", { time: new Date().toLocaleTimeString(I18N.locale()) });
      render(data);
    } catch (e) {
      meta.textContent = I18N.t("common.network_error", { message: e.message });
    } finally {
      loadBtn.disabled = false;
      loadBtn.textContent = I18N.t("ads.load_btn");
    }
  });

  function fillKpiInputs(objective) {
    const saved = kpiState.targets[objective] || {};
    Object.entries(kpiInputs).forEach(([field, input]) => {
      const val = saved[field];
      input.value = val === null || val === undefined ? "" : val;
    });
  }

  function renderKpiSavedList() {
    const entries = Object.entries(kpiState.targets).filter(([, t]) => Object.values(t).some((v) => v !== null && v !== undefined));
    if (!entries.length) {
      kpiSavedList.innerHTML = `<div class="hint">${I18N.t("ads.kpi.nothing_saved")}</div>`;
      return;
    }
    const labels = { target_cpl: "CPL", target_cpm: "CPM", target_ctr: "CTR", target_roas: "ROAS", target_cost_per_result: I18N.t("ads.field.cost_per_result") };
    kpiSavedList.innerHTML = `
      <div class="table-scroll">
        <table>
          <thead><tr><th>${I18N.t("ads.kpi.objective_th")}</th>${Object.values(labels).map((l) => `<th>${l}</th>`).join("")}<th></th></tr></thead>
          <tbody>
            ${entries
              .map(
                ([objective, t]) => `<tr>
              <td>${kpiState.objectives[objective] || objective}</td>
              ${Object.keys(labels).map((f) => `<td>${t[f] !== null && t[f] !== undefined ? t[f] : naSpan(I18N.t("ads.kpi.not_set"))}</td>`).join("")}
              <td><button class="icon-btn kpi-del-btn" data-objective="${objective}" title="${I18N.t("ads.kpi.delete_btn")}">✕</button></td>
            </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  kpiSavedList.addEventListener("click", async (e) => {
    const btn = e.target.closest(".kpi-del-btn");
    if (!btn) return;
    if (!confirm(I18N.t("ads.kpi.confirm_delete"))) return;
    const objective = btn.dataset.objective;
    btn.disabled = true;
    try {
      const res = await fetch(`/api/ads/kpi-targets/${encodeURIComponent(objective)}`, { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        alert(data.error || I18N.t("ads.kpi.msg.delete_error"));
        btn.disabled = false;
        return;
      }
      delete kpiState.targets[objective];
      renderKpiSavedList();
    } catch (err) {
      alert(I18N.t("common.network_error", { message: err.message }));
      btn.disabled = false;
    }
  });

  function renderKpiBenchmarks() {
    kpiBenchmarksEl.innerHTML = Object.entries(kpiState.benchmarks)
      .map(([metric, text]) => `<li><strong>${metric}:</strong> ${text}</li>`)
      .join("");
  }

  async function initKpiCard() {
    try {
      const res = await fetch("/api/ads/kpi-targets");
      const data = await res.json();
      kpiState = data;
      kpiObjectiveSelect.innerHTML = Object.entries(data.objectives)
        .map(([value, label]) => `<option value="${value}">${label}</option>`)
        .join("");
      fillKpiInputs(kpiObjectiveSelect.value);
      renderKpiSavedList();
      renderKpiBenchmarks();
    } catch (e) {
      kpiSaveStatus.textContent = I18N.t("ads.kpi.load_failed", { message: e.message });
    }
  }

  kpiObjectiveSelect.addEventListener("change", () => fillKpiInputs(kpiObjectiveSelect.value));

  kpiSaveBtn.addEventListener("click", async () => {
    kpiSaveBtn.disabled = true;
    kpiSaveStatus.textContent = I18N.t("generator.msg.saving");
    try {
      const body = { objective: kpiObjectiveSelect.value };
      Object.entries(kpiInputs).forEach(([field, input]) => {
        body[field] = input.value === "" ? null : parseFloat(input.value);
      });
      const res = await fetch("/api/ads/kpi-targets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        kpiSaveStatus.textContent = I18N.t("common.error") + ": " + (data.error || I18N.t("ads.kpi.save_failed"));
        return;
      }
      kpiState.targets[data.objective] = data.targets;
      renderKpiSavedList();
      kpiSaveStatus.textContent = I18N.t("common.saved_ok");
      setTimeout(() => (kpiSaveStatus.textContent = ""), 2500);
    } catch (e) {
      kpiSaveStatus.textContent = I18N.t("common.network_error", { message: e.message });
    } finally {
      kpiSaveBtn.disabled = false;
    }
  });

  document.addEventListener("langchange", () => {
    initKpiCard();
    if (lastData) render(lastData);
  });

  // Снимок фонового авто-обновления (см. app/scheduler.py, всегда период "maximum") — сразу
  // показываем его при открытии вкладки, чтобы не ждать ручного клика по «Загрузить».
  async function loadCachedAds() {
    try {
      const res = await fetch("/api/ads/cached");
      const data = await res.json();
      if (!data || !data.campaigns || !data.campaigns.length) return;
      if (lastData && lastData.synced_at === data.synced_at) return;
      render(data);
    } catch (e) {
      // тихо: это просто попытка подхватить фоновый снимок, кнопка «Загрузить» всегда доступна
    }
  }

  initKpiCard();
  loadCachedAds();

  setInterval(updateAdsAgo, 30 * 1000);
  // Перезаписываем экран только если сейчас показан период "maximum" (тот же, что и у
  // фонового авто-обновления) — иначе это перетёрло бы ручной просмотр другого периода.
  setInterval(() => {
    if (period === "maximum" && !loadBtn.disabled) loadCachedAds();
  }, 5 * 60 * 1000);
})();
