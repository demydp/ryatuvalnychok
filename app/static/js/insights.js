(function () {
  const refreshBtn = document.getElementById("btn-refresh-insights");
  const subtitle = document.getElementById("insights-subtitle");
  const meta = document.getElementById("insights-meta");
  const emptyState = document.getElementById("insights-empty");
  const content = document.getElementById("insights-content");
  const warningBox = document.getElementById("insights-warning");
  const recList = document.getElementById("recommendations-list");
  const resultsTbody = document.getElementById("results-tbody");
  const videoLengthNote = document.getElementById("video-length-note");
  const savesNote = document.getElementById("saves-note");
  const sharesNote = document.getElementById("shares-note");

  const btnInsightsAiSummary = document.getElementById("btn-insights-ai-summary");
  const insightsAiSummaryStatus = document.getElementById("insights-ai-summary-status");
  const insightsAiSummaryText = document.getElementById("insights-ai-summary-text");

  let hourChart = null;
  let weekdayChart = null;
  let lastData = null;

  function fmtDateShort(iso) {
    if (!iso) return "";
    return new Date(iso).toLocaleDateString(I18N.locale(), { day: "2-digit", month: "2-digit", year: "2-digit" });
  }

  function miniCard(p, statLabel, statValue) {
    return `
      <a class="post-mini-card" href="${p.permalink || "#"}" target="_blank" rel="noopener">
        ${p.thumbnail_url ? `<img src="${p.thumbnail_url}">` : ""}
        <div class="info">
          <div class="caption">${p.caption ? p.caption : `<span class="na">${I18N.t("common.no_caption")}</span>`}</div>
          <div class="stats">${fmtDateShort(p.timestamp)} • ER ${fmtPercent(p.engagement_rate)} • ${statLabel}: <strong>${statValue}</strong></div>
        </div>
      </a>`;
  }

  function renderList(elId, posts, statKey, statLabel, suffix) {
    const el = document.getElementById(elId);
    if (!posts || posts.length === 0) {
      el.innerHTML = `<p class="na">${I18N.t("common.no_data")}</p>`;
      return;
    }
    el.innerHTML = posts
      .map((p) => miniCard(p, statLabel, `${p[statKey] ?? "—"}${suffix || ""}`))
      .join("");
  }

  function renderChart(canvasId, chartRefSetter, breakdown) {
    const ctx = document.getElementById(canvasId);
    const chart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: breakdown.map((b) => `${b.label} (${b.count})`),
        datasets: [
          {
            label: "Средний ER %",
            data: breakdown.map((b) => b.avg_er),
            backgroundColor: "#bd94eb",
            borderRadius: 4,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true } },
      },
    });
    chartRefSetter(chart);
  }

  function render(data) {
    lastData = data;
    if (data.insufficient_data) {
      content.style.display = "none";
      emptyState.style.display = "block";
      emptyState.textContent = I18N.t("insights.empty_no_data");
      return;
    }

    emptyState.style.display = "none";
    content.style.display = "block";

    subtitle.textContent = data.ig_username ? I18N.t("metrics.subtitle_account", { username: data.ig_username }) : "";
    meta.textContent = I18N.t("insights.meta", {
      size: data.dataset_size,
      ad_excluded: data.ad_excluded_count,
      no_insights_excluded: data.no_insights_excluded_count,
    });

    if (data.low_sample_warning) {
      warningBox.style.display = "block";
      warningBox.textContent = I18N.t("insights.low_sample_warning", { count: data.dataset_size });
    } else {
      warningBox.style.display = "none";
    }

    recList.innerHTML = data.recommendations.map((r) => `<li>${r}</li>`).join("");

    renderList("list-top-er", data.top_er, "reach", "reach");
    renderList("list-bottom-er", data.bottom_er, "reach", "reach");
    renderList("list-top-saves", data.top_saves_rate, "saves_rate", "saves rate", "%");
    renderList("list-top-shares", data.top_shares, "shares", I18N.t("insights.list.shares_stat_label"));

    savesNote.style.display = data.saves_note ? "block" : "none";
    savesNote.textContent = data.saves_note || "";
    sharesNote.style.display = data.shares_note ? "block" : "none";
    sharesNote.textContent = data.shares_note || "";

    resultsTbody.innerHTML = data.results_top
      .map(
        (p) => `
      <tr>
        <td>
          <a href="${p.permalink || "#"}" target="_blank" rel="noopener" style="display:flex; align-items:center; gap:8px; text-decoration:none; color:inherit;">
            ${p.thumbnail_url ? `<img src="${p.thumbnail_url}" style="width:32px;height:32px;object-fit:cover;border-radius:5px;">` : ""}
            <span class="caption-cell" style="max-width:220px;">${p.caption || `<span class="na">${I18N.t("common.no_caption")}</span>`}</span>
          </a>
        </td>
        <td>${fmtNumber(p.like_count)}</td>
        <td>${fmtNumber(p.comments_count)}</td>
        <td>${fmtNumber(p.saved)}</td>
        <td>${fmtNumber(p.shares)}</td>
        <td>${fmtNumber(p.total_interactions)}</td>
      </tr>`
      )
      .join("");

    videoLengthNote.textContent = data.video_length_note || "";

    if (hourChart) hourChart.destroy();
    if (weekdayChart) weekdayChart.destroy();
    if (data.by_hour && data.by_hour.length) {
      renderChart("chart-hour", (c) => (hourChart = c), data.by_hour);
    }
    if (data.by_weekday && data.by_weekday.length) {
      renderChart("chart-weekday", (c) => (weekdayChart = c), data.by_weekday);
    }
  }

  async function loadInsights() {
    refreshBtn.disabled = true;
    refreshBtn.textContent = I18N.t("insights.msg.computing");
    try {
      const res = await fetch("/api/analysis");
      const data = await res.json();
      if (!res.ok) {
        emptyState.style.display = "block";
        emptyState.textContent = data.error || I18N.t("insights.msg.load_failed");
        content.style.display = "none";
        return;
      }
      render(data);
    } catch (e) {
      emptyState.style.display = "block";
      emptyState.textContent = I18N.t("common.network_error", { message: e.message });
      content.style.display = "none";
    } finally {
      refreshBtn.disabled = false;
      refreshBtn.textContent = I18N.t("insights.refresh_btn");
    }
  }

  refreshBtn.addEventListener("click", loadInsights);

  if (btnInsightsAiSummary) {
    btnInsightsAiSummary.addEventListener("click", async () => {
      btnInsightsAiSummary.disabled = true;
      btnInsightsAiSummary.textContent = I18N.t("insights.ai_summary.generating");
      insightsAiSummaryStatus.className = "status-box show";
      insightsAiSummaryStatus.textContent = I18N.t("insights.ai_summary.generating");
      insightsAiSummaryText.style.display = "none";
      try {
        const res = await fetch("/api/analysis/ai-summary", { method: "POST" });
        const data = await res.json();
        if (!res.ok) {
          insightsAiSummaryStatus.className = "status-box show error";
          insightsAiSummaryStatus.textContent = data.error || I18N.t("common.error");
          return;
        }
        insightsAiSummaryStatus.className = "status-box";
        insightsAiSummaryStatus.textContent = "";
        insightsAiSummaryText.style.display = "block";
        insightsAiSummaryText.textContent = data.summary;
      } catch (e) {
        insightsAiSummaryStatus.className = "status-box show error";
        insightsAiSummaryStatus.textContent = I18N.t("common.network_error", { message: e.message });
      } finally {
        btnInsightsAiSummary.disabled = false;
        btnInsightsAiSummary.textContent = I18N.t("insights.ai_summary.btn");
      }
    });
  }

  document.querySelector('.tab-btn[data-tab="insights"]').addEventListener("click", () => {
    if (content.style.display === "none" && emptyState.style.display !== "none") {
      loadInsights();
    }
  });

  document.addEventListener("langchange", () => {
    if (lastData) render(lastData);
  });
})();
