# N100 — J10 rapport de recette final (02/11/2026)

## Périmètre livré

- **U2** : classement des offres par urgence, shortlist texte/JSON, export
  shortlist à cible serveur.
- **U3** : champs ATS, checklist dossier avec `blockers`, aperçu lecture seule.
- **U4** : atelier lettre multilingue (FR/EN/DE/ES), tons, aperçu modifiable,
  contrôle factuel, approbation humaine, export local.
- **U5** : labels accessibles, focus visible, skeletons, `aria-busy`,
  `prefers-reduced-motion`, responsive mobile.
- **U7** : routes académiques locales bornées (finance, maths, plan du jour,
  plan de recherche), sans dispatch arbitraire ni réseau.
- **CLI `nage.py`** : finance/maths, budget local, plan du jour, brief,
  recherche, méthode de devoirs pas-à-pas.
- **Guide** : `docs/USER_GUIDE_V2.md`.

## Preuves exécutées

Commande finale (02/11) :

```bash
.venv/bin/python -m pytest -q \
  tests/test_e2e_local_pipeline.py \
  tests/test_career_letter_routes.py \
  tests/test_career_shortlist_routes.py \
  tests/test_career_dossier_routes.py \
  tests/test_n100_letter_ui.py \
  tests/test_n100_career_accessibility.py \
  tests/test_academics_routes.py \
  tests/test_academics_integration.py \
  tests/test_nage_cli.py \
  tests/test_urgency_shortlist.py
```

Résultat : **56 passed in 12.92s** (exit 0).

Lint :

```bash
.venv/bin/python -m ruff check nage.py tests/test_nage_cli.py
# All checks passed!
```

JavaScript :

```bash
node --check desktop_static/app.js
node --check career_static/career.js
```

Serveurs locaux :

- `http://127.0.0.1:8765/` → **200**
- `http://127.0.0.1:8766/` → **200**

Routes vérifiées en direct :

```bash
curl -s -X POST http://127.0.0.1:8765/api/career/offers/rank \
  -H 'Content-Type: application/json' \
  -d '{"offers":[{"id":"a","deadline":"2026-11-03"},{"id":"b"}],"today":"2026-11-01"}'
# ordered = ["a","b"] : deadline connue d'abord, inconnue en dernier

curl -s -X POST http://127.0.0.1:8765/api/academics/finance/calculate \
  -H 'Content-Type: application/json' \
  -d '{"operation":"future_value","arguments":{"pv":100,"rate":0.1,"periods":2}}'
# result = 121.00000000000001
```

## Preuve HTTP réelle (instance jetable 8799)

Une instance `create_app(tmp_path)` a été lancée avec uvicorn sur un dossier
temporaire, puis testée par `curl` (vrai socket HTTP, aucune donnée perso) :

| Scénario | Résultat |
|---|---|
| Lettre rendue puis contrôlée | `200`, corps de 210 caractères |
| Approbation humaine | `200`, `approved: true` |
| Export avec `target: /tmp/evil-client-path.md` | `200`, `ok: true`, fichier écrit sous `<tmp>/career_data/exports/live-http-test.md` ; `/tmp/evil-client-path.md` **absent** |
| Export sans approbation avec `approved: true` | `200`, `ok: false`, `blockers: ["export bloqué : lettre non approuvée par un humain"]` ; `/tmp/evil2.md` **absent** |
| Dossier banque incomplet | `completeness.ok = false`, blockers `lettre_motivation` + `transcript_english` |
| Classement urgence | `ordered = ["urgent", "unknown"]` (inconnue en dernier) |
| Finance `future_value` | `result = 121.00000000000001` |
| Finance `__import__` | `result = null`, blocker « Opération non autorisée » |
| Export shortlist CSV | écrit sous `<tmp>/career_data/exports/shortlist.csv` |

Correction associée : `days_left` est désormais calculé dans
`career/urgency_ranking.py` (auparavant toujours `null`), avec le test
`test_rank_days_left_is_computed`.

## Vérifications de sécurité

| Exigence | Preuve |
|---|---|
| Le booléen client `approved` ne contourne pas l'approbation | `test_client_approved_flag_cannot_bypass_server_gate` : export refusé malgré `approved: true` |
| Export imposé côté serveur | `test_approved_letter_exports_only_under_server_directory` : le `target` client `/tmp/...` est ignoré, sortie sous `career_data/exports/` |
| Deadline inconnue classée en dernier | `test_rank_orders_unknown_deadline_last` + E2E |
| Dossier incomplet → `blockers` | `test_dossier_checklist_missing_required_is_blocked` |
| Aucun envoi automatique | aucun appel SMTP/formulaire dans le diff ; l'export est une écriture locale |
| Aucun dispatch académique arbitraire | `test_arbitrary_function_dispatch_is_refused` (`__import__` refusé) ; opérations listées explicitement |
| Pas de données personnelles dans le dépôt | CLI : ledger par défaut sous `~/.nage/` ; tests sur `tmp_path` |
| Pas de réseau dans les routes académiques | imports limités aux modules locaux `academics/*` |

## Intégration

- Candidate Codex : `codex/n100-consolidated-20261101` @ `a9f8226`
  (base `99a2069`).
- Merge carrier : `0aa7224`, déduplication U2 : `bd07d64`, board : `9806f9e`.
- Aucun force-push, aucun merge dans `main`.

## Limites connues (assumées)

1. **J04 PWA hors-ligne** : non implémentée. L'app est déjà locale ; une PWA
   sans serveur local n'apporte pas de valeur et pourrait masquer des données
   personnelles. Décision humaine requise.
2. **Registre d'approbation lettre** : volontairement fail-closed et en mémoire
   du processus. Après redémarrage du serveur, une lettre doit être ré-approuvée
   avant export (comportement sûr, pas de contournement).
3. **Recette HTTP réelle** : les tests utilisent `TestClient` (in-process) ; les
   routes ont aussi été vérifiées en direct sur le serveur 8765.

## Verdict

Recette J10 **acceptée** pour le périmètre U2–U5/U7 + CLI. Le dépôt reste à
**99/100** missions N100 ; seule J04 reste ouverte pour décision humaine.
