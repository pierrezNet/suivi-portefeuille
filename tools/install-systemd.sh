#!/usr/bin/env bash
# Installe le service systemd utilisateur Suivi Portefeuille.
# Usage : ./tools/install-systemd.sh [--enable] [--start]
#
# Aucun sudo nécessaire : tout passe par systemd --user.
# L'app sera accessible sur http://127.0.0.1:5000

set -euo pipefail

PROJET="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_SRC="$PROJET/tools/suivi-portefeuille.service"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_DEST="$SERVICE_DIR/suivi-portefeuille.service"

if [[ ! -f "$SERVICE_SRC" ]]; then
    echo "❌ Fichier service introuvable : $SERVICE_SRC" >&2
    exit 1
fi
if [[ ! -x "$PROJET/.venv/bin/python" ]]; then
    echo "❌ Venv introuvable : $PROJET/.venv/bin/python" >&2
    echo "   Lance d'abord : python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

mkdir -p "$SERVICE_DIR"
cp "$SERVICE_SRC" "$SERVICE_DEST"
echo "✅ Fichier service copié vers $SERVICE_DEST"

systemctl --user daemon-reload
echo "✅ systemctl --user daemon-reload effectué"

ENABLE=false
START=false
for arg in "$@"; do
    case "$arg" in
        --enable) ENABLE=true ;;
        --start)  START=true  ;;
        *) echo "Argument inconnu : $arg" >&2; exit 2 ;;
    esac
done

if [[ "$ENABLE" == "true" ]]; then
    systemctl --user enable suivi-portefeuille.service
    echo "✅ Service activé au démarrage de la session utilisateur."
    echo "   Pour qu'il démarre même sans session ouverte, lance UNE FOIS :"
    echo "     loginctl enable-linger \$USER  (peut nécessiter sudo)"
fi

if [[ "$START" == "true" ]]; then
    systemctl --user start suivi-portefeuille.service
    sleep 1
    if systemctl --user is-active --quiet suivi-portefeuille.service; then
        echo "✅ Service démarré : http://127.0.0.1:5000"
    else
        echo "❌ Le service n'a pas démarré. Vérifier :" >&2
        echo "   systemctl --user status suivi-portefeuille.service" >&2
        echo "   journalctl --user -u suivi-portefeuille -n 50" >&2
        exit 1
    fi
fi

cat <<EOF

🔧 Commandes utiles :
  systemctl --user status  suivi-portefeuille    # état
  systemctl --user start   suivi-portefeuille    # démarrer
  systemctl --user stop    suivi-portefeuille    # arrêter
  systemctl --user restart suivi-portefeuille    # redémarrer
  systemctl --user enable  suivi-portefeuille    # auto-start session
  systemctl --user disable suivi-portefeuille    # désactiver auto-start
  journalctl --user -u suivi-portefeuille -f     # logs temps réel
EOF
