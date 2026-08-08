(function () {
  const syncBtn = document.getElementById("btn-stories-sync");
  const syncMeta = document.getElementById("stories-sync-meta");
  const syncAgo = document.getElementById("stories-sync-ago");
  const subtitle = document.getElementById("stories-subtitle");
  const content = document.getElementById("stories-content");
  const emptyState = document.getElementById("stories-empty");
  const reachBreakdownBody = document.getElementById("reach-breakdown-body");
  const tbody = document.getElementById("stories-tbody");
  const tableMeta = document.getElementById("stories-table-meta");

  let lastData = null;

  function fmtDateTime(iso) {
    if (!iso) return '<span class="na">—</span>';
    const d = new Date(iso);
    return d.toLocaleString(I18N.locale(), { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  // Сторіс живе в Instagram ~24 год з моменту публікації — після цього вона архівна:
  // ми й далі показуємо накопичену історію метрик, лише позначка змінюється.
  const STORY_LIVE_HOURS = 24;

  function isLive(timestamp) {
    if (!timestamp) return false;
    const ageHours = (Date.now() - new Date(timestamp).getTime()) / 3600000;
    return ageHours >= 0 && ageHours < STORY_LIVE_HOURS;
  }

  function renderReachBreakdown(rb) {
    if (!rb || !rb.available) {
      reachBreakdownBody.innerHTML = `<div class="na">${(rb && rb.note) || I18N.t("stories.card.reach_breakdown_unavailable")}</div>`;
      return;
    }
    const cards = [
      { label: I18N.t("stories.card.follower"), value: rb.follower },
      { label: I18N.t("stories.card.non_follower"), value: rb.non_follower },
      { label: I18N.t("stories.card.total_reach"), value: rb.total },
    ];
    const pctBlock =
      rb.follower_pct !== null && rb.follower_pct !== undefined
        ? `<div class="top-card"><div class="label">${I18N.t("stories.card.follower_pct_label")}</div><div class="value">${rb.follower_pct}%</div></div>`
        : "";
    reachBreakdownBody.innerHTML = `<div class="top-cards">
      ${pctBlock}
      ${cards
        .map(
          (c) => `<div class="top-card">
            <div class="label">${c.label}</div>
            <div class="value">${fmtNumber(c.value)}</div>
          </div>`
        )
        .join("")}
    </div>`;
  }

  function insightsBadge(story) {
    if (story.insights_status === "ok") return "";
    return `<div class="na" style="font-size:11px; margin-top:2px;">${story.insights_reason || I18N.t("common.no_data")}</div>`;
  }

  function detailRowHtml(s) {
    return `
      <div class="detail-grid">
        <div><div class="k">${I18N.t("stories.detail.story_id")}</div><div class="v" style="font-weight:400;">${s.id}</div></div>
        <div><div class="k">${I18N.t("stories.detail.first_synced_at")}</div><div class="v">${fmtDateTime(s.first_synced_at)}</div></div>
        <div><div class="k">${I18N.t("stories.detail.last_synced_at")}</div><div class="v">${fmtDateTime(s.last_synced_at)}</div></div>
        <div><div class="k">${I18N.t("stories.th.profile_activity")}</div><div class="v">${fmtNumber(s.profile_activity)}</div></div>
      </div>
      ${s.permalink ? `<div style="margin-top:10px;"><a href="${s.permalink}" target="_blank" rel="noopener">${I18N.t("stories.detail.open_in_instagram")}</a></div>` : ""}
      ${
        s.insights_status !== "ok"
          ? `<div class="na" style="margin-top:8px;">${I18N.t("stories.detail.insights")} ${s.insights_reason || I18N.t("common.no_data")}</div>`
          : ""
      }
    `;
  }

  function renderTable(stories) {
    tableMeta.textContent = I18N.t("stories.table.meta", { count: stories.length });

    tbody.innerHTML = stories
      .map((s, idx) => {
        const live = isLive(s.timestamp);
        return `
      <tr class="post-row" data-idx="${idx}">
        <td><span class="expand-toggle">▸</span></td>
        <td>${s.thumbnail_url ? `<img src="${s.thumbnail_url}" style="width:28px;height:40px;object-fit:cover;border-radius:5px;">` : ""}</td>
        <td>${fmtDateTime(s.timestamp)}</td>
        <td><span class="badge ${live ? "status-active" : "status-paused"}">${live ? I18N.t("stories.status.live") : I18N.t("stories.status.archived")}</span></td>
        <td>${fmtCompactCell(s.reach)}${insightsBadge(s)}</td>
        <td>${fmtCompactCell(s.replies)}</td>
        <td>${fmtCompactCell(s.navigation)}</td>
        <td>${fmtCompactCell(s.profile_visits)}</td>
        <td>${fmtCompactCell(s.shares)}</td>
        <td>${fmtCompactCell(s.total_interactions)}</td>
        <td>${fmtCompactCell(s.follows)}</td>
      </tr>
      <tr class="detail-row" data-idx="${idx}"><td colspan="11">${detailRowHtml(s)}</td></tr>`;
      })
      .join("");

    tbody.querySelectorAll("tr.post-row").forEach((row) => {
      row.addEventListener("click", () => {
        row.classList.toggle("expanded");
        const detail = tbody.querySelector(`tr.detail-row[data-idx="${row.dataset.idx}"]`);
        detail.classList.toggle("show");
      });
    });
  }

  function render(data) {
    lastData = data;
    updateSyncAgo();

    const stories = data.stories || [];
    if (stories.length === 0) {
      content.style.display = "none";
      emptyState.style.display = "block";
      subtitle.textContent = I18N.t("stories.subtitle_default");
      return;
    }

    emptyState.style.display = "none";
    content.style.display = "block";

    const syncedAt = data.synced_at ? new Date(data.synced_at).toLocaleString(I18N.locale()) : "";
    subtitle.textContent = data.ig_username ? I18N.t("stories.subtitle_account", { username: data.ig_username }) : "";
    syncMeta.textContent = syncedAt
      ? I18N.t("stories.sync_meta", { synced_at: syncedAt, active: data.active_count || 0, total: stories.length })
      : "";

    renderReachBreakdown(data.reach_follow_type);
    renderTable(stories);
  }

  function updateSyncAgo() {
    syncAgo.textContent = lastData && lastData.synced_at ? timeAgoText(lastData.synced_at) : "";
  }

  syncBtn.addEventListener("click", async () => {
    syncBtn.disabled = true;
    syncBtn.textContent = I18N.t("stories.msg.syncing");
    syncMeta.textContent = I18N.t("stories.msg.sync_in_progress");
    try {
      const res = await fetch("/api/stories/sync", { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        syncMeta.textContent = I18N.t("common.error") + ": " + (data.error || I18N.t("stories.msg.sync_failed"));
        return;
      }
      render(data);
    } catch (e) {
      syncMeta.textContent = I18N.t("common.network_error", { message: e.message });
    } finally {
      syncBtn.disabled = false;
      syncBtn.textContent = I18N.t("stories.sync_btn");
    }
  });

  async function loadCached() {
    const res = await fetch("/api/stories");
    const data = await res.json();
    if (data.stories && data.stories.length) render(data);
  }

  document.addEventListener("langchange", () => {
    if (lastData) render(lastData);
  });

  loadCached();

  setInterval(updateSyncAgo, 30 * 1000);
  setInterval(loadCached, 5 * 60 * 1000);
})();
