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

  // --- Liste-pivot des titres : panneau d'actions déplié au clic sur la ligne -
  function initListePivot() {
    const lignes = document.querySelectorAll(".table-pivot .titre-ligne");
    if (!lignes.length) return;
    lignes.forEach((ligne) => {
      ligne.addEventListener("click", (e) => {
        // Ne pas déclencher si on interagit avec un contrôle de la ligne.
        if (e.target.closest("a, button, input, select, textarea, label, form"))
          return;
        const cible = document.getElementById(ligne.dataset.cible);
        if (!cible) return;
        const ferme = cible.hasAttribute("hidden");
        if (ferme) cible.removeAttribute("hidden");
        else cible.setAttribute("hidden", "");
        ligne.classList.toggle("ouvert", ferme);
      });
    });
  }

  // --- Éditeur de plan de rachat : quantité cible + paliers en lignes --------
  function setupPlanEditor(ed) {
    const rowsBox = ed.querySelector(".plan-rows");
    const fPrix = ed.querySelector(".plan-field-prix");
    const fQte = ed.querySelector(".plan-field-quantite");
    const fComm = ed.querySelector(".plan-field-commentaire");
    const fallback = ed.querySelector(".plan-fallback");
    const cible = ed.querySelector('input[name="cible_totale"]');
    const somme = ed.querySelector(".plan-somme");
    const addBtn = ed.querySelector(".plan-add");
    if (!rowsBox || !fPrix || !fQte || !fComm) return;

    const labelFor = (i) => (i === 0 ? "Premier achat" : "Renforcement");
    const lines = (t) => (t.value || "").split("\n");
    const rows = () => Array.from(rowsBox.querySelectorAll(".plan-row"));

    function sync() {
      const rs = rows();
      fPrix.value = rs.map((r) => r.querySelector(".p-prix").value.trim()).join("\n");
      fQte.value = rs.map((r) => r.querySelector(".p-qte").value.trim()).join("\n");
      fComm.value = rs.map((r, i) => labelFor(i)).join("\n");
      rs.forEach((r, i) => {
        r.querySelector(".p-label").textContent = labelFor(i);
        r.querySelector(".p-remove").style.visibility = i === 0 ? "hidden" : "visible";
      });
      let s = 0;
      rs.forEach((r) => {
        const q = parseFloat(r.querySelector(".p-qte").value.replace(",", "."));
        if (!isNaN(q)) s += q;
      });
      const c = parseFloat((cible.value || "").replace(",", "."));
      let txt = "Σ quantités = " + (s || 0);
      if (!isNaN(c)) txt += " / cible " + c + (s === c ? " ✓" : "");
      somme.textContent = txt;
    }

    function addRow(prix, qte) {
      const row = document.createElement("div");
      row.className = "plan-row";
      row.innerHTML =
        '<span class="p-label pill"></span>' +
        '<input class="p-prix" type="number" step="0.01" placeholder="prix">' +
        '<input class="p-qte" type="number" step="1" placeholder="qté">' +
        '<button type="button" class="btn-icone p-remove" title="Retirer ce palier">✕</button>';
      row.querySelector(".p-prix").value = prix || "";
      row.querySelector(".p-qte").value = qte || "";
      row.querySelector(".p-prix").addEventListener("input", sync);
      row.querySelector(".p-qte").addEventListener("input", sync);
      row.querySelector(".p-remove").addEventListener("click", () => {
        row.remove();
        sync();
      });
      rowsBox.appendChild(row);
    }

    const prixL = lines(fPrix), qteL = lines(fQte);
    const n = Math.max(prixL.length, qteL.length);
    let created = 0;
    for (let i = 0; i < n; i++) {
      if ((prixL[i] || "").trim() || (qteL[i] || "").trim()) {
        addRow((prixL[i] || "").trim(), (qteL[i] || "").trim());
        created++;
      }
    }
    while (created < 2) { addRow("", ""); created++; } // Premier achat + Renforcement

    addBtn && addBtn.addEventListener("click", () => { addRow("", ""); sync(); });
    cible && cible.addEventListener("input", sync);
    if (fallback) fallback.hidden = true; // JS OK : on masque les textareas brutes
    sync();
  }

  function initPlanEditors() {
    document.querySelectorAll(".plan-editor").forEach(setupPlanEditor);
  }

  // --- « En faire un ordre » : pré-remplit le formulaire d'ordre depuis un palier
  function initPalierVersOrdre() {
    const btns = document.querySelectorAll(".palier-to-ordre");
    if (!btns.length) return;
    const bloc = document.getElementById("bloc-ordre");
    if (!bloc) return;
    const set = (name, val) => {
      const el = bloc.querySelector('[name="' + name + '"]');
      if (el) el.value = val;
    };
    btns.forEach((btn) => {
      btn.addEventListener("click", () => {
        bloc.open = true; // ouvre le <details> du formulaire d'ordre
        set("ordre_sens", "achat");
        set("ordre_prix", btn.dataset.prix || "");
        set("ordre_quantite", btn.dataset.qte || "");
        bloc.scrollIntoView({ behavior: "smooth", block: "center" });
        const val = bloc.querySelector('[name="ordre_validite"]');
        if (val) val.focus();
      });
    });
  }

  function init() {
    initTabsDashboard();
    initListePivot();
    initPlanEditors();
    initPalierVersOrdre();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
