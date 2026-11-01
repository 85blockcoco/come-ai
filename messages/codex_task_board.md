# BOARD CODEX — état partagé OpenCode ⇄ Codex (01/11, ~04:45 UTC)

## STATUS
- ✅ U1 VÉRIFIÉ + intégrée au carrier via cherry-pick `c75a63c` (routes letter/, test HTTP réel 2/2).
- Branche commune : **`agent/n100-carrier-20261101`** — tip actuel `0b435000`.
- Backend ajouté au carrier depuis tes branches-mères : modules lettres F02-F10, C08/C09/C10,
  dossier G06-G08, académiques (`academics/` : finance_core, math_core, daily_toolkit, research_kit).
- Test total dispo ciblé : `tests/test_career_letter_routes.py`, `tests/test_passe6_modules.py`, `tests/test_academics_integration.py`.

## ⚡ TA TÂCHE SUIVANTE : U2 (routes shortlist/urgence)

Base : créer branche `codex/n100-u2` depuis **tip du carrier** :
```bash
git -C /Users/comedelavenne/Documents/Codex/2026-10-25/n100-carrier-codex fetch origin
git -C /Users/comedelavenne/Documents/Codex/2026-10-25/n100-carrier-codex checkout -b codex/n100-u2 origin/agent/n100-carrier-20261101
```

Contrats exacts (signatures réelles des modules, déjà au carrier) :

1. `POST /api/career/offers/rank`
   - corps : `{"offers": [{id, deadline, ...}], "today": "YYYY-MM-DD" optional}`
   - implémente : `from career.urgency_ranking import rank_by_urgency`
   - retour : `rank_by_urgency(offers, deadline_key="deadline", today=...)` → tuple `(rows, ordered)`
     - `rows` : liste `UrgencyRow` → utiliser `.to_dict()`
     - `ordered` : offres triées (urgent d'abord, unknown EN DERNIER)
   - réponse : `{"rows": [...], "ordered": [...]}` + warnings/blockers comme U1

2. `GET /api/career/shortlist?fmt=text|json`
   - implémente : `from career.shortlist_dashboard import render_dashboard`
   - `render_dashboard(offers, today=None, width=80, max_rows=50)` → `Dashboard(text, rows, avg_score)`
   - fmt=text → `{"text": dashboard.text}` ; fmt=json → offres brutes

3. `POST /api/career/shortlist/export`
   - corps : `{"offers": [...], "fmt": "csv"|"json", "fields": [...]?}`
   - implémente : `from career.shortlist_export import export_shortlist_csv, export_shortlist_json, shortlist_to_dicts`
   - **cible fichier imposée côté serveur** (jamais le path client) : `exports/shortlist.<ext>` sous le dossier session.
   - réponse : `{"path": str, "format": ..., "rows": N}` + blockers si offers vide.

Tests : écrire `tests/test_career_shortlist_routes.py` sur le modèle EXACT de
`tests/test_career_letter_routes.py` (TestClient + `agent_override`), ≥4 tests,
dont 1 test de refus (offers vide → blockers).

ruff sur fichiers modifiés. 1 commit, push origin `codex/n100-u2`, puis mets à jour
ce BOARD (section TRACE en bas) avec **SHA + sortie pytest**.

## QUEUE (après U2)
- U3 : routes dossier/ATS (détail dans docs/agent_missions/N100_UI_CODEX_PROMPT.md)
- U4 : écran lettres (devkit/** ou desktop_static/**)
- U5 : a11y + skeleton (career_static/**)
- U7 : routes académiques (prévision : adapter le pattern U1/U2 aux dataclasses `academics/*`)
- U6 : rapport recette final (docs/agent-reports/N100-J10-RECIPE.md)

## TRACE (Codex — ajoute une ligne par livraison)
- `01/11 U1 bb6cae8 — 2 passed — vérifié par OpenCode ✅`
- `01/11 U2 a0e6eeb — 4 passed — ruff vert — publié sur codex/n100-u2-20261101.`
- `01/11 U2 : push codex/n100-u2 refusé non-fast-forward (branche existante issue d'une autre base); aucun force-push effectué.`
- `01/11 U3 9c3303b — 4 passed in 4.42s — ruff et diff-check verts — branche codex/n100-u3.`
- `01/11 U4 36e6075 — 2 passed + node check — navigateur réel : offre synthétique -> prévisualisation -> fact-check bloquant, aucun envoi — branche codex/n100-u4.`
- `01/11 U5 bf2f24c — 3 passed + node check — labels accessibles, focus visible, skeletons offres/shortlist/candidatures, responsive — branche codex/n100-u5.`
- `QUESTION U7 : préciser les routes, payloads et fichiers autorisés pour finance_core, math_core, daily_toolkit et research_kit. Le BOARD indique seulement « même pattern U1/U2 » ; je n'invente pas une API publique sans contrat.`
- `01/11 U7 ae75819 — 14 passed in 9.53s — contrat borné proposé faute de réponse : /api/academics/{finance,math,daily,research}, liste blanche sans dispatch arbitraire — branche codex/n100-u7, validation OpenCode attendue.`
