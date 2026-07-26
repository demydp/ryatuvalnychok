/* Иконка ⓘ рядом с метриками по всему дашборду: клик открывает короткое объяснение
   (что это / как понимать / как использовать) из общего глоссария /api/help/metrics.
   Работает через делегирование событий на document, поэтому не важно, когда именно
   и в какой вкладке появился конкретный .info-icon — не нужно вызывать инициализацию
   отдельно для каждой вкладки/таблицы. */
(function () {
  let helpMap = null;
  let helpPromise = null;
  let openPopover = null;
  let openIcon = null;

  document.addEventListener("langchange", () => {
    helpMap = null;
    helpPromise = null;
  });

  function loadHelp() {
    if (!helpPromise) {
      helpPromise = fetch("/api/help/metrics")
        .then((res) => res.json())
        .then((data) => {
          helpMap = {};
          (data.sections || []).forEach((section) => {
            (section.metrics || []).forEach((m) => {
              helpMap[m.id] = m;
            });
          });
          return helpMap;
        });
    }
    return helpPromise;
  }

  function directionLabel(direction) {
    if (direction === "higher_better") return I18N.t("metric.direction.higher_better");
    if (direction === "lower_better") return I18N.t("metric.direction.lower_better");
    return I18N.t("metric.direction.context");
  }

  function closePopover() {
    if (openPopover) {
      openPopover.remove();
      openPopover = null;
      openIcon = null;
    }
  }

  function showPopover(icon, metric) {
    const pop = document.createElement("div");
    pop.className = "info-popover";
    pop.innerHTML = `
      <div class="info-popover-title">
        <span>${metric.title}</span>
        <span class="info-popover-direction">${directionLabel(metric.direction)}</span>
      </div>
      <div class="info-popover-section"><b>${I18N.t("metric.label.definition")}</b> ${metric.definition}</div>
      <div class="info-popover-section"><b>${I18N.t("metric.label.how_to_read")}</b> ${metric.how_to_read}</div>
      <div class="info-popover-section"><b>${I18N.t("metric.label.how_to_use")}</b> ${metric.how_to_use}</div>
    `;
    document.body.appendChild(pop);

    const rect = icon.getBoundingClientRect();
    const popRect = pop.getBoundingClientRect();
    let left = rect.left + window.scrollX;
    const top = rect.bottom + window.scrollY + 6;
    const maxLeft = window.scrollX + window.innerWidth - popRect.width - 12;
    if (left > maxLeft) left = Math.max(window.scrollX + 12, maxLeft);

    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;

    openPopover = pop;
    openIcon = icon;
  }

  // Слушаем клик на фазе ПОГРУЖЕНИЯ (capture), а не всплытия — иначе клик по иконке внутри
  // сортируемого заголовка таблицы (th с собственным onclick для сортировки) успевает
  // сначала сработать как сортировка, и только потом всплыть до этого делегированного
  // обработчика. На capture-фазе мы перехватываем клик раньше, чем он дойдёт до th/тела.
  document.addEventListener(
    "click",
    async (e) => {
      const icon = e.target.closest(".info-icon");
      if (!icon) {
        if (openPopover && !e.target.closest(".info-popover")) closePopover();
        return;
      }
      e.stopPropagation();
      e.preventDefault();
      if (icon === openIcon) {
        closePopover();
        return;
      }
      const help = await loadHelp();
      const metric = help[icon.dataset.metric];
      if (!metric) return;
      closePopover();
      showPopover(icon, metric);
    },
    true
  );

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePopover();
  });

  window.addEventListener("scroll", () => closePopover(), true);
  window.addEventListener("resize", () => closePopover());
})();
