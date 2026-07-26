(function () {
  const maxMediaInput = document.getElementById("max-media");
  const anthropicInput = document.getElementById("anthropic-key");
  const contentLanguageSelect = document.getElementById("content-language");
  const whisperModelSelect = document.getElementById("whisper-model");
  const testAnthropicBtn = document.getElementById("btn-test-anthropic");
  const anthropicStatus = document.getElementById("anthropic-status");
  const saveBtn = document.getElementById("btn-save-settings");
  const saveStatus = document.getElementById("save-status");
  const tokenStatusBox = document.getElementById("token-status-box");
  const refreshTokenBtn = document.getElementById("btn-refresh-token");
  const networkInfoBox = document.getElementById("network-info-box");

  async function loadNetworkInfo() {
    try {
      const res = await fetch("/api/settings/network-info");
      const data = await res.json();
      networkInfoBox.className = "status-box show ok";
      networkInfoBox.innerHTML = `
        <span>${I18N.t("settings.network.phone_label")}: <strong>${data.lan_url}</strong></span>
        <span style="color:var(--muted); font-size:12px;">${I18N.t("settings.network.same_wifi_note")}</span>
      `;
    } catch (e) {
      networkInfoBox.className = "status-box show error";
      networkInfoBox.textContent = I18N.t("settings.msg.network_error", { message: e.message });
    }
  }

  async function loadSettings() {
    const res = await fetch("/api/settings");
    const cfg = await res.json();
    if (cfg.anthropic_api_key) anthropicInput.value = cfg.anthropic_api_key;
    if (cfg.max_media) maxMediaInput.value = cfg.max_media;
    if (cfg.content_language !== undefined) contentLanguageSelect.value = cfg.content_language;
    if (cfg.whisper_model) whisperModelSelect.value = cfg.whisper_model;
  }

  async function loadTokenStatus() {
    try {
      const res = await fetch("/api/settings/token-status");
      const data = await res.json();
      renderTokenStatus(data);
    } catch (e) {
      tokenStatusBox.className = "status-box show error";
      tokenStatusBox.textContent = I18N.t("settings.msg.network_error", { message: e.message });
    }
  }

  function renderTokenStatus(data) {
    if (data.is_valid === null) {
      tokenStatusBox.className = "status-box show warn";
      tokenStatusBox.textContent = data.error
        ? I18N.t("settings.token.check_failed", { error: data.error })
        : I18N.t("settings.token.no_token");
      return;
    }
    if (data.is_valid === false) {
      tokenStatusBox.className = "status-box show error";
      tokenStatusBox.textContent = I18N.t("settings.token.invalid", { error: data.error || "" });
      return;
    }
    if (!data.expires_at) {
      tokenStatusBox.className = "status-box show ok";
      tokenStatusBox.textContent = I18N.t("settings.token.valid_no_expiry");
      return;
    }
    const daysLeft = Math.ceil((new Date(data.expires_at) - new Date()) / 86400000);
    const dateLabel = new Date(data.expires_at).toLocaleDateString();
    if (daysLeft <= 10) {
      tokenStatusBox.className = "status-box show error";
      tokenStatusBox.textContent = I18N.t("settings.token.expiring_soon", { days: daysLeft, date: dateLabel });
    } else if (daysLeft <= 21) {
      tokenStatusBox.className = "status-box show warn";
      tokenStatusBox.textContent = I18N.t("settings.token.expiring_warn", { days: daysLeft, date: dateLabel });
    } else {
      tokenStatusBox.className = "status-box show ok";
      tokenStatusBox.textContent = I18N.t("settings.token.valid_until", { days: daysLeft, date: dateLabel });
    }
  }

  refreshTokenBtn.addEventListener("click", async () => {
    refreshTokenBtn.disabled = true;
    refreshTokenBtn.textContent = I18N.t("settings.msg.testing");
    try {
      const res = await fetch("/api/settings/refresh-token", { method: "POST" });
      const data = await res.json();
      if (data.action === "refreshed") {
        tokenStatusBox.className = "status-box show ok";
        tokenStatusBox.textContent = I18N.t("settings.token.refreshed_ok", {
          date: data.expires_at ? new Date(data.expires_at).toLocaleDateString() : "?",
        });
      } else if (data.action === "failed") {
        tokenStatusBox.className = "status-box show error";
        tokenStatusBox.textContent = I18N.t("settings.token.refresh_failed", { reason: data.reason || "" });
      } else {
        tokenStatusBox.className = "status-box show ok";
        tokenStatusBox.textContent = I18N.t("settings.token.refresh_not_needed", { reason: data.reason || "" });
      }
    } catch (e) {
      tokenStatusBox.className = "status-box show error";
      tokenStatusBox.textContent = I18N.t("settings.msg.network_error", { message: e.message });
    } finally {
      refreshTokenBtn.disabled = false;
      refreshTokenBtn.textContent = I18N.t("settings.token.refresh_btn");
      loadTokenStatus();
    }
  });

  function setBusy(btn, busy, label) {
    btn.disabled = busy;
    btn.textContent = busy ? I18N.t("settings.msg.testing") : label || btn.dataset.label || btn.textContent;
  }

  testAnthropicBtn.addEventListener("click", async () => {
    const key = anthropicInput.value.trim();
    if (!key) {
      anthropicStatus.className = "status-box show error";
      anthropicStatus.textContent = I18N.t("settings.msg.enter_anthropic_key");
      return;
    }
    testAnthropicBtn.disabled = true;
    testAnthropicBtn.textContent = I18N.t("settings.msg.testing");
    try {
      const res = await fetch("/api/settings/test-anthropic-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ anthropic_api_key: key }),
      });
      const data = await res.json();
      anthropicStatus.className = `status-box show ${res.ok ? "ok" : "error"}`;
      anthropicStatus.textContent = res.ok ? I18N.t("settings.msg.anthropic_ok") : data.error || I18N.t("settings.msg.anthropic_check_error");
    } catch (e) {
      anthropicStatus.className = "status-box show error";
      anthropicStatus.textContent = I18N.t("settings.msg.network_error", { message: e.message });
    } finally {
      testAnthropicBtn.disabled = false;
      testAnthropicBtn.textContent = I18N.t("settings.anthropic.test_btn");
    }
  });

  saveBtn.addEventListener("click", async () => {
    saveStatus.textContent = I18N.t("settings.msg.saving");
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        anthropic_api_key: anthropicInput.value.trim(),
        max_media: parseInt(maxMediaInput.value, 10) || 100,
        content_language: contentLanguageSelect.value,
        whisper_model: whisperModelSelect.value,
      }),
    });
    if (res.ok) {
      saveStatus.textContent = I18N.t("common.saved_ok");
      setTimeout(() => (saveStatus.textContent = ""), 2500);
    } else {
      const data = await res.json();
      saveStatus.textContent = I18N.t("settings.msg.save_error", { message: data.error || I18N.t("settings.msg.save_failed") });
    }
  });

  // --- Проєкти (Фаза 5) ---
  const projectsListEl = document.getElementById("projects-list");
  const newProjectNameInput = document.getElementById("new-project-name");
  const addProjectBtn = document.getElementById("btn-add-project");

  let projects = [];
  let activeProjectId = null;

  function escapeAttr(value) {
    return String(value || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }

  async function loadProjects() {
    const res = await fetch("/api/projects");
    const data = await res.json();
    projects = data.projects || [];
    activeProjectId = data.active_id;
    renderProjects();
  }

  function projectCardHtml(p) {
    const isActive = p.id === activeProjectId;
    const badge = isActive
      ? `<span class="badge status-active">${I18N.t("projects.badge.active")}</span>`
      : "";
    return `
      <div class="top-card category-card project-card" data-id="${p.id}">
        <div class="category-head">
          <span class="category-name">${escapeAttr(p.name)}</span>
          ${badge}
        </div>

        <div class="field">
          <label>${I18N.t("projects.name_label")}</label>
          <input type="text" class="project-name-input" value="${escapeAttr(p.name)}">
        </div>

        <div class="field">
          <label>${I18N.t("projects.ig_token_label")}</label>
          <input type="password" class="project-ig-token" value="${escapeAttr(p.ig_access_token)}" placeholder="EAAG...">
          <button class="btn secondary project-test-ig" data-label="${I18N.t("projects.test_ig_btn")}">${I18N.t("projects.test_ig_btn")}</button>
          <div class="status-box project-ig-status"></div>
          <div class="account-choice project-ig-choice" style="display:none;"></div>
        </div>

        <div class="field">
          <label>${I18N.t("projects.ads_account_label")}</label>
          <input type="text" class="project-ads-account" value="${escapeAttr(p.ads_account_id)}" placeholder="act_...">
          <button class="btn secondary project-test-ads" data-label="${I18N.t("projects.test_ads_btn")}">${I18N.t("projects.test_ads_btn")}</button>
          <div class="status-box project-ads-status"></div>
        </div>

        <div class="field">
          <label>${I18N.t("projects.niche_label")}</label>
          <input type="text" class="project-niche" value="${escapeAttr(p.account_niche)}">
        </div>

        <div class="field">
          <label>${I18N.t("projects.anthropic_override_label")}</label>
          <input type="password" class="project-anthropic-key" value="${escapeAttr(p.anthropic_api_key)}" placeholder="${I18N.t("projects.anthropic_override_placeholder")}">
          <button class="btn secondary project-test-anthropic" data-label="${I18N.t("projects.test_anthropic_btn")}">${I18N.t("projects.test_anthropic_btn")}</button>
          <div class="status-box project-anthropic-status"></div>
        </div>

        <div class="category-actions">
          <button class="btn project-save-btn">${I18N.t("projects.save_btn")}</button>
          ${isActive ? "" : `<button class="icon-btn project-activate-btn">${I18N.t("projects.activate_btn")}</button>`}
          <button class="icon-btn project-delete-btn">${I18N.t("projects.delete_btn")}</button>
        </div>
      </div>`;
  }

  function renderProjects() {
    projectsListEl.innerHTML = projects.map(projectCardHtml).join("");
    wireProjectCardEvents();
  }

  function projectFields(card) {
    return {
      name: card.querySelector(".project-name-input").value.trim(),
      ig_access_token: card.querySelector(".project-ig-token").value.trim(),
      ads_account_id: card.querySelector(".project-ads-account").value.trim(),
      account_niche: card.querySelector(".project-niche").value.trim(),
      anthropic_api_key: card.querySelector(".project-anthropic-key").value.trim(),
    };
  }

  function wireProjectCardEvents() {
    projectsListEl.querySelectorAll(".project-card").forEach((card) => {
      const projectId = card.dataset.id;

      card.querySelector(".project-save-btn").addEventListener("click", async () => {
        const res = await fetch(`/api/projects/${projectId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(projectFields(card)),
        });
        const data = await res.json();
        if (!res.ok) {
          alert(data.error || I18N.t("projects.msg.save_error"));
          return;
        }
        await loadProjects();
      });

      card.querySelector(".project-activate-btn")?.addEventListener("click", async () => {
        await fetch(`/api/projects/${projectId}/activate`, { method: "POST" });
        location.reload();
      });

      card.querySelector(".project-delete-btn").addEventListener("click", async () => {
        if (!confirm(I18N.t("projects.confirm_delete"))) return;
        const res = await fetch(`/api/projects/${projectId}`, { method: "DELETE" });
        const data = await res.json();
        if (!res.ok) {
          alert(data.error || I18N.t("projects.msg.delete_error"));
          return;
        }
        location.reload();
      });

      const igBtn = card.querySelector(".project-test-ig");
      const igStatus = card.querySelector(".project-ig-status");
      const igChoice = card.querySelector(".project-ig-choice");

      async function selectIgAccount(id) {
        setBusy(igBtn, true);
        try {
          const res = await fetch("/api/settings/select-account", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              id,
              project_id: projectId,
              ig_access_token: card.querySelector(".project-ig-token").value.trim(),
            }),
          });
          const data = await res.json();
          if (!res.ok) {
            igStatus.className = "status-box show error";
            igStatus.textContent = data.error || I18N.t("settings.msg.account_select_error");
            return;
          }
          igChoice.style.display = "none";
          igStatus.className = "status-box show ok";
          igStatus.textContent = I18N.t("settings.msg.account_connected", {
            username: data.username, name: data.name || "", followers: data.followers_count ?? "?",
          });
        } finally {
          setBusy(igBtn, false);
        }
      }

      igBtn.addEventListener("click", async () => {
        const token = card.querySelector(".project-ig-token").value.trim();
        if (!token) {
          igStatus.className = "status-box show error";
          igStatus.textContent = I18N.t("settings.msg.enter_ig_token");
          return;
        }
        igChoice.style.display = "none";
        setBusy(igBtn, true);
        try {
          const res = await fetch("/api/settings/test-connection", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ig_access_token: token, project_id: projectId }),
          });
          const data = await res.json();
          if (!res.ok) {
            igStatus.className = "status-box show error";
            igStatus.textContent = data.error || I18N.t("settings.msg.connect_failed");
            return;
          }
          if (data.multiple_accounts) {
            igStatus.className = "status-box show ok";
            igStatus.textContent = I18N.t("settings.msg.multiple_accounts");
            igChoice.style.display = "flex";
            igChoice.innerHTML = "";
            data.multiple_accounts.forEach((acc) => {
              const btn = document.createElement("button");
              btn.textContent = `@${acc.username || I18N.t("common.no_name")} — ${acc.name || ""} (ID: ${acc.id})`;
              btn.addEventListener("click", () => selectIgAccount(acc.id));
              igChoice.appendChild(btn);
            });
            return;
          }
          igStatus.className = "status-box show ok";
          igStatus.textContent = I18N.t("settings.msg.connected", {
            username: data.username, name: data.name || "", followers: data.followers_count ?? "?", media_count: data.media_count ?? "?",
          });
        } catch (e) {
          igStatus.className = "status-box show error";
          igStatus.textContent = I18N.t("settings.msg.network_error", { message: e.message });
        } finally {
          setBusy(igBtn, false);
        }
      });

      const adsBtn = card.querySelector(".project-test-ads");
      const adsStatusEl = card.querySelector(".project-ads-status");
      adsBtn.addEventListener("click", async () => {
        const accountId = card.querySelector(".project-ads-account").value.trim();
        if (!accountId) {
          adsStatusEl.className = "status-box show error";
          adsStatusEl.textContent = I18N.t("settings.msg.enter_ads_account");
          return;
        }
        setBusy(adsBtn, true);
        try {
          const res = await fetch("/api/ads/test-connection", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ads_account_id: accountId, project_id: projectId }),
          });
          const data = await res.json();
          if (!res.ok) {
            adsStatusEl.className = "status-box show error";
            adsStatusEl.textContent = data.error || I18N.t("settings.msg.ads_connect_failed");
            return;
          }
          card.querySelector(".project-ads-account").value = data.id;
          adsStatusEl.className = "status-box show ok";
          adsStatusEl.textContent = I18N.t("settings.msg.ads_connected", {
            name: data.name || I18N.t("common.no_name"), currency: data.currency, status: data.account_status_label,
          });
        } catch (e) {
          adsStatusEl.className = "status-box show error";
          adsStatusEl.textContent = I18N.t("settings.msg.network_error", { message: e.message });
        } finally {
          setBusy(adsBtn, false);
        }
      });

      const anthropicBtn = card.querySelector(".project-test-anthropic");
      const anthropicStatusEl = card.querySelector(".project-anthropic-status");
      anthropicBtn.addEventListener("click", async () => {
        const key = card.querySelector(".project-anthropic-key").value.trim();
        if (!key) {
          anthropicStatusEl.className = "status-box show error";
          anthropicStatusEl.textContent = I18N.t("settings.msg.enter_anthropic_key");
          return;
        }
        setBusy(anthropicBtn, true);
        try {
          const res = await fetch("/api/settings/test-anthropic-key", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ anthropic_api_key: key, project_id: projectId }),
          });
          const data = await res.json();
          anthropicStatusEl.className = `status-box show ${res.ok ? "ok" : "error"}`;
          anthropicStatusEl.textContent = res.ok
            ? I18N.t("settings.msg.anthropic_ok")
            : data.error || I18N.t("settings.msg.anthropic_check_error");
        } catch (e) {
          anthropicStatusEl.className = "status-box show error";
          anthropicStatusEl.textContent = I18N.t("settings.msg.network_error", { message: e.message });
        } finally {
          setBusy(anthropicBtn, false);
        }
      });
    });
  }

  addProjectBtn.addEventListener("click", async () => {
    const name = newProjectNameInput.value.trim();
    if (!name) {
      alert(I18N.t("projects.msg.enter_name"));
      return;
    }
    const res = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.error || I18N.t("projects.msg.save_error"));
      return;
    }
    newProjectNameInput.value = "";
    location.reload();
  });

  // --- Обновления ---
  const checkUpdatesBtn = document.getElementById("btn-check-updates");
  const updateStatus = document.getElementById("update-status");
  const currentVersionEl = document.getElementById("update-current-version");

  function renderCurrentVersion() {
    currentVersionEl.textContent = I18N.t("settings.updates.current_version", { version: currentVersionEl.dataset.version });
  }

  checkUpdatesBtn.addEventListener("click", async () => {
    checkUpdatesBtn.disabled = true;
    updateStatus.className = "status-box show";
    updateStatus.textContent = I18N.t("settings.updates.checking");
    try {
      const res = await fetch("/api/updates/check");
      const data = await res.json();
      if (!res.ok || !data.update_available) {
        // Пока нет опубликованных релизов на GitHub, проверка обновлений всегда "не удаётся" —
        // с точки зрения пользователя это неотличимо от "обновлений нет", красную ошибку не
        // показываем ни при каком сбое проверки (см. app/routes/updates.py).
        updateStatus.className = "status-box show ok";
        updateStatus.textContent = I18N.t("settings.updates.up_to_date");
        return;
      }
      updateStatus.className = "status-box show warn";
      updateStatus.innerHTML = "";
      const label = document.createElement("div");
      label.textContent = I18N.t("settings.updates.available", { version: data.latest_version });
      updateStatus.appendChild(label);
      const installBtn = document.createElement("button");
      installBtn.className = "btn";
      installBtn.style.marginTop = "10px";
      installBtn.textContent = I18N.t("settings.updates.install_btn");
      installBtn.addEventListener("click", async () => {
        installBtn.disabled = true;
        updateStatus.className = "status-box show warn";
        updateStatus.textContent = I18N.t("settings.updates.installing");
        try {
          await fetch("/api/updates/apply", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: data.download_url }),
          });
        } catch (e) {
          // Приложение вот-вот закроется само (см. app/update_checker.py) — обрыв
          // соединения здесь ожидаем, а не ошибка.
        }
      });
      updateStatus.appendChild(installBtn);
    } catch (e) {
      updateStatus.className = "status-box show ok";
      updateStatus.textContent = I18N.t("settings.updates.up_to_date");
    } finally {
      checkUpdatesBtn.disabled = false;
    }
  });

  renderCurrentVersion();
  loadSettings();
  loadProjects();
  loadTokenStatus();
  loadNetworkInfo();
})();
