(function () {
  const syncBtn = document.getElementById("btn-sync");
  const syncMeta = document.getElementById("sync-meta");
  const syncAgo = document.getElementById("sync-ago");
  const subtitle = document.getElementById("metrics-subtitle");
  const content = document.getElementById("metrics-content");
  const emptyState = document.getElementById("metrics-empty");
  const topCardsEl = document.getElementById("top-cards");
  const tbody = document.getElementById("posts-tbody");
  const tableMeta = document.getElementById("table-meta");
  const headers = document.querySelectorAll("#posts-table thead th");

  let currentPosts = [];
  let lastData = null;
  let sortKey = "timestamp";
  let sortAsc = false;
  let reachChart = null;
  let erChart = null;

  function badgeFor(type) {
    const map = { REELS: "reels", IMAGE: "image", CAROUSEL_ALBUM: "carousel", VIDEO: "reels" };
    const cls = map[type] || "image";
    return `<span class="badge ${cls}">${type || "?"}</span>`;
  }

  function fmtDate(iso) {
    if (!iso) return '<span class="na">—</span>';
    const d = new Date(iso);
    return d.toLocaleDateString(I18N.locale(), { day: "2-digit", month: "2-digit", year: "numeric" });
  }

  function insightsBadge(post) {
    if (post.insights_status === "ok") return "";
    if (post.insights_status === "pending_fresh") {
      return `<div class="badge pending-fresh" style="margin-top:2px;" title="${post.insights_reason || ""}">${I18N.t("metrics.badge.pending_fresh")}</div>`;
    }
    return `<div class="na" style="font-size:11px; margin-top:2px;">${post.insights_reason || I18N.t("common.no_data")}</div>`;
  }

  function render(data) {
    lastData = data;
    currentPosts = data.posts || [];
    updateSyncAgo();

    if (currentPosts.length === 0) {
      content.style.display = "none";
      emptyState.style.display = "block";
      subtitle.textContent = I18N.t("metrics.subtitle_default");
      return;
    }

    emptyState.style.display = "none";
    content.style.display = "block";

    const syncedAt = data.synced_at ? new Date(data.synced_at).toLocaleString(I18N.locale()) : "";
    subtitle.textContent = data.ig_username ? I18N.t("metrics.subtitle_account", { username: data.ig_username }) : "";
    syncMeta.textContent = syncedAt
      ? I18N.t("metrics.sync_meta", {
          synced_at: syncedAt,
          total: data.total_media,
          ok: data.insights_ok,
          pending: data.insights_pending_fresh || 0,
          unavailable: data.insights_unavailable,
        })
      : "";
    tableMeta.textContent = I18N.t("metrics.table.meta", { count: currentPosts.length });

    renderTopCards();
    renderCharts();
    sortAndRenderTable();
  }

  function updateSyncAgo() {
    syncAgo.textContent = lastData && lastData.synced_at ? timeAgoText(lastData.synced_at) : "";
  }

  function renderTopCards() {
    const withReach = currentPosts.filter((p) => typeof p.reach === "number");
    const withER = currentPosts.filter((p) => typeof p.engagement_rate === "number");
    const withSaved = currentPosts.filter((p) => typeof p.saved === "number");
    const withShares = currentPosts.filter((p) => typeof p.shares === "number");

    const topReach = withReach.length ? withReach.reduce((a, b) => (b.reach > a.reach ? b : a)) : null;
    const topER = withER.length ? withER.reduce((a, b) => (b.engagement_rate > a.engagement_rate ? b : a)) : null;
    const topSaved = withSaved.length ? withSaved.reduce((a, b) => (b.saved > a.saved ? b : a)) : null;
    const topShares = withShares.length ? withShares.reduce((a, b) => (b.shares > a.shares ? b : a)) : null;

    const cards = [
      { label: I18N.t("metrics.card.top_reach"), metric: "reach", item: topReach, valueKey: "reach" },
      { label: I18N.t("metrics.card.top_er"), metric: "engagement_rate", item: topER, valueKey: "engagement_rate", suffix: "%" },
      { label: I18N.t("metrics.card.top_saved"), metric: "saved", item: topSaved, valueKey: "saved" },
      { label: I18N.t("metrics.card.top_shares"), metric: "shares", item: topShares, valueKey: "shares" },
    ];

    topCardsEl.innerHTML = cards
      .map((c) => {
        const label = `${c.label}${infoIcon(c.metric)}`;
        if (!c.item) {
          return `<div class="top-card"><div class="label">${label}</div><div class="value na">${I18N.t("common.no_data")}</div></div>`;
        }
        const val = c.item[c.valueKey];
        return `<div class="top-card">
          <div class="label">${label}</div>
          <div class="value">${Number(val).toLocaleString(I18N.locale())}${c.suffix || ""}</div>
          <div class="sub">${(c.item.caption || I18N.t("common.no_caption")).slice(0, 60)}</div>
        </div>`;
      })
      .join("");
  }

  function renderCharts() {
    const top10 = [...currentPosts]
      .filter((p) => typeof p.reach === "number")
      .sort((a, b) => b.reach - a.reach)
      .slice(0, 10);

    const reachCtx = document.getElementById("chart-reach");
    if (reachChart) reachChart.destroy();
    reachChart = new Chart(reachCtx, {
      type: "bar",
      data: {
        labels: top10.map((p) => (p.caption || I18N.t("common.no_caption")).slice(0, 24) || p.id),
        datasets: [
          {
            label: "Reach",
            data: top10.map((p) => p.reach),
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

    const chronological = [...currentPosts]
      .filter((p) => typeof p.engagement_rate === "number" && p.timestamp)
      .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

    const erCtx = document.getElementById("chart-er");
    if (erChart) erChart.destroy();
    erChart = new Chart(erCtx, {
      type: "line",
      data: {
        labels: chronological.map((p) => fmtDate(p.timestamp)),
        datasets: [
          {
            label: "Engagement rate %",
            data: chronological.map((p) => p.engagement_rate),
            borderColor: "#bd94eb",
            backgroundColor: "rgba(189,148,235,0.15)",
            fill: true,
            tension: 0.25,
            pointRadius: 2,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true } },
      },
    });
  }

  function detailRowHtml(p) {
    const notes = p.metric_notes || {};
    const noteLines = Object.entries(notes)
      .map(([field, reason]) => `<div class="k">${field}: <span class="na">${reason}</span></div>`)
      .join("");

    return `
      <div class="detail-grid">
        <div><div class="k">${I18N.t("metrics.detail.total_interactions")}</div><div class="v">${fmtNumber(p.total_interactions)}</div></div>
        <div><div class="k">${I18N.t("metrics.detail.saves_rate")}</div><div class="v">${fmtPercent(p.saves_rate)}</div></div>
        <div><div class="k">${I18N.t("metrics.detail.shares_rate")}</div><div class="v">${fmtPercent(p.shares_rate)}</div></div>
        <div><div class="k">${I18N.t("metrics.detail.avg_watch_time")}</div><div class="v">${fmtMsAsSeconds(p.avg_watch_time)}</div></div>
        <div><div class="k">${I18N.t("metrics.detail.view_total_time")}</div><div class="v">${fmtMsAsSeconds(p.view_total_time)}</div></div>
        <div><div class="k">${I18N.t("metrics.detail.skip_rate")}</div><div class="v">${p.skip_rate === null ? `<span class="na">${p.skip_rate_reason || I18N.t("common.no_data")}</span>` : fmtPercent(p.skip_rate)}</div></div>
        <div><div class="k">${I18N.t("metrics.detail.hook_indicator")}</div><div class="v">${p.hook_indicator === null ? `<span class="na">${p.hook_indicator_reason || I18N.t("common.no_data")}</span>` : p.hook_indicator}</div></div>
        <div><div class="k">${I18N.t("metrics.detail.post_id")}</div><div class="v" style="font-weight:400;">${p.id}</div></div>
      </div>
      ${p.permalink ? `<div style="margin-top:10px;"><a href="${p.permalink}" target="_blank" rel="noopener">${I18N.t("metrics.detail.open_in_instagram")}</a></div>` : ""}
      ${
        p.insights_status === "pending_fresh"
          ? `<div class="badge pending-fresh" style="margin-top:8px;">${I18N.t("metrics.badge.pending_fresh")}</div>`
          : p.insights_status !== "ok"
          ? `<div class="na" style="margin-top:8px;">${I18N.t("metrics.detail.post_insights")} ${p.insights_reason || I18N.t("common.no_data")}</div>`
          : ""
      }
      ${noteLines ? `<div style="margin-top:8px;">${noteLines}</div>` : ""}
    `;
  }

  function sortAndRenderTable() {
    const sorted = [...currentPosts].sort((a, b) => {
      let av = a[sortKey];
      let bv = b[sortKey];
      if (sortKey === "timestamp") {
        av = av ? new Date(av).getTime() : -Infinity;
        bv = bv ? new Date(bv).getTime() : -Infinity;
      }
      if (av === null || av === undefined) av = -Infinity;
      if (bv === null || bv === undefined) bv = -Infinity;
      if (typeof av === "string") return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortAsc ? av - bv : bv - av;
    });

    tbody.innerHTML = sorted
      .map(
        (p, idx) => `
      <tr class="post-row" data-idx="${idx}">
        <td><span class="expand-toggle">▸</span></td>
        <td>${p.thumbnail_url ? `<img src="${p.thumbnail_url}" style="width:28px;height:28px;object-fit:cover;border-radius:5px;">` : ""}</td>
        <td class="caption-cell" title="${(p.caption || "").replace(/"/g, "&quot;")}">${p.caption ? p.caption.slice(0, 40) : `<span class="na">${I18N.t("common.no_caption")}</span>`}</td>
        <td>${badgeFor(p.media_product_type)}</td>
        <td>${fmtDate(p.timestamp)}</td>
        <td>${fmtCompactCell(p.reach)}${insightsBadge(p)}</td>
        <td>${fmtCompactCell(p.views)}</td>
        <td>${fmtCompactCell(p.like_count)}</td>
        <td>${fmtCompactCell(p.comments_count)}</td>
        <td>${fmtCompactCell(p.saved)}</td>
        <td>${fmtCompactCell(p.shares)}</td>
        <td>${fmtPercent(p.engagement_rate)}</td>
        <td><label class="ad-toggle"><input type="checkbox" class="ad-checkbox" data-id="${p.id}" ${p.is_ad ? "checked" : ""}></label></td>
      </tr>
      <tr class="detail-row" data-idx="${idx}"><td colspan="13">${detailRowHtml(p)}</td></tr>`
      )
      .join("");

    tbody.querySelectorAll("tr.post-row").forEach((row) => {
      row.addEventListener("click", (e) => {
        if (e.target.closest(".ad-toggle")) return;
        row.classList.toggle("expanded");
        const detail = tbody.querySelector(`tr.detail-row[data-idx="${row.dataset.idx}"]`);
        detail.classList.toggle("show");
      });
    });

    tbody.querySelectorAll(".ad-checkbox").forEach((cb) => {
      cb.addEventListener("click", (e) => e.stopPropagation());
      cb.addEventListener("change", async () => {
        const id = cb.dataset.id;
        const post = currentPosts.find((p) => p.id === id);
        try {
          const res = await fetch(`/api/metrics/${id}/ad-flag`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ is_ad: cb.checked }),
          });
          if (!res.ok) throw new Error("save failed");
          if (post) post.is_ad = cb.checked;
        } catch (e) {
          cb.checked = !cb.checked;
          alert(I18N.t("metrics.msg.ad_flag_failed", { message: e.message }));
        }
      });
    });

    headers.forEach((h) => {
      h.classList.remove("sorted", "asc");
      if (h.dataset.key === sortKey) {
        h.classList.add("sorted");
        if (sortAsc) h.classList.add("asc");
      }
    });
  }

  headers.forEach((h) => {
    h.addEventListener("click", () => {
      if (!h.dataset.key || h.dataset.key === "thumbnail") return;
      if (sortKey === h.dataset.key) {
        sortAsc = !sortAsc;
      } else {
        sortKey = h.dataset.key;
        sortAsc = false;
      }
      sortAndRenderTable();
    });
  });

  syncBtn.addEventListener("click", async () => {
    syncBtn.disabled = true;
    syncBtn.textContent = I18N.t("metrics.msg.syncing");
    syncMeta.textContent = I18N.t("metrics.msg.sync_in_progress");
    try {
      const res = await fetch("/api/metrics/sync", { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        syncMeta.textContent = I18N.t("common.error") + ": " + (data.error || I18N.t("metrics.msg.sync_failed"));
        return;
      }
      render(data);
    } catch (e) {
      syncMeta.textContent = I18N.t("common.network_error", { message: e.message });
    } finally {
      syncBtn.disabled = false;
      syncBtn.textContent = I18N.t("metrics.sync_btn");
    }
  });

  async function loadCached() {
    const res = await fetch("/api/metrics");
    const data = await res.json();
    if (data.posts && data.posts.length) render(data);
  }

  document.addEventListener("langchange", () => {
    if (lastData) render(lastData);
  });

  loadCached();

  // «обновлено N мин назад» тикает без сетевых запросов; сами данные — фоновое авто-обновление
  // (см. app/scheduler.py) раз в несколько часов пишет media_cache.json, а этот опрос раз
  // в 5 минут подхватывает его на открытой вкладке без ручного нажатия «Синхронизировать».
  setInterval(updateSyncAgo, 30 * 1000);
  setInterval(loadCached, 5 * 60 * 1000);
})();
