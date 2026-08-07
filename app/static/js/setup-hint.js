(function () {
  const banner = document.getElementById("setup-hint-banner");
  if (!banner) return;
  const cta = document.getElementById("setup-hint-cta");

  if (cta) {
    cta.addEventListener("click", () => {
      const btn = document.querySelector('.tab-btn[data-tab="settings"]');
      if (btn) btn.click();
    });
  }

  fetch("/api/onboarding/status")
    .then((res) => res.json())
    .then((data) => {
      if (!data.ig_ok && !data.ads_ok) {
        banner.classList.add("show");
      }
    })
    .catch(() => {});
})();
