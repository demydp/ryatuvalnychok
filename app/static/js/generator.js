(function () {
  const refreshProfileBtn = document.getElementById("btn-refresh-profile");
  const profileEmpty = document.getElementById("profile-empty");
  const profileContent = document.getElementById("profile-content");
  const profileText = document.getElementById("profile-text");
  const profileMeta = document.getElementById("profile-meta");
  const profileStatus = document.getElementById("profile-status");

  const modelCardsEl = document.getElementById("model-cards");
  const formatCardsEl = document.getElementById("format-cards");
  const topicInput = document.getElementById("gen-topic");
  const categorySelect = document.getElementById("gen-category");
  const hookTypeSelect = document.getElementById("gen-hook-type");
  const cleanAdsCheckbox = document.getElementById("gen-clean-ads");
  const generateBtn = document.getElementById("btn-generate");
  const genStatus = document.getElementById("gen-status");

  const resultCard = document.getElementById("result-card");
  const resultMeta = document.getElementById("result-meta");
  const resultBlocks = document.getElementById("result-blocks");
  const resultWhyBlock = document.getElementById("result-why-block");
  const resultWhy = document.getElementById("result-why");
  const resultNotes = document.getElementById("result-notes");

  let models = {};
  let selectedModel = "opus";
  let selectedFormat = "reels";
  let lastProfile = null;
  let lastResult = null;

  function fmtDate(iso) {
    if (!iso) return "";
    return new Date(iso).toLocaleString(I18N.locale());
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str === null || str === undefined ? "" : str;
    return div.innerHTML;
  }

  function formatLabel(format) {
    return format === "carousel" ? I18N.t("generator.format.carousel") : I18N.t("generator.format.reels");
  }

  formatCardsEl.querySelectorAll(".format-card").forEach((card) => {
    card.addEventListener("click", () => {
      selectedFormat = card.dataset.format;
      formatCardsEl.querySelectorAll(".format-card").forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
    });
  });

  function scriptBlockHtml(label, text) {
    return `<div class="script-block"><div class="script-label">${escapeHtml(label)}</div><div class="script-text">${escapeHtml(text || "—")}</div></div>`;
  }

  // Карусель — по слайдах (слайд 1 = хук, середні = script.slides, останній = CTA), як у
  // вкладці Ідеї; Рілс — звичний хук/тіло/CTA.
  function scriptBlocksHtml(script, format) {
    if (format === "carousel") {
      const slides = script.slides || [];
      const total = slides.length + 2;
      const blocks = [scriptBlockHtml(I18N.t("ideas.card.slide_hook", { number: 1 }), script.hook)];
      slides.forEach((text, i) => {
        blocks.push(scriptBlockHtml(I18N.t("ideas.card.slide_content", { number: i + 2 }), text));
      });
      blocks.push(scriptBlockHtml(I18N.t("ideas.card.slide_cta", { number: total }), script.cta));
      return blocks.join("");
    }
    return [
      scriptBlockHtml(I18N.t("generator.result.hook_label"), script.hook),
      scriptBlockHtml(I18N.t("generator.result.body_label"), script.body),
      scriptBlockHtml(I18N.t("generator.result.cta_label"), script.cta),
    ].join("");
  }

  async function loadCategoriesIntoSelect() {
    const res = await fetch("/api/categories");
    const data = await res.json();
    const categories = data.categories || [];
    const current = categorySelect.value;
    categorySelect.innerHTML =
      `<option value="">${I18N.t("generator.new.category_none")}</option>` +
      categories.map((c) => `<option value="${c.id}">${c.name} (ER ${c.avg_er ?? I18N.t("common.na")}%)</option>`).join("");
    if (categories.some((c) => c.id === current)) categorySelect.value = current;
  }

  async function loadModels() {
    const res = await fetch("/api/generator/models");
    const data = await res.json();
    models = data.models || {};
    selectedModel = data.default || "opus";
    renderModelCards();
  }

  function renderModelCards() {
    modelCardsEl.innerHTML = Object.entries(models)
      .map(
        ([key, info]) => `
      <div class="model-card ${key === selectedModel ? "selected" : ""}" data-key="${key}">
        <div class="model-name">
          <span>${info.label}</span>
          <span class="model-price">${I18N.t("generator.model.price", { input: info.input_price_per_mtok, output: info.output_price_per_mtok })}</span>
        </div>
        <div class="model-desc">${info.description}</div>
      </div>`
      )
      .join("");

    modelCardsEl.querySelectorAll(".model-card").forEach((card) => {
      card.addEventListener("click", () => {
        selectedModel = card.dataset.key;
        modelCardsEl.querySelectorAll(".model-card").forEach((c) => c.classList.remove("selected"));
        card.classList.add("selected");
      });
    });
  }

  async function loadProfile() {
    const res = await fetch("/api/generator/profile");
    const data = await res.json();
    renderProfile(data.profile);
  }

  function renderProfile(profile) {
    lastProfile = profile;
    if (!profile) {
      profileEmpty.style.display = "block";
      profileContent.style.display = "none";
      return;
    }
    profileEmpty.style.display = "none";
    profileContent.style.display = "block";
    profileText.textContent = profile.profile_text;
    profileMeta.textContent = I18N.t("generator.profile.computed_meta", {
      count: profile.transcripts_used,
      date: fmtDate(profile.computed_at),
      model: profile.model,
    });
    if (profile.low_sample_warning) {
      profileMeta.textContent += I18N.t("generator.profile.low_sample_suffix");
    }
  }

  refreshProfileBtn.addEventListener("click", async () => {
    refreshProfileBtn.disabled = true;
    refreshProfileBtn.textContent = I18N.t("generator.msg.computing");
    profileStatus.className = "status-box show";
    profileStatus.textContent = I18N.t("generator.msg.analyzing_transcripts");
    try {
      const res = await fetch("/api/generator/profile/refresh", { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        profileStatus.className = "status-box show error";
        profileStatus.textContent = data.error || I18N.t("common.error");
        return;
      }
      profileStatus.className = "status-box show ok";
      profileStatus.textContent = I18N.t("generator.msg.profile_updated");
      renderProfile(data.profile);
    } catch (e) {
      profileStatus.className = "status-box show error";
      profileStatus.textContent = I18N.t("common.network_error", { message: e.message });
    } finally {
      refreshProfileBtn.disabled = false;
      refreshProfileBtn.textContent = I18N.t("generator.profile.refresh_btn");
    }
  });

  generateBtn.addEventListener("click", async () => {
    const topic = topicInput.value.trim();
    if (!topic) {
      genStatus.textContent = I18N.t("generator.msg.enter_topic");
      return;
    }
    generateBtn.disabled = true;
    generateBtn.textContent = I18N.t("generator.msg.generating");
    genStatus.textContent = "";
    try {
      const res = await fetch("/api/generator/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic,
          format: selectedFormat,
          hook_type: hookTypeSelect.value,
          model: selectedModel,
          clean_for_ads: cleanAdsCheckbox.checked,
          category_id: categorySelect.value || null,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        genStatus.textContent = data.error || I18N.t("generator.msg.generation_error_generic");
        return;
      }
      renderResult(data);
      await loadSavedScripts();
    } catch (e) {
      genStatus.textContent = I18N.t("common.network_error", { message: e.message });
    } finally {
      generateBtn.disabled = false;
      generateBtn.textContent = I18N.t("generator.new.generate_btn");
    }
  });

  function renderResult(data) {
    lastResult = data;
    resultCard.style.display = "block";
    const modelInfo = models[data.model_key] || {};
    const categoryPart = data.category_name ? I18N.t("generator.category_suffix", { name: data.category_name }) : "";
    resultMeta.textContent = I18N.t("generator.result.meta", {
      format: formatLabel(data.format),
      model: modelInfo.label || data.model_id,
      cost: data.estimated_cost_usd,
      version: data.clean_for_ads ? I18N.t("generator.result.clean_version") : I18N.t("generator.result.normal_version"),
      category: categoryPart,
    });

    const hasContent = data.script.hook || data.script.body || data.script.cta || (data.script.slides || []).length;
    if (hasContent) {
      resultBlocks.innerHTML = scriptBlocksHtml(data.script, data.format);
    } else {
      resultBlocks.innerHTML = scriptBlockHtml(I18N.t("generator.result.body_label"), data.raw_text);
    }

    if (data.script.why) {
      resultWhyBlock.style.display = "block";
      resultWhy.textContent = data.script.why;
    } else {
      resultWhyBlock.style.display = "none";
      resultWhy.textContent = "";
    }

    resultNotes.innerHTML = data.notes.map((n) => `<li>${n}</li>`).join("");
    resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // ---------- Сохранённые скрипты ----------

  const savedEmpty = document.getElementById("saved-empty");
  const savedListEl = document.getElementById("saved-list");
  const savedMeta = document.getElementById("saved-meta");
  const savedSearch = document.getElementById("saved-search");
  const savedSort = document.getElementById("saved-sort");
  const savedFavoritesOnly = document.getElementById("saved-favorites-only");

  const addManualBtn = document.getElementById("btn-add-manual");
  const manualFormCard = document.getElementById("manual-form-card");
  const manualModelSelect = document.getElementById("manual-model");
  const manualTopic = document.getElementById("manual-topic");
  const manualHookType = document.getElementById("manual-hook-type");
  const manualHook = document.getElementById("manual-hook");
  const manualBody = document.getElementById("manual-body");
  const manualCta = document.getElementById("manual-cta");
  const manualNotes = document.getElementById("manual-notes");
  const manualDate = document.getElementById("manual-date");
  const saveManualBtn = document.getElementById("btn-save-manual");
  const cancelManualBtn = document.getElementById("btn-cancel-manual");
  const manualStatus = document.getElementById("manual-status");

  function toDatetimeLocalValue(date) {
    const pad = (n) => String(n).padStart(2, "0");
    return (
      `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
      `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
    );
  }

  function resetManualForm() {
    manualTopic.value = "";
    manualHookType.value = "";
    manualHook.value = "";
    manualBody.value = "";
    manualCta.value = "";
    manualNotes.value = "";
    manualDate.value = toDatetimeLocalValue(new Date());
    manualStatus.textContent = "";
    if (models[selectedModel]) manualModelSelect.value = selectedModel;
  }

  addManualBtn.addEventListener("click", () => {
    const opening = manualFormCard.style.display === "none";
    manualFormCard.style.display = opening ? "block" : "none";
    if (opening) {
      manualModelSelect.innerHTML = Object.entries(models)
        .map(([key, info]) => `<option value="${key}">${info.label}</option>`)
        .join("");
      resetManualForm();
      manualFormCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  });

  cancelManualBtn.addEventListener("click", () => {
    manualFormCard.style.display = "none";
  });

  saveManualBtn.addEventListener("click", async () => {
    const topic = manualTopic.value.trim();
    if (!topic) {
      manualStatus.textContent = I18N.t("generator.msg.enter_manual_title");
      return;
    }
    saveManualBtn.disabled = true;
    manualStatus.textContent = I18N.t("generator.msg.saving");
    try {
      const res = await fetch("/api/generator/scripts/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic,
          hook_type_pref: manualHookType.value || null,
          model_key: manualModelSelect.value || null,
          hook: manualHook.value.trim(),
          body: manualBody.value.trim(),
          cta: manualCta.value.trim(),
          notes: manualNotes.value.trim(),
          created_at: manualDate.value || null,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        manualStatus.textContent = data.error || I18N.t("generator.msg.save_error");
        return;
      }
      manualFormCard.style.display = "none";
      await loadSavedScripts();
    } catch (e) {
      manualStatus.textContent = I18N.t("common.network_error", { message: e.message });
    } finally {
      saveManualBtn.disabled = false;
    }
  });

  let savedScripts = [];
  let reelsCache = null;
  let openPickerId = null;

  async function loadSavedScripts() {
    const res = await fetch("/api/generator/scripts");
    const data = await res.json();
    savedScripts = data.scripts || [];
    renderSavedList();
  }

  async function loadReelsForLinking() {
    if (reelsCache) return reelsCache;
    const res = await fetch("/api/generator/reels");
    const data = await res.json();
    reelsCache = data.reels || [];
    return reelsCache;
  }

  function verdictBadge(script) {
    if (!script.linked_media_id) {
      return `<button class="icon-btn btn-link" data-id="${script.id}">${I18N.t("generator.link_btn")}</button>`;
    }
    if (!script.verdict) {
      return `<span class="verdict-badge verdict-neutral">${I18N.t("verdict.neutral")}</span>`;
    }
    const cls = script.verdict === "good" ? "verdict-good" : script.verdict === "bad" ? "verdict-bad" : "verdict-neutral";
    const label = script.verdict === "good" ? I18N.t("verdict.good") : script.verdict === "bad" ? I18N.t("verdict.bad") : I18N.t("verdict.neutral");
    return `<span class="verdict-badge ${cls}">${label}</span>`;
  }

  function getFilteredSorted() {
    let list = [...savedScripts];
    const q = savedSearch.value.trim().toLowerCase();
    if (q) list = list.filter((s) => (s.topic || "").toLowerCase().includes(q));
    if (savedFavoritesOnly.checked) list = list.filter((s) => s.is_favorite);

    const sortBy = savedSort.value;
    if (sortBy === "date_asc") list.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    else if (sortBy === "topic") list.sort((a, b) => (a.topic || "").localeCompare(b.topic || ""));
    else list.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

    return list;
  }

  function renderSavedList() {
    const list = getFilteredSorted();
    savedMeta.textContent = I18N.t("generator.saved.count_total", { count: savedScripts.length });

    if (savedScripts.length === 0) {
      savedEmpty.style.display = "block";
      savedListEl.innerHTML = "";
      return;
    }
    savedEmpty.style.display = "none";

    savedListEl.innerHTML = list
      .map((s) => {
        const modelLabel = (models[s.model_key] || {}).label || s.model_key;
        const script = s.script || {};
        const pickerHtml = openPickerId === s.id ? linkPickerHtml(s) : "";
        const linkedStrip = s.linked_media_id && s.verdict_reason ? `<div class="verdict-reason">${s.verdict_reason} <a href="#" class="unlink-link" data-id="${s.id}">${I18N.t("generator.unlink_link")}</a></div>` : "";

        return `
        <div class="saved-script-card" data-id="${s.id}">
          <div class="saved-script-header">
            <div>
              <div class="saved-script-topic">${s.topic}</div>
              <div class="saved-script-meta">${formatLabel(s.format)} • ${fmtDate(s.created_at)} • ${I18N.t("generator.saved.hook_meta", { type: s.hook_type_pref ? hookTypeLabel(s.hook_type_pref) : I18N.t("generator.saved.hook_any") })} • ${I18N.t("generator.saved.model_meta", { model: modelLabel })}${s.clean_for_ads ? I18N.t("generator.saved.for_ads_suffix") : ""}${s.category_name ? I18N.t("generator.category_suffix", { name: s.category_name }) : ""}${s.manual ? I18N.t("generator.saved.manual_suffix") : ""}</div>
            </div>
            <div class="saved-script-actions">
              ${verdictBadge(s)}
              <button class="icon-btn fav-btn ${s.is_favorite ? "active" : ""}" data-id="${s.id}">${s.is_favorite ? I18N.t("generator.saved.fav_active") : "☆"}</button>
              <button class="icon-btn del-btn" data-id="${s.id}">${I18N.t("generator.delete_btn")}</button>
            </div>
          </div>
          <div class="saved-script-preview" data-id="${s.id}">
            <div class="script-label">${I18N.t("generator.label.hook")}</div><div class="script-text">${script.hook || s.raw_text || ""}</div>
          </div>
          ${linkedStrip}
          ${pickerHtml}
        </div>`;
      })
      .join("");

    wireSavedListEvents();
  }

  function linkPickerHtml(script) {
    return `
      <div class="link-picker" data-id="${script.id}">
        <label style="font-weight:600; font-size:12px;">${I18N.t("generator.link_picker.select_label")}</label>
        <select class="link-select"><option value="">${I18N.t("generator.link_picker.select_default")}</option></select>
        <label style="font-weight:600; font-size:12px;">${I18N.t("generator.link_picker.reference_label")}</label>
        <input type="text" class="link-reference" data-i18n-placeholder="generator.link_picker.reference_placeholder" placeholder="${I18N.t("generator.link_picker.reference_placeholder")}">
        <div style="display:flex; gap:8px;">
          <button class="btn secondary link-confirm" data-id="${script.id}" style="padding:7px 14px; font-size:13px;">${I18N.t("generator.link_picker.confirm_btn")}</button>
          <button class="btn secondary link-cancel" style="padding:7px 14px; font-size:13px;">${I18N.t("generator.link_picker.cancel_btn")}</button>
        </div>
        <div class="link-status" style="font-size:12px;"></div>
      </div>`;
  }

  async function fillLinkSelect(card) {
    const select = card.querySelector(".link-select");
    const reels = await loadReelsForLinking();
    select.innerHTML =
      `<option value="">${I18N.t("generator.link_picker.select_default")}</option>` +
      reels
        .map(
          (r) =>
            `<option value="${r.id}">${fmtDate(r.timestamp)} • ${r.is_ad ? `[${I18N.t("hooks.badge.ad")}] ` : ""}${(r.caption || I18N.t("common.no_caption")).slice(0, 40)} • ER ${r.engagement_rate ?? "?"}%</option>`
        )
        .join("");
  }

  function wireSavedListEvents() {
    savedListEl.querySelectorAll(".fav-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const s = savedScripts.find((x) => x.id === btn.dataset.id);
        await fetch(`/api/generator/scripts/${btn.dataset.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_favorite: !s.is_favorite }),
        });
        await loadSavedScripts();
      });
    });

    savedListEl.querySelectorAll(".del-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm(I18N.t("generator.confirm_delete"))) return;
        await fetch(`/api/generator/scripts/${btn.dataset.id}`, { method: "DELETE" });
        await loadSavedScripts();
      });
    });

    savedListEl.querySelectorAll(".btn-link").forEach((btn) => {
      btn.addEventListener("click", async () => {
        openPickerId = btn.dataset.id;
        renderSavedList();
        const card = savedListEl.querySelector(`.link-picker[data-id="${openPickerId}"]`);
        if (card) await fillLinkSelect(card);
      });
    });

    savedListEl.querySelectorAll(".link-cancel").forEach((btn) => {
      btn.addEventListener("click", () => {
        openPickerId = null;
        renderSavedList();
      });
    });

    savedListEl.querySelectorAll(".link-confirm").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const picker = btn.closest(".link-picker");
        const mediaId = picker.querySelector(".link-select").value;
        const reference = picker.querySelector(".link-reference").value.trim();
        const statusEl = picker.querySelector(".link-status");
        if (!mediaId && !reference) {
          statusEl.textContent = I18N.t("generator.link_picker.status_missing");
          return;
        }
        btn.disabled = true;
        statusEl.textContent = I18N.t("generator.link_picker.status_computing");
        try {
          const res = await fetch(`/api/generator/scripts/${btn.dataset.id}/link`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(mediaId ? { media_id: mediaId } : { reference }),
          });
          const data = await res.json();
          if (!res.ok) {
            statusEl.textContent = data.error || I18N.t("generator.link_picker.status_error");
            btn.disabled = false;
            return;
          }
          openPickerId = null;
          await loadSavedScripts();
        } catch (e) {
          statusEl.textContent = I18N.t("common.network_error", { message: e.message });
          btn.disabled = false;
        }
      });
    });

    savedListEl.querySelectorAll(".unlink-link").forEach((link) => {
      link.addEventListener("click", async (e) => {
        e.preventDefault();
        if (!confirm(I18N.t("generator.confirm_unlink"))) return;
        await fetch(`/api/generator/scripts/${link.dataset.id}/unlink`, { method: "POST" });
        await loadSavedScripts();
      });
    });

    savedListEl.querySelectorAll(".saved-script-preview").forEach((el) => {
      el.addEventListener("click", () => {
        const s = savedScripts.find((x) => x.id === el.dataset.id);
        if (!s) return;
        const script = s.script || {};
        if (el.dataset.expanded === "true") {
          el.innerHTML = `<div class="script-label">${I18N.t("generator.label.hook")}</div><div class="script-text">${script.hook || s.raw_text || ""}</div>`;
          el.dataset.expanded = "false";
        } else {
          const body =
            s.format === "carousel"
              ? scriptBlocksHtml(script, "carousel")
              : `<div class="script-label">${I18N.t("generator.label.hook")}</div><div class="script-text">${script.hook || "—"}</div>
                 <div class="script-label">${I18N.t("generator.label.body")}</div><div class="script-text">${script.body || s.raw_text || "—"}</div>
                 <div class="script-label">${I18N.t("generator.label.cta")}</div><div class="script-text">${script.cta || "—"}</div>`;
          el.innerHTML = `
            ${body}
            ${script.why ? `<div class="script-label">${I18N.t("generator.result.why_label")}</div><div class="script-text">${script.why}</div>` : ""}
            ${(s.notes || []).length ? `<ul class="rec-list" style="margin-top:10px;">${s.notes.map((n) => `<li>${n}</li>`).join("")}</ul>` : ""}
          `;
          el.dataset.expanded = "true";
        }
      });
    });
  }

  savedSearch.addEventListener("input", renderSavedList);
  savedSort.addEventListener("change", renderSavedList);
  savedFavoritesOnly.addEventListener("change", renderSavedList);

  document.querySelector('.tab-btn[data-tab="generator"]').addEventListener("click", () => {
    loadModels();
    loadProfile();
    loadSavedScripts();
    loadCategoriesIntoSelect();
  });

  document.addEventListener("langchange", async () => {
    await loadModels();
    renderProfile(lastProfile);
    if (lastResult) renderResult(lastResult);
    renderSavedList();
    await loadCategoriesIntoSelect();
  });

  loadModels();
  loadProfile();
  loadSavedScripts();
  loadCategoriesIntoSelect();
})();
