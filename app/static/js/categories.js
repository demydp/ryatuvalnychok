(function () {
  const autoDetectBtn = document.getElementById("btn-auto-detect");
  const autoDetectStatus = document.getElementById("auto-detect-status");

  const btnCategoriesAiSummary = document.getElementById("btn-categories-ai-summary");
  const categoriesAiSummaryStatus = document.getElementById("categories-ai-summary-status");
  const categoriesAiSummaryText = document.getElementById("categories-ai-summary-text");

  const categoriesMeta = document.getElementById("categories-meta");
  const categoriesEmpty = document.getElementById("categories-empty");
  const categoriesListEl = document.getElementById("categories-list");

  const newCategoryInput = document.getElementById("new-category-name");
  const addCategoryBtn = document.getElementById("btn-add-category");

  const mergeControls = document.getElementById("merge-controls");
  const mergeNameInput = document.getElementById("merge-name");
  const mergeBtn = document.getElementById("btn-merge");

  const reelsCard = document.getElementById("reels-card");
  const reelsEmpty = document.getElementById("categories-reels-empty");
  const reelsMeta = document.getElementById("reels-meta");
  const reelsTbody = document.getElementById("category-reels-tbody");

  let categories = [];
  let reels = [];
  let selectedForMerge = new Set();

  function fmtDate(iso) {
    if (!iso) return '<span class="na">—</span>';
    return new Date(iso).toLocaleDateString(I18N.locale(), { day: "2-digit", month: "2-digit", year: "numeric" });
  }

  async function loadCategories() {
    const res = await fetch("/api/categories");
    const data = await res.json();
    categories = data.categories || [];
    reels = data.reels || [];
    selectedForMerge = new Set([...selectedForMerge].filter((id) => categories.some((c) => c.id === id)));
    render();
  }

  function render() {
    categoriesMeta.textContent = I18N.t("categories.list.meta", { count: categories.length });

    if (categories.length === 0) {
      categoriesEmpty.style.display = "block";
      categoriesListEl.innerHTML = "";
    } else {
      categoriesEmpty.style.display = "none";
      categoriesListEl.innerHTML = categories.map(categoryCardHtml).join("");
      wireCategoryCardEvents();
    }

    renderMergeControls();
    renderReelsTable();
  }

  function statHtml(label, value, suffix) {
    const display = value === null || value === undefined ? `<span class="na">${I18N.t("common.na")}</span>` : `${value}${suffix || ""}`;
    return `<div class="stat"><div class="label">${label}</div><div class="value">${display}</div></div>`;
  }

  function categoryCardHtml(cat) {
    const sourceBadge =
      cat.source === "auto"
        ? `<span class="badge auto-source">${I18N.t("categories.badge.auto")}</span>`
        : `<span class="badge manual-source">${I18N.t("categories.badge.manual")}</span>`;
    return `
      <div class="top-card category-card" data-id="${cat.id}">
        <div class="category-head">
          <input type="checkbox" class="merge-checkbox" data-id="${cat.id}" ${selectedForMerge.has(cat.id) ? "checked" : ""}>
          <span class="category-name" title="${cat.name}">${cat.name}</span>
          ${sourceBadge}
        </div>
        <div class="category-stats">
          ${statHtml(I18N.t("categories.stat.reels"), cat.reel_count)}
          ${statHtml(I18N.t("categories.stat.er"), cat.avg_er, "%")}
          ${statHtml(I18N.t("categories.stat.saves"), cat.avg_saves_rate, "%")}
          ${statHtml(I18N.t("categories.stat.watch"), cat.avg_hook_indicator, "%")}
        </div>
        <div class="category-actions">
          <button class="icon-btn rename-btn" data-id="${cat.id}">${I18N.t("categories.rename_btn")}</button>
          <button class="icon-btn del-btn" data-id="${cat.id}">${I18N.t("categories.delete_btn")}</button>
        </div>
      </div>`;
  }

  function wireCategoryCardEvents() {
    categoriesListEl.querySelectorAll(".merge-checkbox").forEach((cb) => {
      cb.addEventListener("change", () => {
        if (cb.checked) selectedForMerge.add(cb.dataset.id);
        else selectedForMerge.delete(cb.dataset.id);
        renderMergeControls();
      });
    });

    categoriesListEl.querySelectorAll(".rename-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const cat = categories.find((c) => c.id === btn.dataset.id);
        const name = prompt(I18N.t("categories.rename_prompt"), cat ? cat.name : "");
        if (!name || !name.trim()) return;
        const res = await fetch(`/api/categories/${btn.dataset.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: name.trim() }),
        });
        const data = await res.json();
        if (!res.ok) {
          alert(data.error || I18N.t("categories.msg.rename_error"));
          return;
        }
        await loadCategories();
      });
    });

    categoriesListEl.querySelectorAll(".del-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm(I18N.t("categories.confirm_delete"))) return;
        const res = await fetch(`/api/categories/${btn.dataset.id}`, { method: "DELETE" });
        const data = await res.json();
        if (!res.ok) {
          alert(data.error || I18N.t("categories.msg.delete_error"));
          return;
        }
        selectedForMerge.delete(btn.dataset.id);
        await loadCategories();
      });
    });
  }

  function renderMergeControls() {
    if (selectedForMerge.size >= 2) {
      mergeControls.style.display = "flex";
      if (!mergeNameInput.value) {
        const first = categories.find((c) => c.id === [...selectedForMerge][0]);
        mergeNameInput.value = first ? first.name : "";
      }
    } else {
      mergeControls.style.display = "none";
    }
  }

  addCategoryBtn.addEventListener("click", async () => {
    const name = newCategoryInput.value.trim();
    if (!name) return;
    const res = await fetch("/api/categories", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.error || I18N.t("categories.msg.add_error"));
      return;
    }
    newCategoryInput.value = "";
    await loadCategories();
  });

  mergeBtn.addEventListener("click", async () => {
    const name = mergeNameInput.value.trim();
    const sourceIds = [...selectedForMerge];
    if (sourceIds.length < 2 || !name) return;
    const res = await fetch("/api/categories/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_ids: sourceIds, name }),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.error || I18N.t("categories.msg.merge_error"));
      return;
    }
    selectedForMerge.clear();
    mergeNameInput.value = "";
    await loadCategories();
  });

  autoDetectBtn.addEventListener("click", async () => {
    if (!confirm(I18N.t("categories.confirm_auto_detect"))) {
      return;
    }
    autoDetectBtn.disabled = true;
    autoDetectBtn.textContent = I18N.t("categories.msg.analyzing");
    autoDetectStatus.className = "status-box show";
    autoDetectStatus.textContent = I18N.t("categories.msg.auto_detect_in_progress");
    try {
      const res = await fetch("/api/categories/auto-detect", { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        autoDetectStatus.className = "status-box show error";
        autoDetectStatus.textContent = data.error || I18N.t("common.error");
        return;
      }
      autoDetectStatus.className = "status-box show ok";
      autoDetectStatus.textContent = I18N.t("categories.msg.auto_detect_done", {
        count: data.categories.length,
        analyzed: data.analyzed_count,
        truncated: data.truncated ? I18N.t("categories.msg.truncated_note") : "",
        cost: data.estimated_cost_usd,
      });
      await loadCategories();
    } catch (e) {
      autoDetectStatus.className = "status-box show error";
      autoDetectStatus.textContent = I18N.t("common.network_error", { message: e.message });
    } finally {
      autoDetectBtn.disabled = false;
      autoDetectBtn.textContent = I18N.t("categories.auto_detect.btn");
    }
  });

  if (btnCategoriesAiSummary) {
    btnCategoriesAiSummary.addEventListener("click", async () => {
      btnCategoriesAiSummary.disabled = true;
      btnCategoriesAiSummary.textContent = I18N.t("categories.ai_summary.generating");
      categoriesAiSummaryStatus.className = "status-box show";
      categoriesAiSummaryStatus.textContent = I18N.t("categories.ai_summary.generating");
      categoriesAiSummaryText.style.display = "none";
      try {
        const res = await fetch("/api/categories/ai-summary", { method: "POST" });
        const data = await res.json();
        if (!res.ok) {
          categoriesAiSummaryStatus.className = "status-box show error";
          categoriesAiSummaryStatus.textContent = data.error || I18N.t("common.error");
          return;
        }
        categoriesAiSummaryStatus.className = "status-box";
        categoriesAiSummaryStatus.textContent = "";
        categoriesAiSummaryText.style.display = "block";
        categoriesAiSummaryText.textContent = data.summary;
      } catch (e) {
        categoriesAiSummaryStatus.className = "status-box show error";
        categoriesAiSummaryStatus.textContent = I18N.t("common.network_error", { message: e.message });
      } finally {
        btnCategoriesAiSummary.disabled = false;
        btnCategoriesAiSummary.textContent = I18N.t("categories.ai_summary.btn");
      }
    });
  }

  function renderReelsTable() {
    if (reels.length === 0) {
      reelsCard.style.display = "none";
      reelsEmpty.style.display = "block";
      return;
    }
    reelsEmpty.style.display = "none";
    reelsCard.style.display = "block";

    const unassignedCount = reels.filter((r) => !r.category_id).length;
    reelsMeta.textContent = I18N.t("categories.reels.meta", { count: reels.length, unassigned: unassignedCount });

    const sorted = [...reels].sort((a, b) => {
      const catA = categories.find((c) => c.id === a.category_id);
      const catB = categories.find((c) => c.id === b.category_id);
      const nameA = catA ? catA.name : "";
      const nameB = catB ? catB.name : "";
      if (!nameA && nameB) return -1;
      if (nameA && !nameB) return 1;
      if (nameA !== nameB) return nameA.localeCompare(nameB);
      return new Date(b.timestamp) - new Date(a.timestamp);
    });

    const options = categories.map((c) => `<option value="${c.id}">${c.name}</option>`).join("");

    reelsTbody.innerHTML = sorted
      .map((r) => {
        const thumb = r.thumbnail_url
          ? `<img src="${r.thumbnail_url}" style="width:28px;height:28px;object-fit:cover;border-radius:5px;">`
          : "";
        const caption = (r.caption || I18N.t("common.no_caption")).slice(0, 70);
        const er = r.engagement_rate === null || r.engagement_rate === undefined ? `<span class="na">${I18N.t("common.na")}</span>` : `${r.engagement_rate}%`;
        return `
        <tr>
          <td>${thumb}</td>
          <td class="caption-cell" title="${(r.caption || "").replace(/"/g, "&quot;")}">${r.is_ad ? `[${I18N.t("hooks.badge.ad")}] ` : ""}${caption}</td>
          <td>${fmtDate(r.timestamp)}</td>
          <td>${er}</td>
          <td>
            <select class="category-select" data-id="${r.id}">
              <option value="">${I18N.t("categories.reels.no_category_option")}</option>
              ${options}
            </select>
          </td>
        </tr>`;
      })
      .join("");

    reelsTbody.querySelectorAll(".category-select").forEach((select) => {
      const r = reels.find((x) => x.id === select.dataset.id);
      select.value = r && r.category_id ? r.category_id : "";
      select.addEventListener("change", async () => {
        const res = await fetch("/api/categories/assign", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ media_id: select.dataset.id, category_id: select.value || null }),
        });
        const data = await res.json();
        if (!res.ok) {
          alert(data.error || I18N.t("categories.msg.assign_error"));
          return;
        }
        await loadCategories();
      });
    });
  }

  document.querySelector('.tab-btn[data-tab="categories"]').addEventListener("click", loadCategories);
  document.addEventListener("langchange", () => {
    if (categories.length || reels.length) render();
  });

  loadCategories();
})();
