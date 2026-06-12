#!/usr/bin/env bash
# Sauvegarde du dossier data/ vers ~/sauvegardes/suivi-portefeuille.
# Idempotent et autonome : peut être lancé depuis n'importe quel cwd ou par cron.
#
# Usage :
#   ./tools/backup.sh           # destination par défaut ~/sauvegardes/suivi-portefeuille
#   DEST=/autre/dest ./tools/backup.sh
#
# Rétention : garde les 30 archives les plus récentes.

set -euo pipefail

PROJET="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${DEST:-$HOME/sauvegardes/suivi-portefeuille}"
DATE="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$DEST/data-$DATE.tar.gz"
RETENTION="${RETENTION:-30}"

if [[ ! -d "$PROJET/data" ]]; then
    echo "❌ Dossier introuvable : $PROJET/data" >&2
    exit 1
fi

mkdir -p "$DEST"

# Création de l'archive depuis la racine du projet, contenu = data/
tar -czf "$ARCHIVE" -C "$PROJET" data
TAILLE="$(du -h "$ARCHIVE" | cut -f1)"
echo "✅ Sauvegarde créée : $ARCHIVE ($TAILLE)"

# Rétention : conserver les N plus récentes, supprimer le reste
SUPPRIMEES=0
if cd "$DEST" 2>/dev/null; then
    while IFS= read -r ancien; do
        rm -f -- "$ancien"
        SUPPRIMEES=$((SUPPRIMEES + 1))
    done < <(ls -1t data-*.tar.gz 2>/dev/null | tail -n +$((RETENTION + 1)))
fi

if [[ "$SUPPRIMEES" -gt 0 ]]; then
    echo "🗑  $SUPPRIMEES archive(s) ancienne(s) purgée(s) (rétention $RETENTION)."
fi
