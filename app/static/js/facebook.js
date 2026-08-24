(function () {
  const syncBtn = document.getElementById("btn-facebook-sync");
  const syncMeta = document.getElementById("facebook-sync-meta");
  const syncAgo = document.getElementById("facebook-sync-ago");
  const subtitle = document.getElementById("facebook-subtitle");
  const content = document.getElementById("facebook-content");
  const emptyState = document.getElementById("facebook-empty");

  let lastData = null;

  function fmtDateTime(iso) {
    if (!iso) return '<span class="na">—</span>';
    const d = new Date(iso);
    return d.toLocaleString(I18N.locale(), { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function postHtml(post) {
    const thumb = post.full_picture
      ? `<img src="${post.full_picture}" style="width:56px;height:56px;object-fit:cover;border-radius:6px;flex:none;">`
      : `<div style="width:56px;height:56px;border-radius:6px;flex:none;background:var(--card-alt-bg,rgba(128,128,128,.15));"></div>`;
    const message = post.message
      ? post.message.length > 160
        ? post.message.slice(0, 160) + "…"
        : post.message
      : `<span class="na">${I18N.t("facebook.post.no_text")}</span>`;
    const link = post.permalink_url
      ? `<a href="${post.permalink_url}" target="_blank" rel="noopener">${I18N.t("facebook.post.open_on_facebook")}</a>`
      : "";
    return `
      <div style="display:flex; gap:12px; padding:10px 0; border-top:1px solid var(--border-color,rgba(128,128,128,.2));">
        ${thumb}
        <div style="min-width:0;">
          <div style="font-size:12px; color:var(--muted-fg,#888); margin-bottom:2px;">${fmtDateTime(post.created_time)}</div>
          <div style="overflow-wrap:anywhere;">${message}</div>
          ${link ? `<div style="margin-top:4px; font-size:13px;">${link}</div>` : ""}
        </div>
      </div>`;
  }

  function pageCardHtml(page) {
    const posts = page.posts || [];
    const postsHtml = posts.length
      ? posts.map(postHtml).join("")
      : `<div class="na" style="padding:10px 0;">${I18N.t("facebook.post.none")}</div>`;

    return `
      <div class="card">
        <div class="toolbar">
          <h2 style="margin:0;">${page.name || I18N.t("facebook.page.unnamed")}</h2>
        </div>
        <div class="top-cards">
          <div class="top-card">
            <div class="label">${I18N.t("facebook.card.fan_count")}</div>
            <div class="value">${fmtNumber(page.fan_count)}</div>
          </div>
          <div class="top-card">
            <div class="label">${I18N.t("facebook.card.followers_count")}</div>
            <div class="value">${fmtNumber(page.followers_count)}</div>
          </div>
        </div>
        <div style="margin-top:14px;">
          <div class="meta" style="margin-bottom:4px;">${I18N.t("facebook.posts.heading", { count: posts.length })}</div>
          ${postsHtml}
        </div>
      </div>`;
  }

  function render(data) {
    lastData = data;
    updateSyncAgo();

    const pages = data.pages || [];
    if (pages.length === 0) {
      content.style.display = "none";
      emptyState.style.display = "block";
      subtitle.textContent = I18N.t("facebook.subtitle_default");
      return;
    }

    emptyState.style.display = "none";
    content.style.display = "block";
    content.innerHTML = pages.map(pageCardHtml).join("");

    const syncedAt = data.synced_at ? new Date(data.synced_at).toLocaleString(I18N.locale()) : "";
    subtitle.textContent = I18N.t("facebook.subtitle_pages", { count: pages.length });
    syncMeta.textContent = syncedAt ? I18N.t("facebook.sync_meta", { synced_at: syncedAt }) : "";
  }

  function updateSyncAgo() {
    syncAgo.textContent = lastData && lastData.synced_at ? timeAgoText(lastData.synced_at) : "";
  }

  syncBtn.addEventListener("click", async () => {
    syncBtn.disabled = true;
    syncBtn.textContent = I18N.t("facebook.msg.syncing");
    syncMeta.textContent = I18N.t("facebook.msg.sync_in_progress");
    try {
      const res = await fetch("/api/facebook/sync", { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        syncMeta.textContent = I18N.t("common.error") + ": " + (data.error || I18N.t("facebook.msg.sync_failed"));
        return;
      }
      render(data);
    } catch (e) {
      syncMeta.textContent = I18N.t("common.network_error", { message: e.message });
    } finally {
      syncBtn.disabled = false;
      syncBtn.textContent = I18N.t("facebook.sync_btn");
    }
  });

  async function loadCached() {
    const res = await fetch("/api/facebook");
    const data = await res.json();
    if (data.pages && data.pages.length) render(data);
  }

  document.addEventListener("langchange", () => {
    if (lastData) render(lastData);
  });

  loadCached();

  setInterval(updateSyncAgo, 30 * 1000);
})();
