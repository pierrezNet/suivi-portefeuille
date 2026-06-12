// Interactions UI légères, vanilla JS.

(function () {
  // --- Onglets dashboard (Chiffres / Graphiques) -----------------------------
  function initTabsDashboard() {
    const tabs = document.querySelectorAll(".tabs-dashboard [data-onglet]");
    if (!tabs.length) return;
    const onglets = document.querySelectorAll(".dashboard-corps .onglet");
    const STORE_KEY = "suivi-portefeuille:dashboard-onglet";

    function activer(nom) {
      tabs.forEach((t) => t.classList.toggle("actif", t.dataset.onglet === nom));
      onglets.forEach((o) => o.classList.toggle("actif", o.dataset.onglet === nom));
      try {
        localStorage.setItem(STORE_KEY, nom);
      } catch (e) {
        // localStorage indispo (private mode) : on continue sans persister
      }
    }

    tabs.forEach((t) =>
      t.addEventListener("click", () => activer(t.dataset.onglet))
    );

    let initial = "chiffres";
    try {
      const memo = localStorage.getItem(STORE_KEY);
      if (memo === "chiffres" || memo === "graphiques") initial = memo;
    } catch (e) {}
    activer(initial);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTabsDashboard);
  } else {
    initTabsDashboard();
  }
})();
