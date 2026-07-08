(function () {
  "use strict";

  const LS_KEY_MDP = "suivi-portefeuille:mdp";
  const URL_DATA = "data.enc.json";

  // --- Crypto helpers (compatible chiffrement Python AES-256-GCM/PBKDF2) ----
  function b64ToBytes(b64) {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  async function deriverCle(motPasse, salt, iterations) {
    const enc = new TextEncoder();
    const baseKey = await crypto.subtle.importKey(
      "raw",
      enc.encode(motPasse),
      { name: "PBKDF2" },
      false,
      ["deriveKey"]
    );
    return crypto.subtle.deriveKey(
      {
        name: "PBKDF2",
        salt: salt,
        iterations: iterations,
        hash: "SHA-256",
      },
      baseKey,
      { name: "AES-GCM", length: 256 },
      false,
      ["decrypt"]
    );
  }

  async function dechiffrer(paquet, motPasse) {
    if (paquet.v !== 1) throw new Error("Version inconnue : " + paquet.v);
    const salt = b64ToBytes(paquet.salt);
    const iv = b64ToBytes(paquet.iv);
    const ct = b64ToBytes(paquet.ct);
    // Repli aligné sur le défaut Python (chiffrement.ITERATIONS) ; en pratique
    // `paquet.iter` est toujours présent dans data.enc.json.
    const cle = await deriverCle(motPasse, salt, paquet.iter || 600000);
    const clair = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: iv },
      cle,
      ct
    );
    const texte = new TextDecoder("utf-8").decode(clair);
    return JSON.parse(texte);
  }

  // --- Helpers de formatage (alignés sur dashboard_mobile.js) ---------------
  function fmtEuros(valeur) {
    if (valeur === null || valeur === undefined || valeur === "") return "—";
    const n = Number(valeur);
    if (Number.isNaN(n)) return String(valeur);
    const signe = n < 0 ? "-" : "";
    const abs = Math.abs(n);
    const entier = Math.floor(abs);
    const dec = Math.round((abs - entier) * 100).toString().padStart(2, "0");
    const entierFmt = entier.toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
    return `${signe}${entierFmt},${dec} €`;
  }

  function fmtQuantite(valeur) {
    if (valeur === null || valeur === undefined || valeur === "") return "—";
    const n = Number(valeur);
    if (Number.isNaN(n)) return String(valeur);
    if (Number.isInteger(n)) return String(n);
    // Décimal : virgule française, sans zéros morts
    return n.toString().replace(/\.?0+$/, "").replace(".", ",");
  }

  function fmtDate(iso) {
    if (!iso) return "";
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
    return m ? `${m[3]}/${m[2]}/${m[1]}` : iso;
  }

  function joursAvant(iso) {
    if (!iso) return null;
    const d = new Date(iso + "T00:00:00");
    if (isNaN(d.getTime())) return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return Math.round((d - today) / 86400000);
  }

  function texteJours(n) {
    if (n === 0) return "aujourd'hui";
    if (n === 1) return "demain";
    if (n > 1) return `dans ${n} j`;
    return `${-n} j passé(s)`;
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // --- Rendu (identique à dashboard_mobile.js) ------------------------------
  function renderBandeauActualisation(data) {
    if (!data.cours_a_actualiser) return "";
    const parts = [];
    if (data.nb_positions_sans_cours > 0) {
      parts.push(`${data.nb_positions_sans_cours} position(s) sans cours du jour`);
    }
    if (data.age_cours_max_jours && data.age_cours_max_jours > 7) {
      parts.push(`Cours le plus ancien : ${data.age_cours_max_jours} j`);
    }
    return `<div class="bandeau-info" style="background:#fff8e1;border-left:4px solid #fcc63a">
      ⚠️ ${parts.join(" · ")}. À actualiser via l'import xlsx sur le poste fixe.
    </div>`;
  }

  function renderCamemberts(data) {
    if (!data.coords_camemberts) return "";
    const libelles = {compte: "Par compte", categorie: "Par catégorie", devise: "Par devise"};
    const blocs = ["compte", "categorie", "devise"]
      .map((axe) => {
        const c = data.coords_camemberts[axe];
        const parts = (data.repartitions && data.repartitions[axe]) || [];
        if (!c || c.vide) return "";
        const slices = c.slices
          .map((s) => {
            if (s.circle) {
              return `<circle cx="${c.cx}" cy="${c.cy}" r="${c.rayon}" fill="${s.couleur}"/>`;
            }
            return `<path d="${s.path}" fill="${s.couleur}" stroke="#fff" stroke-width="1"/>`;
          })
          .join("");
        const legende = parts
          .map((p, i) => {
            const couleur = c.slices[i] ? c.slices[i].couleur : "#888";
            return `<li>
              <span class="puce" style="background:${couleur}"></span>
              <span class="lbl">${escapeHtml(p.label)}</span>
              <span class="pct">${escapeHtml(String(p.pourcentage))} %</span>
            </li>`;
          })
          .join("");
        return `<div class="camembert-bloc">
          <h3>${libelles[axe]}</h3>
          <svg viewBox="0 0 ${c.taille} ${c.taille}" xmlns="http://www.w3.org/2000/svg" class="camembert-svg">
            ${slices}
          </svg>
          <ul class="camembert-legende">${legende}</ul>
        </div>`;
      })
      .join("");
    if (!blocs) return "";
    return `<section class="bloc-camemberts">${blocs}</section>`;
  }

  function renderEquity(data) {
    const c = data.equity_coords;
    const pts = data.equity_points || [];
    if (!c || !c.polyline || pts.length < 2) return "";
    const labels = (c.labels_x || [])
      .map((l, i) => {
        const pas = Math.max(1, Math.ceil(c.labels_x.length / 6));
        if (i % pas === 0 || i === c.labels_x.length - 1) {
          return `<text x="${l.x}" y="${c.hauteur - 6}" text-anchor="middle" font-size="10" fill="#666">${escapeHtml(l.texte)}</text>`;
        }
        return "";
      })
      .join("");
    return `
      <section class="bloc">
        <h2>📈 Évolution (${pts.length} mois)</h2>
        <div class="muted" style="margin-bottom:0.5rem">de ${fmtEuros(c.premier)} à <strong>${fmtEuros(c.dernier)}</strong></div>
        <svg viewBox="0 0 ${c.largeur} ${c.hauteur}" xmlns="http://www.w3.org/2000/svg"
             style="width:100%;height:auto;max-height:220px;display:block">
          <line x1="${c.marge}" y1="${c.hauteur - c.marge}" x2="${c.largeur - c.marge}" y2="${c.hauteur - c.marge}" stroke="#ddd" stroke-width="1"/>
          <polyline fill="none" stroke="#000091" stroke-width="2" points="${c.polyline}"/>
          <text x="${c.largeur - 4}" y="${c.marge + 4}" text-anchor="end" font-size="10" fill="#666">${fmtEuros(c.max)}</text>
          <text x="${c.largeur - 4}" y="${c.hauteur - c.marge - 4}" text-anchor="end" font-size="10" fill="#666">${fmtEuros(c.min)}</text>
          ${labels}
        </svg>
      </section>
    `;
  }

  function renderKpis(data) {
    const stats = data.stats_annee || {};
    const a = data.annee_courante;
    const pv = Number(stats.plus_values_realisees || 0);
    const pvClass = pv > 0 ? "pv-positive" : pv < 0 ? "pv-negative" : "";
    const pvLat = Number(data.total_pv_latente || 0);
    const pvLatClass = pvLat > 0 ? "pv-positive" : pvLat < 0 ? "pv-negative" : "";
    return `
      <section class="kpis">
        <div class="kpi kpi-cash">
          <span class="kpi-label">Portefeuille total</span>
          <span class="kpi-value">${fmtEuros(data.total_portefeuille)}</span>
          <span class="kpi-detail muted">${fmtEuros(data.total_cash)} cash · ${fmtEuros(data.total_valo_titres)} titres</span>
        </div>
        <div class="kpi">
          <span class="kpi-label">PV latente</span>
          <span class="kpi-value ${pvLatClass}">${fmtEuros(pvLat)}</span>
        </div>
        <div class="kpi">
          <span class="kpi-label">Investi ${a}</span>
          <span class="kpi-value">${fmtEuros(stats.montant_investi)}</span>
        </div>
        <div class="kpi">
          <span class="kpi-label">PV ${a}</span>
          <span class="kpi-value ${pvClass}">${fmtEuros(pv)}</span>
        </div>
        <div class="kpi">
          <span class="kpi-label">Dividendes ${a}</span>
          <span class="kpi-value">${fmtEuros(stats.dividendes_recus_eur)}</span>
        </div>
        <div class="kpi">
          <span class="kpi-label">Frais ${a}</span>
          <span class="kpi-value">${fmtEuros(stats.frais_courtage_total)}</span>
        </div>
      </section>
    `;
  }

  function renderComptes(data) {
    if (!data.comptes || data.comptes.length === 0) return "";
    return data.comptes
      .map((vue) => {
        const c = vue.compte;
        const typeBadge = (c.type || "").toLowerCase();
        const positionsRows =
          vue.positions && vue.positions.length
            ? `<div class="position-cards">
                 ${vue.positions
                   .map((p) => {
                     const pvCls = p.pv_latente_eur != null && Number(p.pv_latente_eur) > 0 ? "pv-positive" : (p.pv_latente_eur != null && Number(p.pv_latente_eur) < 0 ? "pv-negative" : "");
                     const pvLigne = p.pv_latente_eur != null
                       ? `<span class="${pvCls}">PV ${fmtEuros(p.pv_latente_eur)}</span>`
                       : "";
                     return `<article class="position-card">
                       <header class="position-card-header">
                         <code class="ticker">${escapeHtml(p.ticker)}</code>
                         <span class="nom">${escapeHtml(p.nom)}</span>
                       </header>
                       <div class="position-kpis">
                         <div class="position-kpi"><span class="label">Qté</span><span class="valeur">${fmtQuantite(p.quantite)}</span></div>
                         <div class="position-kpi"><span class="label">PRU</span><span class="valeur">${p.pru ? fmtEuros(p.pru) : "—"}</span></div>
                         <div class="position-kpi"><span class="label">Cours</span><span class="valeur">${p.cours_jour_eur ? fmtEuros(p.cours_jour_eur) : "—"}</span></div>
                       </div>
                       <div class="position-footer">
                         <span>Valo <strong>${p.valo_eur != null ? fmtEuros(p.valo_eur) : "—"}</strong></span>
                         ${pvLigne}
                       </div>
                     </article>`;
                   })
                   .join("")}
               </div>`
            : `<p class="aucun" style="padding:0.7rem 0.85rem">Aucune position en cours.</p>`;
        const pvLatCompteCls = vue.pv_latente_eur && Number(vue.pv_latente_eur) > 0 ? "pv-positive" : (vue.pv_latente_eur && Number(vue.pv_latente_eur) < 0 ? "pv-negative" : "");
        const valoDetail = vue.valo_titres_eur && Number(vue.valo_titres_eur) > 0
          ? `<small class="muted">${fmtEuros(vue.solde_cash)} cash · ${fmtEuros(vue.valo_titres_eur)} titres</small>`
          : `<small class="muted">${fmtEuros(vue.solde_cash)} cash</small>`;
        const pvLatLigne = vue.pv_latente_eur && Number(vue.pv_latente_eur) !== 0
          ? `<div class="${pvLatCompteCls}">PV latente ${fmtEuros(vue.pv_latente_eur)}</div>`
          : "";
        return `
          <article class="compte-card">
            <header class="compte-card-header">
              <div>
                <span class="badge badge-${typeBadge}">${escapeHtml(c.type || "")}</span>
                <strong>${escapeHtml(c.nom)}</strong>
              </div>
              <div style="text-align:right">
                <span class="solde">${fmtEuros(vue.total_eur != null ? vue.total_eur : vue.solde_cash)}</span>
                ${valoDetail}
                ${pvLatLigne}
              </div>
            </header>
            ${positionsRows}
          </article>
        `;
      })
      .join("");
  }

  function renderAgenda(data) {
    if (!data.agenda || data.agenda.length === 0) {
      return `<section class="bloc"><h2>📅 Agenda ${data.agenda_horizon_jours} jours</h2><p class="aucun">Rien à venir.</p></section>`;
    }
    const items = data.agenda
      .map((it) => {
        const n = joursAvant(it.date);
        const restant = n !== null ? `<small>${texteJours(n)}</small>` : "";
        const ticker = it.ticker ? ` <code>${escapeHtml(it.ticker)}</code>` : "";
        const notes = it.notes ? `<small>${escapeHtml(it.notes)}</small>` : "";
        return `
          <li>
            <div class="date">
              <strong>${fmtDate(it.date)}</strong>
              ${restant}
            </div>
            <div class="corps">
              <span class="type-libelle">${escapeHtml(it.type_libelle)}</span>${ticker}
              <div>${escapeHtml(it.libelle)}</div>
              ${notes}
            </div>
          </li>
        `;
      })
      .join("");
    return `
      <section class="bloc">
        <h2>📅 Agenda ${data.agenda_horizon_jours} jours</h2>
        <ul class="agenda">${items}</ul>
      </section>
    `;
  }

  function renderWatchlist(data) {
    if (!data.watchlist_haute || data.watchlist_haute.length === 0) return "";
    const items = data.watchlist_haute
      .map((w) => {
        const ticker = w.ticker ? `<code>${escapeHtml(w.ticker)}</code> ` : "";
        const these = w.these_lt ? `<small>${escapeHtml(w.these_lt)}</small>` : "";
        return `<li><span class="nom">${ticker}${escapeHtml(w.nom || w.ticker || "—")}</span>${these}</li>`;
      })
      .join("");
    return `
      <section class="bloc">
        <h2>🎯 Watchlist priorité haute</h2>
        <ul class="watchlist-aside">${items}</ul>
      </section>
    `;
  }

  function renderOrdresActifs(data) {
    if (!data.ordres_actifs || data.ordres_actifs.length === 0) return "";
    const items = data.ordres_actifs
      .map((o) => {
        const n = joursAvant(o.validite);
        const restant = n !== null ? `<small>${texteJours(n)}</small>` : "";
        const symbole = o.devise === "USD" ? "$" : (o.devise === "EUR" ? "€" : escapeHtml(o.devise || ""));
        const sens = o.sens === "vente" ? "Vente" : "Achat";
        const note = o.note ? `<small>${escapeHtml(o.note)}</small>` : "";
        return `
          <li class="ordre-${o.sens === "vente" ? "vente" : "achat"}">
            <div class="date">
              <strong>${o.validite ? fmtDate(o.validite) : "—"}</strong>
              ${restant}
            </div>
            <div class="corps">
              <span class="type-libelle">Ordre — ${sens}</span> <code>${escapeHtml(o.ticker)}</code>
              <div>${escapeHtml(String(o.prix_limite))} ${symbole} × ${fmtQuantite(o.quantite)}</div>
              ${note}
            </div>
          </li>
        `;
      })
      .join("");
    return `
      <section class="bloc">
        <h2>📋 Ordres limites actifs</h2>
        <ul class="agenda">${items}</ul>
      </section>
    `;
  }

  function renderPredictions(data) {
    if (!data.predictions_en_cours || data.predictions_en_cours.length === 0) return "";
    const items = data.predictions_en_cours
      .map((p) => {
        const n = joursAvant(p.date_echeance);
        const restant = n !== null ? `<small>${texteJours(n)}</small>` : "";
        const symbole = p.devise === "USD" ? "$" : (p.devise === "EUR" ? "€" : escapeHtml(p.devise || ""));
        const sens = p.sens === "baisse" ? "📉 Baisse" : "📈 Hausse";
        const conv = p.conviction || 0;
        const etoiles = "★".repeat(conv) + "☆".repeat(5 - conv);
        return `
          <li class="prediction-${p.sens === "baisse" ? "baisse" : "hausse"}">
            <div class="date">
              <strong>${p.date_echeance ? fmtDate(p.date_echeance) : "—"}</strong>
              ${restant}
            </div>
            <div class="corps">
              <span class="type-libelle">${sens}</span> <code>${escapeHtml(p.ticker)}</code>
              <div>réf. ${escapeHtml(String(p.cours_reference))} ${symbole} · ${etoiles}</div>
            </div>
          </li>
        `;
      })
      .join("");
    return `
      <section class="bloc">
        <h2>🔮 Prédictions en cours</h2>
        <ul class="agenda">${items}</ul>
      </section>
    `;
  }

  function afficher(data) {
    document.getElementById("genere-le").textContent =
      "Synchronisé le " + (data.genere_le_fr || "—");
    document.getElementById("app").innerHTML =
      renderBandeauActualisation(data) +
      renderKpis(data) +
      renderCamemberts(data) +
      renderEquity(data) +
      `<section><h2>Comptes</h2>${renderComptes(data)}</section>` +
      renderOrdresActifs(data) +
      renderPredictions(data) +
      renderAgenda(data) +
      renderWatchlist(data);
  }

  // --- Flux principal -------------------------------------------------------
  let paquetGlobal = null;

  function ouvrirModale(messageErreur) {
    const fond = document.getElementById("modale-fond");
    const err = document.getElementById("erreur-mdp");
    fond.style.display = "flex";
    if (messageErreur) {
      err.textContent = messageErreur;
      err.classList.add("visible");
    } else {
      err.classList.remove("visible");
    }
    setTimeout(() => document.getElementById("mdp").focus(), 50);
  }

  function fermerModale() {
    document.getElementById("modale-fond").style.display = "none";
  }

  async function tenterDechiffrement(mdp, memoriser) {
    try {
      const data = await dechiffrer(paquetGlobal, mdp);
      if (memoriser) {
        localStorage.setItem(LS_KEY_MDP, mdp);
      }
      fermerModale();
      afficher(data);
    } catch (e) {
      console.warn("Échec déchiffrement", e);
      localStorage.removeItem(LS_KEY_MDP);
      ouvrirModale("Mot de passe incorrect.");
    }
  }

  async function init() {
    document.getElementById("app").innerHTML = "<p>Chargement des données chiffrées…</p>";
    // Le service worker (PWA) intercepte data.enc.json avec une stratégie
    // network-first + fallback cache : on ne force PAS no-store ni le query string
    // anti-cache, sinon le SW ne pourrait plus servir la version mise en cache
    // en mode hors ligne.
    try {
      const reponse = await fetch(URL_DATA);
      if (!reponse.ok) throw new Error("HTTP " + reponse.status);
      paquetGlobal = await reponse.json();
    } catch (e) {
      document.getElementById("app").innerHTML =
        `<p style="color:var(--rouge)">Impossible de charger les données : ${escapeHtml(e.message)}</p>`;
      return;
    }

    // Bandeau "hors ligne" si le navigateur est offline au moment du chargement.
    if (!navigator.onLine) {
      const indicateur = document.getElementById("genere-le");
      if (indicateur) {
        indicateur.innerHTML += ' <span style="color:#b34700">· 📡 mode hors ligne</span>';
      }
    }

    const mdpMemo = localStorage.getItem(LS_KEY_MDP);
    if (mdpMemo) {
      try {
        const data = await dechiffrer(paquetGlobal, mdpMemo);
        afficher(data);
        return;
      } catch (e) {
        // Le mdp mémorisé ne marche plus (changement de mot de passe ?)
        localStorage.removeItem(LS_KEY_MDP);
        ouvrirModale("Mot de passe mémorisé invalide — re-saisis.");
        return;
      }
    }
    ouvrirModale();
  }

  document.getElementById("modale-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const mdp = document.getElementById("mdp").value.trim();
    const memoriser = document.getElementById("memoriser").checked;
    tenterDechiffrement(mdp, memoriser);
  });

  document.getElementById("btn-recharger").addEventListener("click", () => {
    init();
  });

  document.getElementById("btn-oublier").addEventListener("click", () => {
    localStorage.removeItem(LS_KEY_MDP);
    location.reload();
  });

  init();
})();
