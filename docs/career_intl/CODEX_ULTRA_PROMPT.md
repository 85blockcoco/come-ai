# CODEX ULTRA-PROMPT — Rendu final Career (usage réel satisfaisant)

Tu es Codex. Tu travailles seul, sans réponse humaine. Tu es le garant final de
l'intégration, de la validation et de l'absence de régression avant acceptation
dans `main`.

## 0. Contexte et base de travail
- Répertoire de travail : `/Users/comedelavenne/AI-Excel-Agent`
- Branche courante : `audit/total-v3-2026-10-14` @ `5ef814e` + modifications de travail (non committées)
- Python : `.venv/bin/python` (3.12)
- État initial vérifié : **1111 tests passent**, 0 échec, 0 erreur de collecte.
- Rapport de préparation : `CODEX_READY.md` (racine) — à lire en premier.
- Handoffs : `HANDOFF_AGENT_CODEX.md`, `HANDOFF_AGENT_CAREER.md`, `HANDOFF_AGENT_STUDY_COACH.md`, `HANDOFF_AGENT_MEMOIRE.md`, `HANDOFF_consent_guard.md`.

## 1. Objectif final
Transformer les briques existantes en un outil Career **utilisable et satisfaisant** en usage réel :
- Carte des offres + tri par correspondance (asc/desc) persistant.
- Fiche détaillée offre par offre avec navigation précédent/suivant.
- Résumé IA structuré avec consentement cloud explicite (fallback local si refus).
- Maximum d'informations par offre : missions, prérequis, dates, pertinence, lien officiel.
- Sources étendues et bornées (21 sources publiques vérifiées).
- Zéro donnée personnelle réelle, zéro secret, zéro régression.

## 2. Périmètre — chemins autorisés
- `career_static/index.html`, `career_static/career.js`
- `career/application_prep.py`, `career/application_studio.py`
- `career/service.py`, `career/router.py`
- `career/exploration.py`, `career/source_registry.py`
- `career/connectors/public_ats.py`, `career/discovery.py`
- `consent_guard/*` (lecture ; ne pas modifier la logique du garde-fou)
- `study_coach/*` (lecture ; ne pas modifier la logique)
- `tests/test_career_*.py`, `tests/test_consent_guard_*.py`, `tests/test_study_coach_*.py`
- `docs/career_intl/agents/REPORT_CODEX_ULTRA.md` (nouveau, à créer)
- `CODEX_READY.md` (mise à jour autorisée)

## 3. Interdits (non négociables)
- Aucun vrai CV, e-mail, téléphone, profil personnel, base réelle.
- Aucun merge/push/rebase/stash/clean/prune sur `main`.
- Aucun `git reset --hard`, force-push.
- Aucun skip/xfail/test supprimé.
- Aucune invention de fait dans les résumés IA.
- Aucun appel cloud réel sans consentement explicite.
- Ne pas modifier la logique de `consent_guard/` ni de `study_coach/` (déjà validés).
- Ne pas toucher à `main` sans validation complète.

## 4. État des lots (déjà intégrés — ne pas refaire)
| Lot | État | Preuve |
|---|---|---|
| Career Stage Hunter + sources publiques | Intégré | 327 tests career verts |
| Career MEGA (carte, tri, fiche, résumé IA) | Intégré | `summarize_offer`, endpoints summary, UI |
| Consent Guard | Intégré + câblé | 185 tests verts, `consent_guard/` présent |
| Study Coach | Intégré (modules) | 18 tests verts, `study_coach/` complet |
| Live source check | Vérifié | 21/21 sources, 0 échec |

## 5. Lots restants NON intégrés (hors périmètre — ne pas toucher)
- Mémoire (`feature/nemotron-memory`) : cassée, rebase requis.
- Profil personnel (`feature/profile-integration-v1`) : régression.
- Step 5 (`feature/step5-intelligence-centrale`) : commits non intégrés, suppression de tests.
- Catalogue Career (`feature/career-sources-overnight`) : probablement absorbé.

## 6. Tâches de validation (à exécuter dans cet ordre)

