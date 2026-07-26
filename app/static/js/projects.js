(function () {
  const switcher = document.getElementById("project-switcher");
  if (!switcher) return;

  const projects = window.__PROJECTS__ || [];
  const activeProject = window.__ACTIVE_PROJECT__;

  function render() {
    switcher.innerHTML = projects
      .map((p) => `<option value="${p.id}">${p.name}</option>`)
      .join("");
    if (activeProject) switcher.value = activeProject.id;
  }

  switcher.addEventListener("change", async () => {
    switcher.disabled = true;
    try {
      await fetch(`/api/projects/${switcher.value}/activate`, { method: "POST" });
      location.reload();
    } catch (e) {
      switcher.disabled = false;
    }
  });

  render();
})();
