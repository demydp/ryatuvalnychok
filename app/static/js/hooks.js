(function () {
  const btnPilot = document.getElementById("btn-pilot");
  const btnAll = document.getElementById("btn-all");
  const modelMeta = document.getElementById("model-status-meta");
  const progressBox = document.getElementById("progress-box");
  const subtitle = document.getElementById("hooks-subtitle");
  const emptyState = document.getElementById("hooks-empty");
  const content = document.getElementById("hooks-content");
  const tableMeta = document.getElementById("hooks-table-meta");
  const tbody = document.getElementById("hooks-tbody");
  const hookTypeNote = document.getElementById("hook-type-note");
  const skipRateNote = document.getElementById("skip-rate-note");

  const btnCheckMetrics = document.getElementById("btn-check-metrics");
  const diagnosticStatus = document.getElementById("diagnostic-status");
  const diagnosticResult = document.getElementById("diagnostic-result");
  const diagnosticTbody = document.getElementById("diagnostic-tbody");

  const btnHooksAiSummary = document.getElementById("btn-hooks-ai-summary");
  const hooksAiSummaryStatus = document.getElementById("hooks-ai-summary-status");
  const hooksAiSummaryText = document.getElementById("hooks-ai-summary-text");

  const HOOK_TYPE_CLASS = {
    "вопрос": "hook-question",
    "боль": "hook-pain",
    "провокация": "hook-provocation",
    "цифра": "hook-number",
    "утверждение": "hook-other",
  };

  let chart = null;
  let skipChart = null;
  let items = [];
  let lastHookTypeSummary = [];
  let lastSkipRateSummary = [];
  let running = false;

  function fmtDuration(sec) {
    if (sec === null || sec === undefined) return `<span class="na">${I18N.t("common.no_data")}</span>`;
    return `${sec.toFixed(1)} сек`;
  }

  function hookBadge(type) {
    if (!type) return "";
    const cls = HOOK_TYPE_CLASS[type] || "hook-other";
    return `<span class="badge ${cls}">${hookTypeLabel(type)}</span>`;
  }

  const HUNT_TEMP_CLASS = { "холодная": "hunt-cold", "тёплая": "hunt-warm", "горячая": "hunt-hot" };

  function huntBadge(it) {
    if (!it.hunt_stage && !it.hunt_temperature) return "";
    const undetermined = "не определено";
    const stageOk = it.hunt_stage && it.hunt_stage !== undetermined;
    const tempOk = it.hunt_temperature && it.hunt_temperature !== undetermined;
    const tempCls = tempOk ? HUNT_TEMP_CLASS[it.hunt_temperature] || "hunt-unknown" : "hunt-unknown";
    const title = it.hunt_reasoning || it.hunt_note || "";
    const stageBadge = `<span class="badge hunt-unknown" title="${title.replace(/"/g, "&quot;")}">${stageOk ? huntStageLabel(it.hunt_stage) : I18N.t("hooks.hunt.undetermined")}</span>`;
    const tempBadge = tempOk
      ? `<span class="badge ${tempCls}" style="margin-left:4px;">${huntTempLabel(it.hunt_temperature)}</span>`
      : "";
    return `${stageBadge}${tempBadge}`;
  }

  async function loadModelStatus() {
    const res = await fetch("/api/hooks/model-status");
    const data = await res.json();
    const sizeHint = document.getElementById("model-size-hint");
    if (sizeHint) sizeHint.textContent = data.size_hint || "";
    modelMeta.textContent = data.downloaded
      ? I18N.t("hooks.msg.model_downloaded", { model: data.model })
      : I18N.t("hooks.msg.model_will_download", { model: data.model, size: data.size_hint });
  }

  function renderTable() {
    tbody.innerHTML = items
      .map((it, idx) => {
        const done = it.transcript_status === "ok";
        return `
      <tr class="post-row" data-idx="${idx}">
        <td>${done ? '<span class="expand-toggle">▸</span>' : ""}</td>
        <td>${it.thumbnail_url ? `<img src="${it.thumbnail_url}" style="width:32px;height:32px;object-fit:cover;border-radius:5px;">` : ""}</td>
        <td class="caption-cell" style="max-width:260px;">${done ? (it.hook_text || `<span class="na">${I18N.t("common.empty")}</span>`) : `<span class="na">${I18N.t("hooks.msg.not_transcribed")}</span>`}${done && it.low_confidence ? ' <span class="badge hook-pain" title="' + (it.quality_reason || "") + '">' + I18N.t("hooks.badge.low_confidence") + '</span>' : ""}</td>
        <td>${done ? hookBadge(it.hook_type) : ""}</td>
        <td>${done ? huntBadge(it) : ""}</td>
        <td>${done ? fmtDuration(it.duration_sec) : ""}</td>
        <td>${it.avg_watch_time_ms != null ? fmtMsAsSeconds(it.avg_watch_time_ms) : `<span class="na">${I18N.t("common.no_data")}</span>`}</td>
        <td>${it.hook_indicator != null ? it.hook_indicator + "%" : `<span class="na">${I18N.t("common.no_data")}</span>`}</td>
        <td>${it.skip_rate != null ? it.skip_rate + "%" : `<span class="na">${it.skip_rate_reason || I18N.t("common.no_data")}</span>`}</td>
        <td>${it.is_ad ? `<span class="badge hook-provocation">${I18N.t("hooks.badge.ad")}</span>` : ""}</td>
        <td>${done ? "" : `<button class="btn secondary btn-transcribe-one" data-id="${it.id}" style="padding:5px 10px; font-size:12px;">${I18N.t("hooks.transcribe_one_btn")}</button>`}</td>
      </tr>
      <tr class="detail-row" data-idx="${idx}"><td colspan="11">${done ? fullTranscriptHtml(it) : ""}</td></tr>`;
      })
      .join("");

    tbody.querySelectorAll("tr.post-row").forEach((row) => {
      row.addEventListener("click", (e) => {
        if (e.target.closest("button")) return;
        const idx = row.dataset.idx;
        const item = items[idx];
        if (item.transcript_status !== "ok") return;
        row.classList.toggle("expanded");
        tbody.querySelector(`tr.detail-row[data-idx="${idx}"]`).classList.toggle("show");
      });
    });

    tbody.querySelectorAll(".btn-transcribe-one").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await transcribeIds([btn.dataset.id]);
      });
    });
  }

  function fullTranscriptHtml(it) {
    return `
      <div style="font-size:13px; line-height:1.6;">
        <div class="k" style="color:var(--muted); margin-bottom:6px;">${I18N.t("hooks.detail.full_transcript", { language: it.language || "?", model: it.whisper_model || "?" })}</div>
        <div>${it.text || `<span class="na">${I18N.t("common.empty")}</span>`}</div>
        ${it.low_confidence ? `<div class="na" style="margin-top:8px;">${I18N.t("hooks.detail.low_confidence_note", { reason: it.quality_reason || "" })}</div>` : ""}
        ${
          it.hunt_stage && it.hunt_stage !== "не определено"
            ? `<div style="margin-top:8px;">${I18N.t("hooks.detail.hunt_line", { stage: huntStageLabel(it.hunt_stage), temperature: huntTempLabel(it.hunt_temperature) })} ${it.hunt_reasoning ? `— ${it.hunt_reasoning}` : ""}</div>`
            : it.hunt_note
            ? `<div class="na" style="margin-top:8px;">${I18N.t("hooks.detail.hunt_undetermined", { reason: it.hunt_note })}</div>`
            : ""
        }
        ${it.permalink ? `<div style="margin-top:8px;"><a href="${it.permalink}" target="_blank" rel="noopener">${I18N.t("metrics.detail.open_in_instagram")}</a></div>` : ""}
      </div>`;
  }

  function renderChart(summary) {
    lastHookTypeSummary = summary;
    const ctx = document.getElementById("chart-hook-type");
    if (chart) chart.destroy();
    if (!summary.length) {
      hookTypeNote.textContent = I18N.t("hooks.msg.not_enough_data_type");
      return;
    }
    chart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: summary.map((s) => `${hookTypeLabel(s.type)} (${s.count})`),
        datasets: [
          {
            label: I18N.t("hooks.chart.avg_hook_indicator_series"),
            data: summary.map((s) => s.avg_indicator),
            backgroundColor: "#bd94eb",
            borderRadius: 4,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true } },
      },
    });
    const best = summary[0];
    hookTypeNote.textContent = I18N.t("hooks.msg.best_hook_type", {
      type: hookTypeLabel(best.type),
      indicator: best.avg_indicator,
      count: best.count,
    });
  }

  function renderSkipChart(summary) {
    lastSkipRateSummary = summary;
    const ctx = document.getElementById("chart-skip-rate");
    if (skipChart) skipChart.destroy();
    if (!summary.length) {
      skipRateNote.textContent = I18N.t("hooks.msg.not_enough_data_skip");
      return;
    }
    skipChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: summary.map((s) => `${hookTypeLabel(s.type)} (${s.count})`),
        datasets: [
          {
            label: I18N.t("hooks.chart.avg_skip_rate_series"),
            data: summary.map((s) => s.avg_skip_rate),
            backgroundColor: "#bd94eb",
            borderRadius: 4,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true } },
      },
    });
    const best = summary[0];
    skipRateNote.textContent = I18N.t("hooks.msg.best_skip_rate", {
      type: hookTypeLabel(best.type),
      rate: best.avg_skip_rate,
      count: best.count,
    });
  }

  let engagementChart = null;
  let lastEngagementSummary = [];

  function renderEngagementChart(summary) {
    lastEngagementSummary = summary;
    const ctx = document.getElementById("chart-engagement-rate");
    if (engagementChart) engagementChart.destroy();
    const note = document.getElementById("engagement-rate-note");
    if (!summary.length) {
      note.textContent = I18N.t("hooks.msg.not_enough_data_engagement");
      return;
    }
    engagementChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: summary.map((s) => `${hookTypeLabel(s.type)} (${s.count})`),
        datasets: [
          {
            label: I18N.t("hooks.chart.avg_engagement_rate_series"),
            data: summary.map((s) => s.avg_engagement_rate),
            backgroundColor: "#bd94eb",
            borderRadius: 4,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true } },
      },
    });
    const best = summary[0];
    note.textContent = I18N.t("hooks.msg.best_engagement_rate", {
      type: hookTypeLabel(best.type),
      rate: best.avg_engagement_rate,
      count: best.count,
    });
  }

  function statusBadge(status) {
    return status === "ok"
      ? `<span class="verdict-badge verdict-good">${I18N.t("hooks.diagnostic.status_ok")}</span>`
      : `<span class="verdict-badge verdict-bad">${I18N.t("common.no_data")}</span>`;
  }

  function renderDiagnostic(groups) {
    diagnosticResult.style.display = "block";
    diagnosticTbody.innerHTML = groups
      .map((g) => {
        const groupHeader = `<tr><td colspan="3" style="font-weight:600; background:var(--bg-elevated-2);">${g.group}</td></tr>`;
        const rows = g.metrics
          .map((m) => {
            const detail =
              m.status === "ok"
                ? `<span title="${I18N.t("hooks.diagnostic.sample_values_title")}">${m.sample_values.join(", ")}</span>`
                : m.reason || m.raw_message || "";
            return `<tr><td><code>${m.metric}</code><br><span class="na" style="font-style:normal;">${m.label}</span></td><td>${statusBadge(m.status)}</td><td>${detail}</td></tr>`;
          })
          .join("");
        return groupHeader + rows;
      })
      .join("");
  }

  btnCheckMetrics.addEventListener("click", async () => {
    btnCheckMetrics.disabled = true;
    btnCheckMetrics.textContent = I18N.t("hooks.msg.checking");
    diagnosticStatus.className = "status-box show";
    diagnosticStatus.textContent = I18N.t("hooks.msg.diagnostic_in_progress");
    diagnosticResult.style.display = "none";
    try {
      const res = await fetch("/api/hooks/metrics-diagnostic");
      const data = await res.json();
      if (!res.ok) {
        diagnosticStatus.className = "status-box show error";
        diagnosticStatus.textContent = data.error || I18N.t("common.error");
        return;
      }
      diagnosticStatus.className = "status-box show ok";
      diagnosticStatus.textContent = I18N.t("hooks.msg.diagnostic_done", { count: data.checked_count });
      renderDiagnostic(data.groups);
    } catch (e) {
      diagnosticStatus.className = "status-box show error";
      diagnosticStatus.textContent = I18N.t("common.network_error", { message: e.message });
    } finally {
      btnCheckMetrics.disabled = false;
      btnCheckMetrics.textContent = I18N.t("hooks.diagnostic.check_btn");
    }
  });

  if (btnHooksAiSummary) {
    btnHooksAiSummary.addEventListener("click", async () => {
      btnHooksAiSummary.disabled = true;
      btnHooksAiSummary.textContent = I18N.t("hooks.ai_summary.generating");
      hooksAiSummaryStatus.className = "status-box show";
      hooksAiSummaryStatus.textContent = I18N.t("hooks.ai_summary.generating");
      hooksAiSummaryText.style.display = "none";
      try {
        const res = await fetch("/api/hooks/ai-summary", { method: "POST" });
        const data = await res.json();
        if (!res.ok) {
          hooksAiSummaryStatus.className = "status-box show error";
          hooksAiSummaryStatus.textContent = data.error || I18N.t("common.error");
          return;
        }
        hooksAiSummaryStatus.className = "status-box show ok";
        hooksAiSummaryStatus.textContent = "";
        hooksAiSummaryStatus.classList.remove("show");
        hooksAiSummaryText.style.display = "block";
        hooksAiSummaryText.textContent = data.summary;
      } catch (e) {
        hooksAiSummaryStatus.className = "status-box show error";
        hooksAiSummaryStatus.textContent = I18N.t("common.network_error", { message: e.message });
      } finally {
        btnHooksAiSummary.disabled = false;
        btnHooksAiSummary.textContent = I18N.t("hooks.ai_summary.btn");
      }
    });
  }

  async function loadHooks() {
    const res = await fetch("/api/hooks");
    const data = await res.json();
    items = data.items || [];

    if (items.length === 0) {
      content.style.display = "none";
      emptyState.style.display = "block";
      return;
    }

    emptyState.style.display = "none";
    content.style.display = "block";
    subtitle.textContent = data.ig_username ? I18N.t("metrics.subtitle_account", { username: data.ig_username }) : "";

    const doneCount = items.filter((it) => it.transcript_status === "ok").length;
    tableMeta.textContent = I18N.t("hooks.table.meta", { done: doneCount, total: items.length });

    renderTable();
    renderChart(data.hook_type_summary || []);
    renderSkipChart(data.skip_rate_summary || []);
    renderEngagementChart(data.engagement_rate_summary || []);
  }

  async function transcribeIds(ids) {
    if (running) return;
    running = true;
    btnPilot.disabled = true;
    btnAll.disabled = true;
    progressBox.style.display = "block";
    progressBox.className = "status-box show";

    const errors = [];
    for (let i = 0; i < ids.length; i++) {
      progressBox.textContent = I18N.t("hooks.msg.processing", { current: i + 1, total: ids.length });
      try {
        const res = await fetch(`/api/hooks/transcribe/${ids[i]}`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) errors.push(`${ids[i]}: ${data.error || I18N.t("common.error")}`);
      } catch (e) {
        errors.push(`${ids[i]}: ${e.message}`);
      }
      await loadHooks();
    }

    progressBox.className = errors.length ? "status-box show error" : "status-box show ok";
    progressBox.textContent = errors.length
      ? I18N.t("hooks.msg.done_with_errors", { count: errors.length, errors: errors.join("; ") })
      : I18N.t("hooks.msg.done", { count: ids.length });

    await loadModelStatus();
    running = false;
    btnPilot.disabled = false;
    btnAll.disabled = false;
  }

  btnPilot.addEventListener("click", () => {
    const pending = items.filter((it) => it.transcript_status !== "ok").slice(0, 3).map((it) => it.id);
    if (pending.length === 0) {
      alert(I18N.t("hooks.msg.all_transcribed_or_none"));
      return;
    }
    transcribeIds(pending);
  });

  btnAll.addEventListener("click", () => {
    const pending = items.filter((it) => it.transcript_status !== "ok").map((it) => it.id);
    if (pending.length === 0) {
      alert(I18N.t("hooks.msg.all_transcribed"));
      return;
    }
    if (!confirm(I18N.t("hooks.msg.confirm_transcribe_all", { count: pending.length }))) return;
    transcribeIds(pending);
  });

  document.querySelector('.tab-btn[data-tab="hooks"]').addEventListener("click", () => {
    loadHooks();
    loadModelStatus();
  });

  document.addEventListener("langchange", () => {
    loadModelStatus();
    if (items.length) {
      renderTable();
      renderChart(lastHookTypeSummary);
      renderSkipChart(lastSkipRateSummary);
      renderEngagementChart(lastEngagementSummary);
    }
  });

  loadModelStatus();
})();
