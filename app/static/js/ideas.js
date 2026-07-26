(function () {
  const emptyState = document.getElementById("ideas-empty");
  const mainEl = document.getElementById("ideas-main");
  const goSettingsBtn = document.getElementById("btn-ideas-go-settings");
  const modelSelect = document.getElementById("ideas-model");
  const generateBtn = document.getElementById("btn-ideas-generate");
  const statusBox = document.getElementById("ideas-status");
  const listEl = document.getElementById("ideas-list");
  const bankEmptyEl = document.getElementById("ideas-bank-empty");
  const bankListEl = document.getElementById("ideas-bank-list");

  const MODEL_STORAGE_KEY = "ideas_model";

  let lastIdeas = [];
  let bank = [];

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str === null || str === undefined ? "" : str;
    return div.innerHTML;
  }

  function restoreModel() {
    const saved = localStorage.getItem(MODEL_STORAGE_KEY);
    if (saved && [...modelSelect.options].some((o) => o.value === saved)) {
      modelSelect.value = saved;
    }
  }

  modelSelect.addEventListener("change", () => {
    localStorage.setItem(MODEL_STORAGE_KEY, modelSelect.value);
  });

  function hideStatus() {
    statusBox.className = "status-box";
    statusBox.textContent = "";
  }

  function showStatus(type, message) {
    statusBox.className = `status-box show ${type}`;
    statusBox.textContent = message;
  }

  function scriptBlockHtml(label, text) {
    return `<div class="script-block"><div class="script-label">${escapeHtml(label)}</div><div class="script-text">${escapeHtml(text || "—")}</div></div>`;
  }

  // Карусель — по слайдах (слайд 1 = хук, середні слайди = idea.slides, останній = CTA);
  // Reels — розгорнутий каркас (хук, потім idea.script_steps по кроках, потім CTA); якщо
  // жодного з нових полів нема (старі ідеї, збережені в банк до цієї доробки) — старий
  // однорядковий рендер hook/script/cta, щоб історія банку не зламалась.
  function scenarioHtml(idea) {
    if (idea.slides && idea.slides.length) {
      const total = idea.slides.length + 2;
      const blocks = [scriptBlockHtml(I18N.t("ideas.card.slide_hook", { number: 1 }), idea.hook)];
      idea.slides.forEach((text, i) => {
        blocks.push(scriptBlockHtml(I18N.t("ideas.card.slide_content", { number: i + 2 }), text));
      });
      blocks.push(scriptBlockHtml(I18N.t("ideas.card.slide_cta", { number: total }), idea.cta));
      return blocks.join("");
    }

    if (idea.script_steps && idea.script_steps.length) {
      const blocks = [scriptBlockHtml(I18N.t("ideas.card.hook"), idea.hook)];
      idea.script_steps.forEach((text, i) => {
        blocks.push(scriptBlockHtml(I18N.t("ideas.card.script_step", { number: i + 1 }), text));
      });
      blocks.push(scriptBlockHtml(I18N.t("ideas.card.cta"), idea.cta));
      return blocks.join("");
    }

    return [
      scriptBlockHtml(I18N.t("ideas.card.hook"), idea.hook),
      scriptBlockHtml(I18N.t("ideas.card.script"), idea.script),
      scriptBlockHtml(I18N.t("ideas.card.cta"), idea.cta),
    ].join("");
  }

  function ideaCardHtml(idea, { saved, saveIndex, bankId } = {}) {
    const actionsHtml = bankId
      ? `<button class="icon-btn del-btn" data-id="${bankId}">${I18N.t("ideas.card.delete")}</button>`
      : `<button class="btn secondary idea-save-btn" data-index="${saveIndex}" ${saved ? "disabled" : ""}>${
          saved ? I18N.t("ideas.card.saved") : I18N.t("ideas.card.save")
        }</button>`;

    const metaParts = [idea.format, [idea.rubric, idea.audience_segment].filter(Boolean).join(" · ")].filter(Boolean);

    return `
    <div class="card idea-card">
      <div class="idea-card-header">
        ${metaParts.map((m) => `<span class="idea-meta-badge">${escapeHtml(m)}</span>`).join("")}
      </div>
      ${scenarioHtml(idea)}
      ${idea.why ? `<div class="idea-why">${escapeHtml(idea.why)}</div>` : ""}
      <div class="idea-card-actions">${actionsHtml}</div>
    </div>`;
  }

  function isSameIdea(a, b) {
    return a.hook === b.hook && a.cta === b.cta;
  }

  function renderIdeas() {
    if (!lastIdeas.length) {
      listEl.innerHTML = "";
      return;
    }
    listEl.innerHTML = lastIdeas
      .map((idea, index) => {
        const saved = bank.some((b) => isSameIdea(b, idea));
        return ideaCardHtml(idea, { saved, saveIndex: index });
      })
      .join("");

    listEl.querySelectorAll(".idea-save-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const idea = lastIdeas[Number(btn.dataset.index)];
        btn.disabled = true;
        try {
          const res = await fetch("/api/ideas/bank", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(idea),
          });
          if (!res.ok) {
            btn.disabled = false;
            return;
          }
          await loadBank();
          renderIdeas();
        } catch (e) {
          btn.disabled = false;
        }
      });
    });
  }

  function renderBank() {
    bankEmptyEl.style.display = bank.length ? "none" : "block";
    bankListEl.innerHTML = bank.map((idea) => ideaCardHtml(idea, { bankId: idea.id })).join("");

    bankListEl.querySelectorAll(".del-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await fetch(`/api/ideas/bank/${btn.dataset.id}`, { method: "DELETE" });
        await loadBank();
        renderIdeas();
      });
    });
  }

  async function loadBank() {
    try {
      const res = await fetch("/api/ideas/bank");
      const data = await res.json();
      bank = data.ideas || [];
    } catch (e) {
      bank = [];
    }
    renderBank();
  }

  async function generate() {
    hideStatus();
    generateBtn.disabled = true;
    generateBtn.textContent = I18N.t("ideas.btn.generating");
    listEl.innerHTML = "";
    try {
      const res = await fetch("/api/ideas/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: modelSelect.value }),
      });
      const data = await res.json();
      if (!res.ok) {
        showStatus("error", data.error || I18N.t("ideas.msg.error"));
        return;
      }
      lastIdeas = data.ideas || [];
      renderIdeas();
    } catch (e) {
      showStatus("error", I18N.t("common.network_error", { message: e.message }));
    } finally {
      generateBtn.disabled = false;
      generateBtn.textContent = I18N.t("ideas.btn.generate");
    }
  }

  generateBtn.addEventListener("click", generate);

  goSettingsBtn.addEventListener("click", () => {
    const settingsTabBtn = document.querySelector('.tab-btn[data-tab="settings"]');
    if (settingsTabBtn) settingsTabBtn.click();
  });

  async function checkKey() {
    try {
      const res = await fetch("/api/settings");
      const cfg = await res.json();
      const hasKey = !!cfg.anthropic_api_key;
      emptyState.style.display = hasKey ? "none" : "block";
      mainEl.style.display = hasKey ? "block" : "none";
      if (hasKey) await loadBank();
    } catch (e) {
      emptyState.style.display = "block";
      mainEl.style.display = "none";
    }
  }

  const ideasTabBtn = document.querySelector('.tab-btn[data-tab="ideas"]');
  if (ideasTabBtn) ideasTabBtn.addEventListener("click", checkKey);

  document.addEventListener("langchange", () => {
    renderIdeas();
    renderBank();
  });

  restoreModel();
  checkKey();
})();