### 6.1 Pré-vol (obligatoire, avant toute modification)
```bash
cd /Users/comedelavenne/AI-Excel-Agent
.venv/bin/python -m pytest -q                          # attendu : 1111 passed
.venv/bin/python -m py_compile come_ai_web.py hybrid_chat.py career/service.py career/router.py career/application_prep.py
PYTHONPATH=/Users/comedelavenne/AI-Excel-Agent .venv/bin/python scripts/live_source_check.py  # 21/21
.venv/bin/python -c "from come_ai_web import create_app; print('IMPORT OK')"
node --check career_static/career.js
```

### 6.2 Vérification fonctionnelle UI (navigateur)
- Ouvrir `/career`, lancer une exploration.
- Vérifier la carte `#stagehunter-map` affiche villes + compteurs.
- Vérifier le sélecteur de tri asc/desc fonctionne et persiste (`localStorage` clé `stagehunter_sort`).
- Cliquer "Détail" sur une offre : fiche complète (lieu, dates, missions, prérequis, pertinence, lien cliquable).
- Navigation précédent/suivant fonctionne.
- Cliquer "Résumé IA (consentement cloud)" : confirmation → appel POST mode=ai avec consentement → affichage ou fallback local.

### 6.3 Vérification consentement (tests)
```bash
.venv/bin/python -m pytest -q tests/test_consent_guard_*.py   # 185 passed
```
Ordre d'évaluation des refus : `consent_unknown` → `consent_revoked` → `envelope_mismatch` → `consent_expired` → `consent_exhausted`. Correspondance examinée avant l'état.

### 6.4 Vérification Study Coach (tests)
```bash
.venv/bin/python -m pytest -q tests/test_study_coach_*.py     # 18 passed
```
Invariant : `document.text[char_start:char_end] == SourceRef.excerpt` (vérifié par `matches_text()`).

### 6.5 Vérification secrets
```bash
git ls-files | grep -iE '\.env$|\.db$|secret|key|token|password' | grep -v test_hybrid_secret_guards
# attendu : vide
```

### 6.6 Empreinte DevKit
```bash
ls -la .devkit/diagnostics/latest.*   # rapport présent
```

## 7. Critères d'acceptation (mesurables)
- [ ] UI : carte + tri + fiche détaillée + résumé IA avec consentement.
- [ ] Backend : endpoint summary (GET + POST) + consent_guard câblé.
- [ ] Tests verts : ≥ 1111 passed, 0 failed, 0 erreur de collecte.
- [ ] Consent guard : 185 tests verts.
- [ ] Study coach : 18 tests verts.
- [ ] Live source check : 21/21 sources, 0 échec, 0 non interrogée.
- [ ] Rapport avec métriques réelles (aucune donnée personnelle).
- [ ] Zéro secret tracké.
- [ ] Zéro régression (pas de test supprimé, pas de xfail ajouté).

## 8. Métriques live attendues (audit borné)
- Sources interrogées : 21
- Sources réussies : 21
- Sources échouées : 0
- Offres brutes évaluées : ~1774
- Offres retenues : ~45
- Offres conformes (confirmed) : ~23
- Offres à vérifier (uncertain) : ~1059
- Offres exclues : ~692
- Temps total : ~33 s

## 9. Rapport final à produire
Créer `docs/career_intl/agents/REPORT_CODEX_ULTRA.md` avec :
```
STATUT: TERMINÉE
MISSION: CODEX ULTRA — Rendu final Career
## Livré
## Backend
## UI
## Tests
## Métriques live
## Limites
## État Git
```
Mettre à jour `CODEX_READY.md` avec le résultat final.

## 10. En cas d'échec
- Ne pas modifier `main`.
- Ne pas supprimer de tests.
- Documenter l'échec dans `REPORT_CODEX_ULTRA.md` avec la commande et le message d'erreur.
- Conserver les modifications sur la branche courante pour diagnostic.

## 11. Rappel des interdits
- Pas de `git reset --hard`, `clean`, force-push sur `main`.
- Pas de secrets dans le contexte modèle.
- Pas de données personnelles réelles dans les fixtures.
- Pas de validation sans empreinte DevKit à jour.
- Pas de skip/xfail/test supprimé.

---
Fin du prompt. Exécute les étapes dans l'ordre, produis le rapport, et valide.