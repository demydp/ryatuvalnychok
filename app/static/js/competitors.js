(function () {
  const queryInput = document.getElementById("competitors-query");
  const countriesInput = document.getElementById("competitors-countries");
  const openBtn = document.getElementById("btn-competitors-open");
  const meta = document.getElementById("competitors-meta");
  const linksBox = document.getElementById("competitors-links");
  const linksList = document.getElementById("competitors-links-list");
  const countryPicker = document.getElementById("competitors-country-picker");
  const countryChips = document.getElementById("competitors-country-chips");
  const referenceList = document.getElementById("competitors-country-reference-list");

  const COUNTRIES = window.COUNTRIES || [];

  function countryName(country) {
    const lang = I18N.getLang();
    return country[lang] || country.ru;
  }

  function sortedCountries() {
    return [...COUNTRIES].sort((a, b) => countryName(a).localeCompare(countryName(b), I18N.locale()));
  }

  function currentCodes() {
    return countriesInput.value
      .split(",")
      .map((c) => c.trim().toUpperCase())
      .filter(Boolean);
  }

  function setCodes(codes) {
    // dedup, зберігаючи порядок додавання
    countriesInput.value = [...new Set(codes)].join(",");
    renderChips();
  }

  function renderChips() {
    const codes = currentCodes();
    countryChips.innerHTML = codes
      .map((code) => {
        const known = COUNTRIES.find((c) => c.code === code);
        const label = known ? `${countryName(known)} (${code})` : code;
        return `<span class="country-chip" data-code="${code}">${label} <button type="button" class="country-chip-remove" data-code="${code}" aria-label="${I18N.t("competitors.form.remove_country")}">×</button></span>`;
      })
      .join("");
    countryChips.querySelectorAll(".country-chip-remove").forEach((btn) => {
      btn.addEventListener("click", () => {
        setCodes(currentCodes().filter((c) => c !== btn.dataset.code));
      });
    });
  }

  function renderCountryPicker() {
    const options = sortedCountries()
      .map((c) => `<option value="${c.code}">${countryName(c)} (${c.code})</option>`)
      .join("");
    countryPicker.innerHTML = `<option value="">${I18N.t("competitors.form.country_picker_placeholder")}</option>${options}`;
  }

  function renderReferenceList() {
    referenceList.innerHTML = sortedCountries()
      .map((c) => `<div class="country-reference-row"><span>${countryName(c)}</span><span class="country-reference-code">${c.code}</span></div>`)
      .join("");
  }

  countryPicker.addEventListener("change", () => {
    if (!countryPicker.value) return;
    setCodes([...currentCodes(), countryPicker.value]);
    countryPicker.value = "";
  });

  countriesInput.addEventListener("input", renderChips);
  document.addEventListener("langchange", () => {
    renderCountryPicker();
    renderReferenceList();
    renderChips();
  });

  renderCountryPicker();
  renderReferenceList();
  renderChips();

  function buildAdLibraryUrl(country, query) {
    const params = new URLSearchParams({
      active_status: "active",
      ad_type: "all",
      country,
      q: query,
      media_type: "all",
    });
    return `https://www.facebook.com/ads/library/?${params.toString()}`;
  }

  openBtn.addEventListener("click", () => {
    const query = queryInput.value.trim();
    const countries = currentCodes();

    if (!query) {
      meta.textContent = I18N.t("competitors.msg.no_query");
      linksBox.style.display = "none";
      return;
    }
    if (!countries.length) {
      meta.textContent = I18N.t("competitors.msg.no_countries");
      linksBox.style.display = "none";
      return;
    }

    meta.textContent = "";
    // Кожна вибрана країна — окреме посилання зі СВОЇМ country= у query-рядку (Ad Library не
    // вміє показувати кілька країн в одній вкладці за посиланням) — тому НЕ відкриваємо
    // автоматично одну країну, а показуємо кнопку на кожну + "Відкрити всі" одним кліком.
    const links = countries.map((country) => ({ country, url: buildAdLibraryUrl(country, query) }));

    linksList.innerHTML = [
      `<button type="button" class="btn" id="competitors-open-all">${I18N.t("competitors.links.open_all")}</button>`,
      ...links.map(
        ({ country, url }) =>
          `<a class="btn secondary" href="${url}" target="_blank" rel="noopener">${I18N.t("competitors.links.open_country", { code: country })}</a>`
      ),
    ].join("");

    document.getElementById("competitors-open-all").addEventListener("click", () => {
      links.forEach(({ url }) => window.open(url, "_blank", "noopener"));
    });

    linksBox.style.display = "block";
  });
})();
