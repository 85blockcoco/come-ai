# LOT F — Sécurité, interface, performance

Base : worktree jetable `/tmp/audit_5ef814e` sur `5ef814e`. `HOME=/tmp/audit_home`.

## F.1 Adresse d'écoute réelle

| ID | Affirmation | Preuve | Statut |
|---|---|---|---|
| F1-1 | Uvicorn bind `127.0.0.1`, port par défaut 8765 | `run_come_ai_v3.py:43-44` | LU |
| F1-2 | `TrustedHostMiddleware` avec `allowed_hosts = ["127.0.0.1", "localhost", "testserver", "[::1]"]` | `come_ai_web.py:336-340` | LU |

## F.2 TestClient — Origin / Host / tailles

Script : `/tmp/audit_F_http.py` + `/tmp/audit_F_http2.py` + `/tmp/audit_F_msg.py` (sorties `raw/`).

| ID | Cas | Statut observé | Sortie brute | SHA | Statut |
|---|---|---|---|---|---|
| F2-1 | POST `/api/v5/chat` avec `Origin` étranger | 403 | `{"detail":"La conversation doit être lancée depuis cette application locale."}` | `5ef814e` | EXÉCUTÉ |
| F2-2 | POST `/api/v5/chat` avec `Host` inattendu | 400 | `Invalid host header` | `5ef814e` | EXÉCUTÉ |
| F2-3 | POST `/api/files/upload` avec `Origin` étranger | 200 (pas de garde Origin sur l'upload) | import accepté | `5ef814e` | EXÉCUTÉ |
| F2-4 | POST `/api/files/upload` avec `Host` inattendu | 400 | `Invalid host header` | `5ef814e` | EXÉCUTÉ |
| F2-5 | En-têtes renvoyés (chat) | — | `cache-control: no-store`, `x-content-type-options: nosniff`, `referrer-policy: no-referrer`, `x-frame-options: DENY`, `content-security-policy: default-src 'self'; ...` | `5ef814e` | EXÉCUTÉ |
| F2-6 | Upload taille = limite (100 Mo, content-length) | 400 (passe la garde, body vide) | `Sélectionne au moins un fichier à importer.` | `5ef814e` | EXÉCUTÉ |
| F2-7 | Upload taille = limite + 1 | 413 | `Lot d’import trop volumineux (maximum 100 Mo au total).` | `5ef814e` | EXÉCUTÉ |
| F2-8 | Message chat = 12 000 chars | 200 | réponse OK | `5ef814e` | EXÉCUTÉ |
| F2-9 | Message chat = 12 001 chars | 422 | `La demande envoyée à l’application est invalide.` | `5ef814e` | EXÉCUTÉ |

## F.3 `redact_text` / `SECRET_PATTERN` — 15 chaînes factices

Fonctions testées : `task_queue.redact_text`, `usage_ledger.redact_text`, `devkit.exporting.redact_text` (sortie `raw/audit_F_redact_out.txt`). Légende : M = masqué, U = non masqué.

| # | Chaîne factice (tronquée) | task_queue | usage_ledger | devkit_exporting |
|---|---|---|---|---|
| 1 | `AIzaABCDEFGHIJKLMNOPQRSTUVWXYZ123456` | M | M | M |
| 2 | `sk-or-v1-abcdefghijklmnopqrstuvwxyz01234` | U | M | M |
| 3 | `sk_abcdefghijklmnopqrstuvwxyz012345` | M | M | U |
| 4 | `rk_abcdefghijklmnopqrstuvwxyz012345` | M | M | U |
| 5 | `pk_abcdefghijklmnopqrstuvwxyz012345` | M | M | U |
| 6 | `authorization: Bearer abcdefghijklmnopqr…` | M | M | M |
| 7 | `api_key = abcdefghijklmnopqrstuvwxyz0123…` | M | M | U |
| 8 | `password: abcdefghijklmnopqrstuvwxyz0123…` | M | M | U |
| 9 | `secret = abcdefghijklmnopqrstuvwxyz01234…` | M | M | U |
| 10 | `token: abcdefghijklmnopqrstuvwxyz012345` | M | M | U |
| 11 | `AQ.abcdefghijklmnopqrstuvwxyz01234567890` | U | M | M |
| 12 | `Bearer abcdefghijklmnopqrstuvwxyz012345` | M | M | M |
| 13 | `-----BEGIN PRIVATE KEY-----` | U | U | M |
| 14 | `https://user:pass@example.com/path` | U | U | M (partiel) |
| 15 | `api_key='abcdefghijklmnopqrstuvwxyz012345'` | U | U | M |

Observation : les trois implémentations ne masquent pas le même ensemble de secrets ; `task_queue` et `usage_ledger` sont plus proches, `devkit.exporting` masque les blocs de clé privée et les URLs avec identifiants mais pas les clés `sk_`/`rk_`/`pk_` ni les `key = value` sans guillemets.

## F.4 Écriture de fichier par un outil — confirmation

| ID | Affirmation | Preuve | Statut |
|---|---|---|---|
| F4-1 | Seul `create_analysis_workbook` écrit ; refusé si `allow_writes=False` | `workspace_core.py:1034-1038` | LU |
| F4-2 | Vérifié par session scriptée (lot C) : la création sans autorisation lève `UserFacingError` | `LOT_C` C4 (cas non écrit) | EXÉCUTÉ |
| F4-3 | L'endpoint `/api/actions/report` est le clic de confirmation direct | `come_ai_web.py:701-708` | LU |

## F.5 Démarrage à froid, RSS, imports

| ID | Mesure | Commande | Sortie brute | Statut |
|---|---|---|---|---|
| F5-1 | Démarrage à froid x3 (médiane) | `/usr/bin/time -l … python -c "import come_ai_web"` ×3 | `1,45 / 1,19 / 1,18 s` → médiane `1,19 s` | EXÉCUTÉ |
| F5-2 | RSS max (médiane) | idem | `88 797 184 / 88 670 208 / 88 727 552 octets` → médiane ≈ `88,7 Mo` | EXÉCUTÉ |
| F5-3 | Top 10 imports par temps propre (`python -X importtime`) | `python -X importtime -c "import come_ai_web"` | 1. `fastapi.openapi.models` 121 990 µs ; 2. `career.router` 28 061 µs ; 3. `pydantic_core.core_schema` 18 241 µs ; 4. `pandas._libs.tslibs.fields` 16 296 µs ; 5. `come_ai_web` 12 945 µs ; 6. `fastapi.routing` 12 766 µs ; 7. `openpyxl.styles.builtins` 12 601 µs ; 8. `annotated_types` 11 947 µs ; 9. `fastapi.exceptions` 10 741 µs ; 10. `pydantic.types` 9 823 µs | EXÉCUTÉ |

## F.6 Fichiers frontend servis

| ID | Affirmation | Preuve | Statut |
|---|---|---|---|
| F6-1 | Montage `/static` → `web_static/` (3 fichiers) | `come_ai_web.py:792` | LU |
| F6-2 | Montage `/v5-static` → `v5_static/` (5 fichiers) | `come_ai_web.py:793` | LU |
| F6-3 | Montage `/career-static` → `career_static/` (3 fichiers) | `come_ai_web.py:794` | LU |
| F6-4 | Fichiers servis : `web_static/{app.css,app.js,index.html}` ; `v5_static/{devkit.js,evolution.js,index.html,v5.css,v5.js}` ; `career_static/{career.css,career.js,index.html}` | `find` | EXÉCUTÉ |

## F.7 Incohérences trouvées

1. L'upload (`/api/files/upload`) ne vérifie pas l'en-tête `Origin`, contrairement au chat (`/api/v5/chat`) qui renvoie 403. Incohérence de garde.
2. Les trois `redact_text` ne masquent pas le même ensemble de secrets (F3) ; un secret masqué par l'un peut passer chez l'autre.
3. `devkit.exporting.redact_text` laisse passer les clés `sk_`/`rk_`/`pk_` et les `key = value` sans guillemets, alors que `task_queue`/`usage_ledger` les masquent.
4. Le démarrage à froid importe `pandas`/`openpyxl`/`numpy` lourds (top imports), ce qui explique le RSS de ~88 Mo.

## F.8 Ce que je n'ai pas pu déterminer

- Performance réelle avec données volumineuses (pas de benchmark I/O dans ce lot).
- Comportement des limites de taille sur des corps chunked sans `Content-Length` (le middleware lit le flux, non testé ici).
- Autres frontends ou assets non montés.

Fichiers bruts : `docs/audit_v2/raw/audit_F_http_out.txt`, `audit_F_http2_out.txt`, `audit_F_msg_out.txt`, `audit_F_redact_out.txt`.
LOT_F.md : ce fichier.
EOF
cp /tmp/audit_F_http_out.txt docs/audit_v2/raw/audit_F_http_out.txt
cp /tmp/audit_F_http2_out.txt docs/audit_v2/raw/audit_F_http2_out.txt
cp /tmp/audit_F_msg_out.txt docs/audit_v2/raw/audit_F_msg_out.txt
cp /tmp/audit_F_redact_out.txt docs/audit_v2/raw/audit_F_redact_out.txt
sed -i '' 's#/Users/comedelavenne#~#g; s#/tmp/audit_5ef814e#WORKTREE#g' docs/audit_v2/raw/audit_F_http_out.txt docs/audit_v2/raw/audit_F_http2_out.txt docs/audit_v2/raw/audit_F_msg_out.txt docs/audit_v2/raw/audit_F_redact_out.txt docs/audit_v2/LOT_F.md
wc -c docs/audit_v2/LOT_F.md