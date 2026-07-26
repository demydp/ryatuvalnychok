(function () {
  const content = document.getElementById("help-content");

  function directionLabel(direction) {
    if (direction === "higher_better") return I18N.t("metric.direction.higher_better");
    if (direction === "lower_better") return I18N.t("metric.direction.lower_better");
    return I18N.t("metric.direction.context");
  }

  function render(data) {
    content.innerHTML = (data.sections || [])
      .map((section) => {
        const cards = (section.metrics || [])
          .map(
            (m) => `
          <div class="help-metric-card">
            <div class="help-metric-head">
              <span class="title">${m.title}</span>
              <span class="info-popover-direction">${directionLabel(m.direction)}</span>
            </div>
            <div class="info-popover-section"><b>${I18N.t("metric.label.definition")}</b> ${m.definition}</div>
            <div class="info-popover-section"><b>${I18N.t("metric.label.how_to_read")}</b> ${m.how_to_read}</div>
            <div class="info-popover-section"><b>${I18N.t("metric.label.how_to_use")}</b> ${m.how_to_use}</div>
          </div>`
          )
          .join("");
        return `<h2 class="help-section-title">${section.title}</h2>${cards}`;
      })
      .join("");
  }

  async function loadHelp() {
    const res = await fetch("/api/help/metrics");
    const data = await res.json();
    render(data);
  }

  document.querySelector('.tab-btn[data-tab="help"]').addEventListener("click", loadHelp);
  document.addEventListener("langchange", loadHelp);
  loadHelp();
})();
