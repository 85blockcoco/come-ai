# CODEX READY — État de préparation (préparé pour validation finale)

Date : 2026-10-18
Branche courante : `audit/total-v3-2026-10-14` @ `5ef814e` + modifications de travail
Python : `.venv/bin/python` (3.12)

## 1. État des tests (suite complète)
- Commande : `.venv/bin/python -m pytest -q`
- Résultat : **1111 passed, 0 failed, 0 errors** (durée ~59 s)
- Sous-suites vertes :
  - `tests/test_career_*.py` : 327 passed
  - `tests/test_consent_guard_*.py` : 185 passed
  - `tests/test_study_coach_*.py` : 18 passed (citations + v3 validation)
  - `tests/test_hybrid_*.py`, `tests/test_come_ai_v3.py`, etc. : verts

## 2. Lots intégrés dans ce worktree (prêts pour Codex)
| Lot | Statut | Preuve |
|---|---|---|
| Career — Stage Hunter + sources publiques | Intégré (staged) | 327 tests career verts |
| Career — MEGA (carte, tri, fiche détaillée, résumé IA) | Intégré (modifs non committées) | `summarize_offer`, endpoints `/api/career/jobs/{id}/summary`, UI `#stagehunter-map`/`#stagehunter-detail` |
| Consent Guard | Intégré (staged + câblé dans `CareerService`) | 185 tests consent_guard verts, `consent_guard/` présent |
| Study Coach | Intégré (modules copiés depuis `feature/study-coach-v1`) | 18 tests study_coach verts, `study_coach/` complet |

## 3. Modifications de travail non committées (à valider)
- `career/application_prep.py` : +`summarize_offer`
- `career/router.py` : +`JobSummaryPayload`, `GET`/`POST /api/career/jobs/{job_id}/summary`
- `career/service.py` : init `consent_guard`, +`get_job_summary`/`summarize_job`
- `career_static/career.js`, `career_static/index.html` : carte, tri, fiche détaillée, résumé IA
- `study_coach/*` : modules copiés (sauf `syllabus.py` conservé dans sa version stable de branche)

## 4. Commandes de pré-vol (à exécuter par Codex)
```bash
cd /Users/comedelavenne/AI-Excel-Agent
.venv/bin/python -m pytest -q                          # attendu : 1110 passed
.venv/bin/python -m py_compile come_ai_web.py hybrid_chat.py career/service.py career/router.py career/application_prep.py
PYTHONPATH=/Users/comedelavenne/AI-Excel-Agent .venv/bin/python scripts/live_source_check.py  # attendu : 21/21 sources
.venv/bin/python -c "from come_ai_web import create_app; print('IMPORT OK')"
```

## 5. Lots restants NON intégrés (hors périmètre de cette préparation)
- **Mémoire** (`feature/nemotron-memory`, base `1b570dd`, cassée) : import cassé, endpoints dupliqués. Nécessite rebase + décision source de vérité. Ne pas intégrer sans travail dédié.
- **Profil personnel** (`feature/profile-integration-v1`, base `ed8a6b9`) : régression (supprime le code career). Ne pas intégrer tel quel.
- **Step 5 intelligence centrale** (`feature/step5-intelligence-centrale`) : 2 commits non intégrés. À évaluer séparément.
- **Catalogue Career** (`feature/career-sources-overnight`) : probablement déjà absorbé ; vérifier avant merge.

## 6. Fichiers clés à inspecter pour le rendu final
- `career_static/index.html`, `career_static/career.js`
- `career/service.py` (section `get_job_summary`)
- `career/router.py` (endpoints summary)
- `consent_guard/` (package complet + tests)
- `study_coach/` (package complet + tests)
- `docs/career_intl/agents/REPORT_MEGA.md` (métriques live)

## 7. Interdits rappelés
- Pas de `git reset --hard`, `clean`, force-push sur `main`.
- Pas de secrets dans le contexte modèle.
- Pas de données personnelles réelles dans les fixtures.
- Pas de modification de `main` sans validation complète.

## 8. Critères d'acceptation du rendu final (Codex)
- UI : carte + tri + fiche détaillée + résumé IA avec consentement.
- Backend : endpoint summary + consent_guard câblé.
- Tests verts (≥ 1110 passed).
- Rapport avec métriques réelles (aucune donnée personnelle).
- Live source check : 21/21 sources, 0 échec.