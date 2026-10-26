# SPEC-050 — Mode hors-ligne (service worker + cache)

Statut : livré — branche `agent/spec-050-offline_pwa`.
Périmètre : `desktop_static/` (frontend bureau `/app`), aucune dépendance ajoutée,
aucune soumission automatique, aucune donnée réelle utilisée pour les essais.

## Livrables

| Fichier | Rôle |
| --- | --- |
| `desktop_static/sw.js` | Service worker (scope `/`) : précache de la coquille, stratégies de fetch, purge des caches versionnés. |
| `desktop_static/manifest.webmanifest` | Manifeste PWA installable (`start_url=/app`, `display=standalone`, icône 1024²). |
| `desktop_static/offline.html` | Page de secours hors-ligne, sans script ni style inline (compatible CSP). |
| `desktop_static/index.html` | Lien manifeste, `theme-color`, bandeau hors-ligne `#offlineBanner`. |
| `desktop_static/app.js` | Enregistrement du worker (`scope: "/"`), bandeau + statut pilotés par `online`/`offline`, détection de l'en-tête `X-Nage-Offline`. |
| `desktop_static/app.css` | Styles du bandeau et de la page de secours. |
| `come_ai_web.py` | Routes `/sw.js` (avec `Service-Worker-Allowed: /`) et `/app.webmanifest`. |
| `tests/test_offline_pwa.py` | 8 tests ciblés (fichiers, manifeste, enregistrement, routes HTTP). |
| `scripts/check_offline_pwa.mjs` | Vérification réelle par CDP (Chrome headless), phases `online` / `offline`. |

## Stratégies de cache

- **Navigations** : réseau d'abord (timeout 3 s), puis `/app` en cache, puis
  `offline.html`.
- **API `GET /api/*`** : réseau d'abord (timeout 2,5 s), sinon réponse en cache
  marquée `X-Nage-Offline: 1` (l'UI affiche « Hors-ligne · cache local » et le
  bandeau). Requête jamais vue → JSON `503 {detail, offline: true}`.
- **Assets `/app-static/*`** : cache d'abord, revalidation en arrière-plan
  rattachée à `event.waitUntil` (le worker reste vivant jusqu'à la mise à jour).
- **Écritures** : jamais interceptées ni mises en cache (`request.method !== "GET"`).
- **Versionnement** : caches `nage-v2-{shell,assets,api}` ; les anciens caches sont
  supprimés à l'activation ; `skipWaiting` + `clients.claim`.

## Tests automatisés

```text
.venv/bin/python -m pytest -q tests/test_offline_pwa.py
........                                                                 [100%]
8 passed in 2.38s

.venv/bin/python -m ruff check come_ai_web.py tests/test_offline_pwa.py
All checks passed!
```

## Test manuel CDP (Chrome headless 155)

Procédure (serveur sur `127.0.0.1:8877`, Chrome `--headless=new
--remote-debugging-port=9223 --user-data-dir=<profil temporaire>`) :

```bash
PHASE=online  node scripts/check_offline_pwa.mjs   # amorce le cache
pkill -f offline_pwa_server.py                     # serveur réellement arrêté
PHASE=offline node scripts/check_offline_pwa.mjs   # vérifie la bascule hors-ligne
```

L'émulation réseau CDP ne s'applique pas aux `fetch` du service worker lui-même :
le test arrête donc réellement le serveur avant la phase `offline`.

Résultat observé :

```json
{
  "phase": "online",
  "registration": { "scope": "http://127.0.0.1:8877/", "state": "activated" },
  "status": "Local · 127.0.0.1",
  "cachedKeys": ["nage-v2-api", "nage-v2-assets", "nage-v2-shell"]
}
```

```json
{
  "phase": "offline",
  "shell": {
    "title": "NAGE // machine de candidatures",
    "shell": true,
    "bannerVisible": true,
    "status": "Hors-ligne · cache local"
  },
  "cachedApi": { "status": 200, "fromCache": true },
  "unknownApi": { "status": 503, "offline": true }
}
```

Interprétation : la coquille `/app` se recharge serveur arrêté, le bandeau et le
statut passent hors-ligne, le dashboard déjà consulté est servi depuis le cache
(200 + en-tête), une API jamais consultée renvoie le JSON 503 prévu.

## Limites assumées

- Seules les réponses API déjà consultées sont disponibles hors-ligne ; aucune
  donnée n'est préchargée en masse.
- Pas de synchronisation différée des écritures (aucune file d'envoi) : le mode
  hors-ligne est strictement consultatif, conformément au périmètre.
- Le cache reste local au navigateur ; la purge se fait via une nouvelle version
  (`CACHE_VERSION`) ou le message `CLEAR_OFFLINE_CACHE`.
