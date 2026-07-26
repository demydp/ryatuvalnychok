(function () {
  const STEPS = ["welcome", "ig", "ads", "anthropic", "model", "done"];
  const TOTAL = STEPS.length;

  const progressFill = document.getElementById("ob-progress-fill");
  const progressLabel = document.getElementById("ob-progress-label");

  let currentStep = "welcome";
  let obStatus = { ig_ok: false, ads_ok: false, anthropic_ok: false, model_downloaded: false };

  function showStep(name) {
    currentStep = name;
    document.querySelectorAll(".ob-step").forEach((el) => {
      el.style.display = el.dataset.step === name ? "block" : "none";
    });
    const idx = STEPS.indexOf(name);
    progressFill.style.width = `${Math.round(((idx + 1) / TOTAL) * 100)}%`;
    progressLabel.textContent = I18N.t("onboarding.progress", { current: idx + 1, total: TOTAL });
    if (name === "model") checkModelStatus();
  }

  function firstIncompleteStep() {
    if (!obStatus.ig_ok) return "ig";
    if (!obStatus.ads_ok) return "ads";
    if (!obStatus.anthropic_ok) return "anthropic";
    return "model";
  }

  document.querySelectorAll(".ob-back").forEach((btn) => {
    btn.addEventListener("click", () => {
      const idx = STEPS.indexOf(currentStep);
      if (idx > 0) showStep(STEPS[idx - 1]);
    });
  });

  document.getElementById("ob-start-btn").addEventListener("click", () => {
    showStep(firstIncompleteStep());
  });

  function setBusy(btn, busy, label) {
    btn.disabled = busy;
    btn.textContent = busy ? I18N.t("settings.msg.testing") : label;
  }

  // --- Instagram ---
  const igTokenInput = document.getElementById("ob-ig-token");
  const igStatus = document.getElementById("ob-ig-status");
  const igAccountChoice = document.getElementById("ob-ig-account-choice");
  const igTestBtn = document.getElementById("ob-test-ig");
  const igNextBtn = document.getElementById("ob-next-ig");

  function showIgStatus(type, message) {
    igStatus.className = `status-box show ${type}`;
    igStatus.textContent = message;
  }

  function renderIgAccountChoice(accounts) {
    igAccountChoice.style.display = "flex";
    igAccountChoice.innerHTML = "";
    accounts.forEach((acc) => {
      const btn = document.createElement("button");
      btn.textContent = `@${acc.username || I18N.t("common.no_name")} — ${acc.name || ""} (ID: ${acc.id})`;
      btn.addEventListener("click", () => selectIgAccount(acc.id));
      igAccountChoice.appendChild(btn);
    });
  }

  async function selectIgAccount(id) {
    setBusy(igTestBtn, true);
    try {
      const res = await fetch("/api/settings/select-account", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, ig_access_token: igTokenInput.value.trim() }),
      });
      const data = await res.json();
      if (!res.ok) {
        showIgStatus("error", data.error || I18N.t("settings.msg.account_select_error"));
        return;
      }
      igAccountChoice.style.display = "none";
      showIgStatus("ok", I18N.t("settings.msg.account_connected", { username: data.username, name: data.name || "", followers: data.followers_count ?? "?" }));
      obStatus.ig_ok = true;
      igNextBtn.disabled = false;
    } finally {
      setBusy(igTestBtn, false, I18N.t("settings.ig.test_btn"));
    }
  }

  igTestBtn.addEventListener("click", async () => {
    const token = igTokenInput.value.trim();
    if (!token) {
      showIgStatus("error", I18N.t("settings.msg.enter_ig_token"));
      return;
    }
    igAccountChoice.style.display = "none";
    setBusy(igTestBtn, true);
    try {
      const res = await fetch("/api/settings/test-connection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ig_access_token: token }),
      });
      const data = await res.json();
      if (!res.ok) {
        showIgStatus("error", data.error || I18N.t("settings.msg.connect_failed"));
        return;
      }
      if (data.multiple_accounts) {
        showIgStatus("ok", I18N.t("settings.msg.multiple_accounts"));
        renderIgAccountChoice(data.multiple_accounts);
        return;
      }
      showIgStatus("ok", I18N.t("settings.msg.connected", {
        username: data.username, name: data.name || "", followers: data.followers_count ?? "?", media_count: data.media_count ?? "?",
      }));
      obStatus.ig_ok = true;
      igNextBtn.disabled = false;
    } catch (e) {
      showIgStatus("error", I18N.t("settings.msg.network_error", { message: e.message }));
    } finally {
      setBusy(igTestBtn, false, I18N.t("settings.ig.test_btn"));
    }
  });

  igNextBtn.addEventListener("click", () => showStep("ads"));

  // --- Ads account ---
  const adsAccountInput = document.getElementById("ob-ads-account");
  const adsStatus = document.getElementById("ob-ads-status");
  const adsTestBtn = document.getElementById("ob-test-ads");
  const adsNextBtn = document.getElementById("ob-next-ads");

  adsTestBtn.addEventListener("click", async () => {
    const accountId = adsAccountInput.value.trim();
    if (!accountId) {
      adsStatus.className = "status-box show error";
      adsStatus.textContent = I18N.t("settings.msg.enter_ads_account");
      return;
    }
    setBusy(adsTestBtn, true);
    try {
      const res = await fetch("/api/ads/test-connection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ads_account_id: accountId }),
      });
      const data = await res.json();
      if (!res.ok) {
        adsStatus.className = "status-box show error";
        adsStatus.textContent = data.error || I18N.t("settings.msg.ads_connect_failed");
        return;
      }
      adsAccountInput.value = data.id;
      adsStatus.className = "status-box show ok";
      adsStatus.textContent = I18N.t("settings.msg.ads_connected", {
        name: data.name || I18N.t("common.no_name"), currency: data.currency, status: data.account_status_label,
      });
      obStatus.ads_ok = true;
      adsNextBtn.disabled = false;
    } catch (e) {
      adsStatus.className = "status-box show error";
      adsStatus.textContent = I18N.t("settings.msg.network_error", { message: e.message });
    } finally {
      setBusy(adsTestBtn, false, I18N.t("settings.ads.test_btn"));
    }
  });

  adsNextBtn.addEventListener("click", () => showStep("anthropic"));

  // --- Anthropic ---
  const anthropicInput = document.getElementById("ob-anthropic-key");
  const anthropicStatus = document.getElementById("ob-anthropic-status");
  const anthropicTestBtn = document.getElementById("ob-test-anthropic");
  const anthropicNextBtn = document.getElementById("ob-next-anthropic");

  anthropicTestBtn.addEventListener("click", async () => {
    const key = anthropicInput.value.trim();
    if (!key) {
      anthropicStatus.className = "status-box show error";
      anthropicStatus.textContent = I18N.t("settings.msg.enter_anthropic_key");
      return;
    }
    setBusy(anthropicTestBtn, true);
    try {
      const res = await fetch("/api/settings/test-anthropic-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ anthropic_api_key: key }),
      });
      const data = await res.json();
      anthropicStatus.className = `status-box show ${res.ok ? "ok" : "error"}`;
      anthropicStatus.textContent = res.ok ? I18N.t("settings.msg.anthropic_ok") : data.error || I18N.t("settings.msg.anthropic_check_error");
      if (res.ok) {
        obStatus.anthropic_ok = true;
        anthropicNextBtn.disabled = false;
      }
    } catch (e) {
      anthropicStatus.className = "status-box show error";
      anthropicStatus.textContent = I18N.t("settings.msg.network_error", { message: e.message });
    } finally {
      setBusy(anthropicTestBtn, false, I18N.t("settings.anthropic.test_btn"));
    }
  });

  anthropicNextBtn.addEventListener("click", () => showStep("model"));

  // --- Whisper model ---
  const modelProgressBox = document.getElementById("ob-model-progress");
  const modelFill = document.getElementById("ob-model-fill");
  const modelLabel = document.getElementById("ob-model-label");
  const modelStatusBox = document.getElementById("ob-model-status");
  const downloadModelBtn = document.getElementById("ob-download-model");
  const skipModelBtn = document.getElementById("ob-skip-model");
  const modelNextBtn = document.getElementById("ob-next-model");
  let modelPollTimer = null;

  async function checkModelStatus() {
    try {
      const res = await fetch("/api/onboarding/status");
      const data = await res.json();
      if (data.model_downloaded) {
        modelStatusBox.className = "status-box show ok";
        modelStatusBox.textContent = I18N.t("onboarding.step.model.done");
        downloadModelBtn.style.display = "none";
        skipModelBtn.style.display = "none";
        modelNextBtn.style.display = "inline-flex";
      }
    } catch (e) {
      // молча — просто оставляем кнопку "Скачать" доступной
    }
  }

  downloadModelBtn.addEventListener("click", async () => {
    downloadModelBtn.disabled = true;
    modelProgressBox.style.display = "flex";
    modelFill.style.width = "0%";
    await fetch("/api/onboarding/download-model", { method: "POST" });
    modelPollTimer = setInterval(pollModelDownload, 700);
  });

  async function pollModelDownload() {
    try {
      const res = await fetch("/api/onboarding/download-model/status");
      const data = await res.json();
      if (data.status === "downloading") {
        modelFill.style.width = `${data.percent}%`;
        modelLabel.textContent = I18N.t("onboarding.step.model.downloading", { percent: data.percent });
      } else if (data.status === "done") {
        clearInterval(modelPollTimer);
        modelFill.style.width = "100%";
        modelProgressBox.style.display = "none";
        modelStatusBox.className = "status-box show ok";
        modelStatusBox.textContent = I18N.t("onboarding.step.model.done");
        downloadModelBtn.style.display = "none";
        skipModelBtn.style.display = "none";
        modelNextBtn.style.display = "inline-flex";
      } else if (data.status === "error") {
        clearInterval(modelPollTimer);
        modelProgressBox.style.display = "none";
        modelStatusBox.className = "status-box show error";
        modelStatusBox.textContent = I18N.t("onboarding.step.model.error", { error: data.error || "" });
        downloadModelBtn.disabled = false;
      }
    } catch (e) {
      clearInterval(modelPollTimer);
    }
  }

  skipModelBtn.addEventListener("click", () => showStep("done"));
  modelNextBtn.addEventListener("click", () => showStep("done"));

  // --- Готово ---
  document.getElementById("ob-finish-btn").addEventListener("click", async () => {
    const res = await fetch("/api/onboarding/complete", { method: "POST" });
    if (res.ok) {
      window.location.href = "/";
    } else {
      const data = await res.json();
      alert(data.error || I18N.t("onboarding.msg.not_ready"));
    }
  });

  // --- prefill + resume ---
  async function init() {
    try {
      const [cfgRes, statusRes] = await Promise.all([fetch("/api/settings"), fetch("/api/onboarding/status")]);
      const cfg = await cfgRes.json();
      obStatus = await statusRes.json();
      if (cfg.ig_access_token) igTokenInput.value = cfg.ig_access_token;
      if (cfg.ads_account_id) adsAccountInput.value = cfg.ads_account_id;
      if (cfg.anthropic_api_key) anthropicInput.value = cfg.anthropic_api_key;
      if (obStatus.ig_ok) igNextBtn.disabled = false;
      if (obStatus.ads_ok) adsNextBtn.disabled = false;
      if (obStatus.anthropic_ok) anthropicNextBtn.disabled = false;
    } catch (e) {
      // офлайн при старте — просто начинаем с чистого мастера
    }
    showStep("welcome");
  }

  init();
})();
