(function () {
  const subtitle = document.getElementById("tiktok-subtitle");
  const notConnected = document.getElementById("tiktok-not-connected");
  const connectedContent = document.getElementById("tiktok-connected-content");
  const gotoSettingsBtn = document.getElementById("btn-tiktok-goto-settings");
  const diagnosticBtn = document.getElementById("btn-tiktok-diagnostic");
  const diagnosticStatus = document.getElementById("tiktok-diagnostic-status");
  const diagnosticResult = document.getElementById("tiktok-diagnostic-result");

  let lastDiagnostic = null;

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function fieldListHtml(fields) {
    if (!fields || !fields.length) return `<span class="na">—</span>`;
    return fields.map((f) => `<code>${escapeHtml(f)}</code>`).join(" ");
  }

  function sectionHtml(headingKey, block) {
    if (!block) return "";
    if (block.error) {
      return `
        <div class="card">
          <h3>${I18N.t(headingKey)}</h3>
          <div class="status-box show error">${I18N.t("tiktok.diagnostic.error")}: ${escapeHtml(block.error)}</div>
        </div>`;
    }
    return "";
  }

  function renderDiagnostic(data) {
    lastDiagnostic = data;
    const parts = [];

    if (data.user_info) {
      if (data.user_info.error) {
        parts.push(sectionHtml("tiktok.diagnostic.user_heading", data.user_info));
      } else {
        parts.push(`
          <div class="card">
            <h3>${I18N.t("tiktok.diagnostic.user_heading")}</h3>
            <div class="field"><label>${I18N.t("tiktok.diagnostic.fields_present")}</label><div>${fieldListHtml(data.user_info.fields_present)}</div></div>
            <div class="field"><label>${I18N.t("tiktok.diagnostic.fields_missing")}</label><div>${fieldListHtml(data.user_info.fields_missing)}</div></div>
            <details style="margin-top:8px;"><summary>${I18N.t("tiktok.diagnostic.raw_heading")}</summary><pre style="white-space:pre-wrap; overflow-wrap:anywhere;">${escapeHtml(JSON.stringify(data.user_info.raw, null, 2))}</pre></details>
          </div>`);
      }
    }

    if (data.videos) {
      if (data.videos.error) {
        parts.push(sectionHtml("tiktok.diagnostic.video_heading", data.videos));
      } else {
        parts.push(`
          <div class="card">
            <h3>${I18N.t("tiktok.diagnostic.video_heading")}</h3>
            <div class="meta">${I18N.t("tiktok.diagnostic.videos_count", { count: data.videos.count_returned })}</div>
            <div class="field"><label>${I18N.t("tiktok.diagnostic.fields_present")}</label><div>${fieldListHtml(data.videos.sample_fields_present)}</div></div>
            <div class="field"><label>${I18N.t("tiktok.diagnostic.fields_missing")}</label><div>${fieldListHtml(data.videos.fields_missing_in_sample)}</div></div>
            <details style="margin-top:8px;"><summary>${I18N.t("tiktok.diagnostic.raw_heading")}</summary><pre style="white-space:pre-wrap; overflow-wrap:anywhere;">${escapeHtml(JSON.stringify(data.videos.raw, null, 2))}</pre></details>
          </div>`);
      }
    }

    diagnosticResult.innerHTML = parts.join("");
    diagnosticResult.style.display = "block";
  }

  async function loadStatus() {
    const res = await fetch("/api/tiktok/status");
    const data = await res.json();
    if (data.connected) {
      notConnected.style.display = "none";
      connectedContent.style.display = "block";
      subtitle.textContent = I18N.t("tiktok.subtitle_connected", { username: data.username || data.display_name || data.open_id });
    } else {
      notConnected.style.display = "block";
      connectedContent.style.display = "none";
      subtitle.textContent = I18N.t("tiktok.subtitle_not_connected");
    }
  }

  gotoSettingsBtn?.addEventListener("click", () => {
    document.querySelector('.tab-btn[data-tab="settings"]')?.click();
  });

  diagnosticBtn?.addEventListener("click", async () => {
    diagnosticBtn.disabled = true;
    diagnosticStatus.className = "status-box show";
    diagnosticStatus.textContent = I18N.t("tiktok.diagnostic.running");
    diagnosticResult.style.display = "none";
    try {
      const res = await fetch("/api/tiktok/diagnostic");
      const data = await res.json();
      if (!res.ok) {
        diagnosticStatus.className = "status-box show error";
        diagnosticStatus.textContent = data.error || I18N.t("tiktok.diagnostic.error");
        return;
      }
      diagnosticStatus.className = "status-box show ok";
      diagnosticStatus.textContent = "";
      renderDiagnostic(data);
    } catch (e) {
      diagnosticStatus.className = "status-box show error";
      diagnosticStatus.textContent = I18N.t("common.network_error", { message: e.message });
    } finally {
      diagnosticBtn.disabled = false;
    }
  });

  document.addEventListener("langchange", () => {
    if (lastDiagnostic) renderDiagnostic(lastDiagnostic);
  });

  loadStatus();
})();
