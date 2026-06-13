# IA : faire challenger mes thèses par Claude (serveur MCP)

Mettre à jour les thèses et le journal est contraignant. Ce module branche
**Claude** (Desktop ou Code) sur tes données **locales** via un petit serveur
**MCP**, pour qu'il **challenge tes thèses au vu de l'actualité** et te
**propose** des notes / révisions — que **tu valides** (ou rejettes) dans l'app.

## Esprit (souveraineté préservée)

- Le serveur **expose** tes données en local ; **Claude** fait le travail
  (lecture + recherche web pour l'actu + critique). **Notre code n'appelle
  jamais l'API Claude** → zéro clé API, zéro coût côté app.
- Rien n'est modifié sans toi : Claude **dépose une proposition**, tu
  l'**acceptes/édites/rejettes** sur la fiche du titre. La traçabilité est
  conservée (note datée, ou ancienne thèse archivée dans l'historique).
- Tes données ne « partent » que via **ta** session Claude, quand **toi** tu le
  demandes. L'app Flask reste 100 % offline.

## Installation (une fois)

```bash
cd /var/www/html/Bourse
.venv/bin/pip install -r requirements-mcp.txt
```

## Brancher dans Claude Desktop

Édite `claude_desktop_config.json` (Réglages → Developer → Edit Config ;
emplacement : `~/.config/Claude/` sous Linux, `%APPDATA%\Claude\` sous Windows,
`~/Library/Application Support/Claude/` sous macOS) :

```json
{
  "mcpServers": {
    "suivi-portefeuille": {
      "command": "/var/www/html/Bourse/.venv/bin/python",
      "args": ["/var/www/html/Bourse/tools/mcp_server.py"],
      "env": { "BOURSE_DATA_DIR": "/var/www/html/Bourse/data" }
    }
  }
}
```

Redémarre Claude Desktop → l'outil « suivi-portefeuille » apparaît (icône 🔌).

## Brancher dans Claude Code

```bash
claude mcp add suivi-portefeuille \
  -e BOURSE_DATA_DIR=/var/www/html/Bourse/data \
  -- /var/www/html/Bourse/.venv/bin/python /var/www/html/Bourse/tools/mcp_server.py
```

## Outils exposés

| Outil | Rôle |
|---|---|
| `lister_titres` | catalogue (id, ticker, nom, secteur, horizon) |
| `lire_titre` | thèse LT, signaux MT+/-, perspectives, **historique des thèses** |
| `lire_journal` | notes datées du titre |
| `resume_portefeuille` | cash, valorisation, PV latente, positions |
| `proposer_note` | **dépose** une note de journal (à valider) |
| `proposer_revision_these` | **dépose** une révision de thèse (champ versionné, à valider) |

## Le cycle

1. Dans Claude : *« Lis ma thèse STM et le journal, cherche l'actualité récente
   du titre, et challenge-la : qu'est-ce qui la fragilise / la confirme ? »*
2. Claude lit via MCP, fait sa **recherche web**, te répond, puis (si tu lui
   demandes) appelle `proposer_revision_these` / `proposer_note`.
3. Dans l'app, sur la **fiche du titre**, section **« 💡 Suggestions IA en
   attente »** : édite si besoin → **✓ Accepter** (→ journal, ou thèse mise à
   jour + ancienne version archivée) ou **✗ Rejeter**.

> 💡 Garde la main : Claude est un **avocat du diable / assistant de veille**,
> pas un ghostwriter. Vérifie les sources qu'il cite ; la thèse reste **ta**
> conviction.
