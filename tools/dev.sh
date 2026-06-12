#!/usr/bin/env bash
# Lance run.py en mode développement avec les env vars du drop-in systemd.
#
# Pourquoi : BOURSE_PASSWORD et BOURSE_DASHBOARD_REPO sont définies UNIQUEMENT
# dans le drop-in systemd (par sécurité, pour ne pas traîner dans le shell).
# En mode dev, run.py ne les voit pas et le bouton « Publier vers mobile »
# échoue avec « Variable d'environnement BOURSE_DASHBOARD_REPO non définie ».
# Ce wrapper les lit à la volée puis lance run.py.
#
# Usage :  ./tools/dev.sh
# Arrête : Ctrl+C

set -euo pipefail

PROJET="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DROPIN="$HOME/.config/systemd/user/suivi-portefeuille.service.d/override.conf"

if [[ ! -f "$DROPIN" ]]; then
    echo "❌ Drop-in systemd introuvable : $DROPIN" >&2
    echo "   Voir tools/SETUP_CLOUD.md pour le setup initial." >&2
    exit 1
fi

# Évite le conflit de port 5000
if systemctl --user is-active --quiet suivi-portefeuille; then
    echo "⚠️  Le service systemd 'suivi-portefeuille' tourne (port 5000 occupé)."
    echo "   Arrête-le d'abord :  systemctl --user stop suivi-portefeuille"
    exit 1
fi

echo "▶ Mode dev : run.py avec env vars du drop-in systemd"
echo "  Bouton « Publier vers mobile » fonctionnel."
echo

exec env $(sed -n 's/^Environment="\(.*\)"$/\1/p' "$DROPIN") \
     "$PROJET/.venv/bin/python" "$PROJET/run.py"
