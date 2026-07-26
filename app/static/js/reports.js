(function () {
  const collectBtn = document.getElementById("btn-collect-report");
  const exportBtn = document.getElementById("btn-export-excel");
  const statusEl = document.getElementById("report-status");
  const latestBox = document.getElementById("report-latest");
  const totalsBox = document.getElementById("report-totals");
  const campaignsBox = document.getElementById("report-campaigns");
  const historyTable = document.getElementById("report-history-table");
  const historyBody = document.getElementById("report-history-body");
  const historyEmpty = document.getElementById("report-history-empty");

  const VERDICT_CLASS = { success: "verdict-good", fail: "verdict-bad", ok: "verdict-neutral" };
  const VERDICT_LABEL = { success: I18N.t("verdict.good"), fail: I18N.t("verdict.bad"), ok: I18N.t("verdict.neutral") };

  function fmtMoney(value) {
    return value === null || value === undefined ? I18N.t("common.no_data") : Number(value).toLocaleString(I18N.locale());
  }

  function renderReport(report) {
    if (!report || !report.campaigns) {
      latestBox.style.display = "none";
      return;
    }
    latestBox.style.display = "block";

    if (!report.campaigns.length) {
      totalsBox.innerHTML = `<div>${report.note || I18N.t("reports.no_active_campaigns")}</div>`;
      campaignsBox.innerHTML = "";
      return;
    }

    totalsBox.innerHTML = `
      <div><div class="subtitle" data-i18n="reports.totals.spend">${I18N.t("reports.totals.spend")}</div><div style="font-size:24px; color:var(--accent);">${fmtMoney(report.totals.spend)}</div></div>
      <div><div class="subtitle" data-i18n="reports.totals.campaigns">${I18N.t("reports.totals.campaigns")}</div><div style="font-size:24px; color:var(--accent);">${report.totals.campaigns_count}</div></div>
    `;

    campaignsBox.innerHTML = report.campaigns
      .map((c) => {
        const badges = (c.verdicts || [])
          .map((v) => `<span class="verdict-badge ${VERDICT_CLASS[v.verdict] || "verdict-neutral"}">${v.metric}: ${VERDICT_LABEL[v.verdict] || v.verdict}</span>`)
          .join(" ");
        const metrics = c.metrics;
        const result = c.result;
        const metricsLine = metrics
          ? `${I18N.t("reports.col.spend")}: ${fmtMoney(metrics.spend)} · CTR: ${metrics.ctr ?? I18N.t("common.no_data")}% · CPM: ${fmtMoney(metrics.cpm)}`
          : I18N.t("reports.no_data_today");
        const resultLine = result && result.value !== null && result.value !== undefined
          ? `${result.label}: ${result.value} (${I18N.t("reports.col.cost_per_result")}: ${fmtMoney(result.cost_per_result)})`
          : (result && result.note) || "";

        return `
          <div class="card" style="margin-bottom:14px; background:var(--bg-elevated-2);">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
              <strong>${c.name}</strong>
              <span class="subtitle">${c.objective_label}</span>
            </div>
            <div style="margin-top:8px; font-size:13px; color:var(--muted);">${metricsLine}</div>
            <div style="margin-top:4px; font-size:13px; color:var(--muted);">${resultLine}</div>
            <div style="margin-top:10px;">${badges}</div>
            <div class="verdict-reason">${c.recommendation}</div>
          </div>
        `;
      })
      .join("");
  }

  function renderHistory(days) {
    if (!days || !days.length) {
      historyTable.style.display = "none";
      historyEmpty.style.display = "block";
      return;
    }
    historyTable.style.display = "table";
    historyEmpty.style.display = "none";

    const rows = [];
    days.forEach((day) => {
      if (!day.campaigns || !day.campaigns.length) {
        rows.push(`<tr><td>${day.date}</td><td colspan="6">${day.note || I18N.t("reports.no_active_campaigns")}</td></tr>`);
        return;
      }
      day.campaigns.forEach((c) => {
        const result = c.result || {};
        const spend = c.metrics ? c.metrics.spend : null;
        const spendCls = spend === null || spend === undefined ? "" : "";
        rows.push(`
          <tr>
            <td>${day.date}</td>
            <td>${c.name}</td>
            <td>${c.objective_label}</td>
            <td class="${spendCls}">${fmtMoney(spend)}</td>
            <td>${result.value !== null && result.value !== undefined ? `${result.label}: ${result.value}` : I18N.t("common.no_data")}</td>
            <td>${fmtMoney(result.cost_per_result)}</td>
            <td>${c.recommendation || ""}</td>
          </tr>
        `);
      });
    });
    historyBody.innerHTML = rows.join("");
  }

  async function loadHistory() {
    const res = await fetch("/api/reports/history");
    const data = await res.json();
    renderHistory(data.days || []);
    if (data.days && data.days.length) {
      renderReport(data.days[0]);
    }
  }

  collectBtn.addEventListener("click", async () => {
    collectBtn.disabled = true;
    collectBtn.textContent = I18N.t("reports.collecting");
    statusEl.textContent = "";
    try {
      const res = await fetch("/api/reports/collect", { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        statusEl.textContent = data.error || I18N.t("reports.no_keys");
        return;
      }
      renderReport(data);
      await loadHistory();
      statusEl.textContent = I18N.t("common.saved_ok");
      setTimeout(() => (statusEl.textContent = ""), 2500);
    } catch (e) {
      statusEl.textContent = I18N.t("common.network_error", { message: e.message });
    } finally {
      collectBtn.disabled = false;
      collectBtn.textContent = I18N.t("reports.collect_btn");
    }
  });

  exportBtn.addEventListener("click", async () => {
    exportBtn.disabled = true;
    try {
      const res = await fetch("/api/reports/export-excel");
      if (!res.ok) {
        const data = await res.json();
        statusEl.textContent = data.error || I18N.t("reports.msg.no_history_to_export");
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "daily_ads_report.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      statusEl.textContent = I18N.t("common.network_error", { message: e.message });
    } finally {
      exportBtn.disabled = false;
    }
  });

  loadHistory();

  // --- Отчёт по прошлым кампаниям (неактивные/завершённые/на паузе) ---

  const pastStatusBtns = document.querySelectorAll(".past-status-btn");
  const pastPeriodBtns = document.querySelectorAll(".past-period-btn");
  const pastCustomRange = document.getElementById("past-custom-range");
  const pastDateFromInput = document.getElementById("past-date-from");
  const pastDateToInput = document.getElementById("past-date-to");
  const pastCollectBtn = document.getElementById("btn-collect-past-report");
  const pastExportBtn = document.getElementById("btn-export-past-excel");
  const pastStatusEl = document.getElementById("past-report-status");
  const pastLatestBox = document.getElementById("past-report-latest");
  const pastTotalsBox = document.getElementById("past-report-totals");
  const pastCampaignsBox = document.getElementById("past-report-campaigns");
  const pastHistoryTable = document.getElementById("past-report-history-table");
  const pastHistoryBody = document.getElementById("past-report-history-body");
  const pastHistoryEmpty = document.getElementById("past-report-history-empty");

  let pastStatusFilter = "all";
  let pastPeriod = "last_30d";

  pastStatusBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      pastStatusBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      pastStatusFilter = btn.dataset.status;
    });
  });

  pastPeriodBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      pastPeriodBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      pastPeriod = btn.dataset.period;
      pastCustomRange.style.display = pastPeriod === "custom" ? "inline-flex" : "none";
    });
  });

  function pastStatusBadgeClass(effectiveStatus) {
    const s = (effectiveStatus || "").toUpperCase();
    if (s === "ACTIVE") return "status-active";
    if (["DISAPPROVED", "WITH_ISSUES", "PENDING_BILLING_INFO"].includes(s)) return "status-issue";
    return "status-paused";
  }

  function renderPastReport(report) {
    if (!report || !report.campaigns) {
      pastLatestBox.style.display = "none";
      return;
    }
    pastLatestBox.style.display = "block";

    if (!report.campaigns.length) {
      pastTotalsBox.innerHTML = `<div>${I18N.t("reports.past.no_campaigns_for_filter")}</div>`;
      pastCampaignsBox.innerHTML = "";
      return;
    }

    pastTotalsBox.innerHTML = `
      <div><div class="subtitle">${I18N.t("reports.totals.spend")}</div><div style="font-size:24px; color:var(--accent);">${fmtMoney(report.totals.spend)}</div></div>
      <div><div class="subtitle">${I18N.t("reports.past.totals.campaigns")}</div><div style="font-size:24px; color:var(--accent);">${report.totals.campaigns_count}</div></div>
    `;

    pastCampaignsBox.innerHTML = report.campaigns
      .map((c) => {
        const badges = (c.verdicts || [])
          .map((v) => `<span class="verdict-badge ${VERDICT_CLASS[v.verdict] || "verdict-neutral"}">${v.metric}: ${VERDICT_LABEL[v.verdict] || v.verdict}</span>`)
          .join(" ");
        const metrics = c.metrics;
        const result = c.result;
        const metricsLine = metrics
          ? `${I18N.t("reports.col.spend")}: ${fmtMoney(metrics.spend)} · CTR: ${metrics.ctr ?? I18N.t("common.no_data")}% · CPM: ${fmtMoney(metrics.cpm)}`
          : I18N.t("reports.no_data_today");
        const resultLine = result && result.value !== null && result.value !== undefined
          ? `${result.label}: ${result.value} (${I18N.t("reports.col.cost_per_result")}: ${fmtMoney(result.cost_per_result)})`
          : (result && result.note) || "";

        return `
          <div class="card" style="margin-bottom:14px; background:var(--bg-elevated-2);">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
              <strong>${c.name}</strong>
              <span style="display:flex; gap:8px; align-items:center;">
                <span class="badge ${pastStatusBadgeClass(c.effective_status)}">${c.effective_status || c.status || "?"}</span>
                <span class="subtitle">${c.objective_label}</span>
              </span>
            </div>
            <div style="margin-top:8px; font-size:13px; color:var(--muted);">${metricsLine}</div>
            <div style="margin-top:4px; font-size:13px; color:var(--muted);">${resultLine}</div>
            <div style="margin-top:10px;">${badges}</div>
            <div class="verdict-reason">${c.recommendation}</div>
          </div>
        `;
      })
      .join("");
  }

  function renderPastHistory(reports) {
    if (!reports || !reports.length) {
      pastHistoryTable.style.display = "none";
      pastHistoryEmpty.style.display = "block";
      return;
    }
    pastHistoryTable.style.display = "table";
    pastHistoryEmpty.style.display = "none";

    const rows = [];
    reports.forEach((snap) => {
      const generatedLabel = snap.generated_at ? new Date(snap.generated_at).toLocaleString(I18N.locale()) : "";
      const periodLabel = I18N.t(`ads.period.${snap.period}`) !== `ads.period.${snap.period}` ? I18N.t(`ads.period.${snap.period}`) : (I18N.t(`reports.past.period.${snap.period}`) || snap.period);
      const filterLabel = I18N.t(`reports.past.status.${snap.status_filter}`) || snap.status_filter;
      if (!snap.campaigns || !snap.campaigns.length) {
        rows.push(`<tr><td>${generatedLabel}</td><td>${periodLabel}</td><td>${filterLabel}</td><td colspan="5">${I18N.t("reports.past.no_campaigns_for_filter")}</td></tr>`);
        return;
      }
      snap.campaigns.forEach((c) => {
        const result = c.result || {};
        const spend = c.metrics ? c.metrics.spend : null;
        rows.push(`
          <tr>
            <td>${generatedLabel}</td>
            <td>${periodLabel}</td>
            <td>${filterLabel}</td>
            <td>${c.name}</td>
            <td><span class="badge ${pastStatusBadgeClass(c.effective_status)}">${c.effective_status || c.status || "?"}</span></td>
            <td>${fmtMoney(spend)}</td>
            <td>${result.value !== null && result.value !== undefined ? `${result.label}: ${result.value}` : I18N.t("common.no_data")}</td>
            <td>${c.recommendation || ""}</td>
          </tr>
        `);
      });
    });
    pastHistoryBody.innerHTML = rows.join("");
  }

  async function loadPastHistory() {
    const res = await fetch("/api/reports/past-campaigns/history");
    const data = await res.json();
    renderPastHistory(data.reports || []);
    if (data.reports && data.reports.length) {
      renderPastReport(data.reports[0]);
    }
  }

  pastCollectBtn.addEventListener("click", async () => {
    if (pastPeriod === "custom" && (!pastDateFromInput.value || !pastDateToInput.value)) {
      pastStatusEl.textContent = I18N.t("ads.msg.specify_both_dates");
      return;
    }
    pastCollectBtn.disabled = true;
    pastCollectBtn.textContent = I18N.t("reports.collecting");
    pastStatusEl.textContent = "";
    try {
      const body = { status_filter: pastStatusFilter, period: pastPeriod };
      if (pastPeriod === "custom") {
        body.date_from = pastDateFromInput.value;
        body.date_to = pastDateToInput.value;
      }
      const res = await fetch("/api/reports/past-campaigns/collect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        pastStatusEl.textContent = data.error || I18N.t("reports.no_keys");
        return;
      }
      renderPastReport(data);
      await loadPastHistory();
      pastStatusEl.textContent = I18N.t("common.saved_ok");
      setTimeout(() => (pastStatusEl.textContent = ""), 2500);
    } catch (e) {
      pastStatusEl.textContent = I18N.t("common.network_error", { message: e.message });
    } finally {
      pastCollectBtn.disabled = false;
      pastCollectBtn.textContent = I18N.t("reports.past.collect_btn");
    }
  });

  pastExportBtn.addEventListener("click", async () => {
    pastExportBtn.disabled = true;
    try {
      const res = await fetch("/api/reports/past-campaigns/export-excel");
      if (!res.ok) {
        const data = await res.json();
        pastStatusEl.textContent = data.error || I18N.t("reports.past.msg.no_history_to_export");
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "past_campaigns_report.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      pastStatusEl.textContent = I18N.t("common.network_error", { message: e.message });
    } finally {
      pastExportBtn.disabled = false;
    }
  });

  loadPastHistory();

  // --- Звіт для клієнта (Фаза 7) ---

  const clientPeriodBtns = document.querySelectorAll(".client-period-btn");
  const clientCustomRange = document.getElementById("client-report-custom-range");
  const clientDateFromInput = document.getElementById("client-report-date-from");
  const clientDateToInput = document.getElementById("client-report-date-to");
  const clientGenerateBtn = document.getElementById("btn-generate-client-report");
  const clientStatusEl = document.getElementById("client-report-status");
  const clientLatestBox = document.getElementById("client-report-latest");
  const clientSummaryBox = document.getElementById("client-report-summary");
  const clientTotalsBox = document.getElementById("client-report-totals");
  const clientCompareBox = document.getElementById("client-report-compare");
  const clientFunnelBox = document.getElementById("client-report-funnel");
  const clientCampaignsBox = document.getElementById("client-report-campaigns");
  const clientCreativesBox = document.getElementById("client-report-creatives");
  const clientTestedBox = document.getElementById("client-report-tested");
  const clientBusinessBox = document.getElementById("client-report-business");
  const clientReelsBox = document.getElementById("client-report-reels");
  const clientReportsListEl = document.getElementById("client-reports-list");
  const clientReportsEmpty = document.getElementById("client-reports-empty");

  let clientPeriod = "daily";

  clientPeriodBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      clientPeriodBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      clientPeriod = btn.dataset.period;
      clientCustomRange.style.display = clientPeriod === "custom" ? "inline-flex" : "none";
    });
  });

  function clientPeriodLabel(reportType) {
    const key = `reports.client.type.${reportType}`;
    return I18N.t(key) !== key ? I18N.t(key) : reportType;
  }

  function fmtDelta(curr, prev) {
    if (curr === null || curr === undefined || prev === null || prev === undefined || prev === 0) {
      return I18N.t("reports.client.no_comparison");
    }
    const pct = Math.round(((curr - prev) / prev) * 1000) / 10;
    return `${pct >= 0 ? "+" : ""}${pct}%`;
  }

  function renderClientSummary(report) {
    const summary = report.summary || {};
    const hasStructured = summary.main_fact || summary.cause || summary.consequence || summary.actions || summary.business_plain;
    if (!hasStructured) {
      // Звіти, згенеровані до єдиного формату (Фаза 7 rework), мають старі поля conclusion/
      // next_period_plan замість summary — показуємо їх як є, а не ховаємо історію.
      if (report.conclusion) {
        clientSummaryBox.innerHTML = `
          <div class="report-summary-box">
            <div class="report-summary-fact">${report.conclusion.replace(/\n/g, "<br>")}</div>
            ${report.next_period_plan ? `<div class="summary-line"><b>${I18N.t("reports.client.summary.actions_label")}:</b> ${report.next_period_plan.replace(/\n/g, "<br>")}</div>` : ""}
          </div>
        `;
        clientBusinessBox.innerHTML = "";
        return;
      }
      clientSummaryBox.innerHTML = report.opus_note
        ? `<div class="report-summary-box"><div class="summary-line" style="color:var(--muted);">${report.opus_note}</div></div>`
        : "";
      clientBusinessBox.innerHTML = "";
      return;
    }

    const lines = [];
    if (summary.main_fact) {
      lines.push(`<div class="report-summary-fact">${summary.main_fact}</div>`);
    }
    if (summary.cause) {
      lines.push(`<div class="summary-line"><b>${I18N.t("reports.client.summary.cause_label")}:</b> ${summary.cause}</div>`);
    }
    if (summary.consequence) {
      lines.push(`<div class="summary-line"><b>${I18N.t("reports.client.summary.consequence_label")}:</b> ${summary.consequence}</div>`);
    }
    if (summary.actions) {
      const actionsHtml = summary.actions.replace(/\n/g, "<br>");
      lines.push(`<div class="summary-line"><b>${I18N.t("reports.client.summary.actions_label")}:</b> ${actionsHtml}</div>`);
    }
    clientSummaryBox.innerHTML = `<div class="report-summary-box">${lines.join("")}</div>`;

    clientBusinessBox.innerHTML = summary.business_plain
      ? `
        <div class="subtitle" style="margin-bottom:6px;">${I18N.t("reports.client.business_heading")}</div>
        <div class="report-business-box">${summary.business_plain}</div>
      `
      : "";
  }

  function testedResultText(item) {
    const r = item.result || {};
    if (r.value === null || r.value === undefined) return I18N.t("common.no_data");
    const cost = r.cost_per_result !== null && r.cost_per_result !== undefined ? ` (${fmtMoney(r.cost_per_result)})` : "";
    return `${r.label}: ${r.value}${cost}`;
  }

  function verdictBadgeHtml(verdict) {
    if (!verdict || !verdict.text) return "";
    const cls = `verdict-${verdict.code || "in_range"}`;
    return `<span class="badge ${cls}">${verdict.text}</span>`;
  }

  function renderClientReport(report) {
    if (!report) {
      clientLatestBox.style.display = "none";
      return;
    }
    clientLatestBox.style.display = "block";
    const totals = report.totals || {};
    const prevTotals = report.prev_totals || {};

    renderClientSummary(report);

    const numberRows = [
      [I18N.t("reports.col.spend"), fmtMoney(totals.spend), fmtDelta(totals.spend, prevTotals.spend)],
      [I18N.t("reports.client.funnel.impressions"), fmtMoney(totals.impressions), fmtDelta(totals.impressions, prevTotals.impressions)],
      [I18N.t("reports.client.reach_label"), fmtMoney(totals.reach), fmtDelta(totals.reach, prevTotals.reach)],
      ["CTR", totals.ctr ?? I18N.t("common.no_data"), fmtDelta(totals.ctr, prevTotals.ctr), "%"],
      ["CPM", fmtMoney(totals.cpm), fmtDelta(totals.cpm, prevTotals.cpm)],
      [I18N.t("reports.client.frequency"), totals.frequency ?? I18N.t("common.no_data"), fmtDelta(totals.frequency, prevTotals.frequency)],
    ];
    const prevResultsByLabel = {};
    (prevTotals.results || []).forEach((r) => { prevResultsByLabel[r.label] = r; });
    (totals.results || []).forEach((r) => {
      const prevR = prevResultsByLabel[r.label];
      numberRows.push([r.label, r.value, fmtDelta(r.value, prevR ? prevR.value : undefined)]);
      numberRows.push([`${I18N.t("reports.col.cost_per_result")} (${r.label})`, fmtMoney(r.cost_per_result), fmtDelta(r.cost_per_result, prevR ? prevR.cost_per_result : undefined)]);
    });

    clientTotalsBox.innerHTML = `
      <div class="subtitle" style="margin-bottom:6px;">${I18N.t("reports.client.totals_heading")}</div>
      <table style="width:100%; border-collapse:collapse; font-size:13px;">
        <tbody>
          ${numberRows.map(([label, value, delta, suffix]) => `
            <tr style="border-top:1px solid var(--border);">
              <td style="padding:6px 8px; color:var(--muted);">${label}</td>
              <td style="padding:6px 8px; font-weight:600;">${value}${suffix || ""}</td>
              <td style="padding:6px 8px; color:var(--muted);">${delta}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;

    clientCompareBox.innerHTML = report.prev_date_from
      ? `<div class="subtitle">${I18N.t("reports.client.vs_prev")}: ${report.prev_date_from} — ${report.prev_date_to}</div>`
      : "";

    clientFunnelBox.innerHTML = (report.funnel && report.funnel.length)
      ? `
        <div class="subtitle" style="margin-bottom:6px;">${I18N.t("reports.client.funnel_heading")}</div>
        <table style="width:100%; border-collapse:collapse; font-size:13px;">
          <thead><tr style="text-align:left; color:var(--muted);">
            <th style="padding:4px 8px;">${I18N.t("reports.client.funnel_col_stage")}</th>
            <th style="padding:4px 8px;">${I18N.t("reports.client.funnel_col_current")}</th>
            <th style="padding:4px 8px;">${I18N.t("reports.client.funnel_col_prev")}</th>
            <th style="padding:4px 8px;">${I18N.t("reports.client.funnel_col_change")}</th>
          </tr></thead>
          <tbody>
            ${report.funnel.map((f) => `
              <tr style="border-top:1px solid var(--border);">
                <td style="padding:4px 8px;">${f.label}</td>
                <td style="padding:4px 8px;">${f.value ?? I18N.t("common.no_data")}</td>
                <td style="padding:4px 8px;">${f.prev_value ?? I18N.t("common.no_data")}</td>
                <td style="padding:4px 8px;">${fmtDelta(f.value, f.prev_value)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `
      : "";

    clientCampaignsBox.innerHTML = `
      <div class="subtitle" style="margin-bottom:8px;">${I18N.t("reports.client.campaigns_heading")}</div>
      <table style="width:100%; border-collapse:collapse; font-size:13px;">
        <thead><tr style="text-align:left; color:var(--muted);">
          <th style="padding:4px 8px;">${I18N.t("reports.client.col_campaign")}</th>
          <th style="padding:4px 8px;">${I18N.t("reports.client.col_spend")}</th>
          <th style="padding:4px 8px;">${I18N.t("reports.client.col_ctr")}</th>
          <th style="padding:4px 8px;">${I18N.t("reports.client.col_frequency")}</th>
          <th style="padding:4px 8px;">${I18N.t("reports.client.col_result")}</th>
          <th style="padding:4px 8px;">${I18N.t("reports.client.col_cost_per_result")}</th>
          <th style="padding:4px 8px;">${I18N.t("reports.client.col_verdict")}</th>
        </tr></thead>
        <tbody>
          ${(report.campaigns || [])
            .map((c) => {
              const m = c.metrics || {};
              const r = c.result || {};
              const resultCell = r.value !== null && r.value !== undefined ? `${r.label}: ${r.value}` : (r.note || I18N.t("common.no_data"));
              return `
                <tr style="border-top:1px solid var(--border);">
                  <td style="padding:6px 8px;"><strong>${c.name}</strong><br><span class="subtitle">${c.objective_label}</span></td>
                  <td style="padding:6px 8px;">${fmtMoney(m.spend)}</td>
                  <td style="padding:6px 8px;">${m.ctr ?? I18N.t("common.no_data")}%</td>
                  <td style="padding:6px 8px;">${m.frequency ?? I18N.t("common.no_data")}</td>
                  <td style="padding:6px 8px;">${resultCell}</td>
                  <td style="padding:6px 8px;">${fmtMoney(r.cost_per_result)}</td>
                  <td style="padding:6px 8px;">${verdictBadgeHtml(c.verdict)}</td>
                </tr>
              `;
            })
            .join("")}
        </tbody>
      </table>
    `;

    if (report.best_ad && report.worst_ad) {
      clientCreativesBox.innerHTML = `
        <div class="subtitle">${I18N.t("reports.client.creatives_heading")}</div>
        <div style="margin-top:6px; font-size:13px;">
          <div><b>${I18N.t("reports.client.best_ad")}:</b> «${report.best_ad.name}» (${report.best_ad.campaign_name}) — ${report.best_ad.metric_used}: ${report.best_ad.value} (${I18N.t("reports.client.funnel.impressions")}: ${fmtMoney(report.best_ad.impressions)})</div>
          <div><b>${I18N.t("reports.client.worst_ad")}:</b> «${report.worst_ad.name}» (${report.worst_ad.campaign_name}) — ${report.worst_ad.metric_used}: ${report.worst_ad.value} (${I18N.t("reports.client.funnel.impressions")}: ${fmtMoney(report.worst_ad.impressions)})</div>
          ${report.ad_note ? `<div style="color:var(--muted); margin-top:4px;">${report.ad_note}</div>` : ""}
        </div>
      `;
    } else {
      clientCreativesBox.innerHTML = `
        <div class="subtitle">${I18N.t("reports.client.creatives_heading")}</div>
        <div style="color:var(--muted); font-size:13px;">${report.ad_note || I18N.t("common.no_data")}</div>
      `;
    }

    const newAdsets = report.new_adsets || [];
    const newAds = report.new_ads || [];
    if (newAdsets.length || newAds.length) {
      clientTestedBox.innerHTML = `
        <div class="subtitle">${I18N.t("reports.client.tested_heading")}</div>
        ${newAdsets
          .map((a) => `<div style="font-size:13px; margin-top:4px;">${I18N.t("reports.client.tested_new_adset", { name: a.name, campaign: a.campaign_name, result: testedResultText(a) })}</div>`)
          .join("")}
        ${newAds
          .map((a) => `<div style="font-size:13px; margin-top:4px;">${I18N.t("reports.client.tested_new_ad", { name: a.name, campaign: a.campaign_name, result: testedResultText(a) })}</div>`)
          .join("")}
      `;
    } else {
      clientTestedBox.innerHTML = `
        <div class="subtitle">${I18N.t("reports.client.tested_heading")}</div>
        <div style="color:var(--muted); font-size:13px;">${I18N.t("reports.client.tested_none")}</div>
      `;
    }

    if (report.top_reels && report.top_reels.length) {
      clientReelsBox.innerHTML = `
        <div class="subtitle">${I18N.t("reports.client.top_reels_heading")}</div>
        ${report.top_reels
          .map((p) => `<div style="font-size:13px; margin-top:4px;">«${p.caption}» — ER ${p.engagement_rate}%, ${I18N.t("reports.client.reach_label")}: ${p.reach}</div>`)
          .join("")}
      `;
    } else {
      clientReelsBox.innerHTML = `
        <div class="subtitle">${I18N.t("reports.client.top_reels_heading")}</div>
        <div style="color:var(--muted); font-size:13px;">${I18N.t("common.no_data")}</div>
      `;
    }

  }

  function clientReportCardHtml(r) {
    const generatedLabel = r.generated_at ? new Date(r.generated_at).toLocaleString(I18N.locale()) : "";
    return `
      <div class="top-card" data-id="${r.id}" style="margin-bottom:10px;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
          <strong>${clientPeriodLabel(r.period)} (${r.date_from} — ${r.date_to})</strong>
          <span class="subtitle">${generatedLabel}</span>
        </div>
        <div class="category-actions" style="margin-top:8px;">
          <button class="icon-btn client-report-pdf-btn">${I18N.t("reports.client.download_pdf_btn")}</button>
          <button class="icon-btn client-report-delete-btn">${I18N.t("categories.delete_btn")}</button>
        </div>
      </div>
    `;
  }

  async function downloadClientReportPdf(reportId) {
    const res = await fetch(`/api/reports/client/${reportId}/pdf`);
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `client_report_${reportId}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function renderClientReportsList(reports) {
    if (!reports || !reports.length) {
      clientReportsListEl.innerHTML = "";
      clientReportsEmpty.style.display = "block";
      return;
    }
    clientReportsEmpty.style.display = "none";
    clientReportsListEl.innerHTML = reports.map(clientReportCardHtml).join("");
    clientReportsListEl.querySelectorAll(".client-report-pdf-btn").forEach((btn) => {
      btn.addEventListener("click", () => downloadClientReportPdf(btn.closest(".top-card").dataset.id));
    });
    clientReportsListEl.querySelectorAll(".client-report-delete-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm(I18N.t("reports.client.confirm_delete"))) return;
        const id = btn.closest(".top-card").dataset.id;
        const res = await fetch(`/api/reports/client/${id}`, { method: "DELETE" });
        if (res.ok) await loadClientReports();
      });
    });
  }

  async function loadClientReports() {
    const res = await fetch("/api/reports/client");
    const data = await res.json();
    renderClientReportsList(data.reports || []);
  }

  clientGenerateBtn.addEventListener("click", async () => {
    if (clientPeriod === "custom" && (!clientDateFromInput.value || !clientDateToInput.value)) {
      clientStatusEl.textContent = I18N.t("ads.msg.specify_both_dates");
      return;
    }
    clientGenerateBtn.disabled = true;
    clientGenerateBtn.textContent = I18N.t("reports.collecting");
    clientStatusEl.textContent = "";
    try {
      const body = { report_type: clientPeriod };
      if (clientPeriod === "custom") {
        body.date_from = clientDateFromInput.value;
        body.date_to = clientDateToInput.value;
      }
      const res = await fetch("/api/reports/client/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        clientStatusEl.textContent = data.error || I18N.t("reports.no_keys");
        return;
      }
      renderClientReport(data);
      await loadClientReports();
      clientStatusEl.textContent = I18N.t("common.saved_ok");
      setTimeout(() => (clientStatusEl.textContent = ""), 2500);
    } catch (e) {
      clientStatusEl.textContent = I18N.t("common.network_error", { message: e.message });
    } finally {
      clientGenerateBtn.disabled = false;
      clientGenerateBtn.textContent = I18N.t("reports.client.generate_btn");
    }
  });

  loadClientReports();
})();
