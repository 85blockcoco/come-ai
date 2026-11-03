# Prompt Codex — Améliorations NAGe pour examen (carte blanche)

## Objectif
Maximiser la préparation d'ici vendredi : de 0 à examen blanc chronométré + révision ciblée + tuteur IA sourcé.

## Fonctionnalités à implémenter (priorité)

1. **Mode examen blanc** (`career/exam.py` + route `/career/exam`)
   - Génération d'un examen à partir des chapitres sélectionnés (QCM + exercices).
   - Timer, barème, correction détaillée, score final, export PDF.
   - Tests : `tests/test_nage_exam.py`.

2. **Spaced repetition (SRS)** (`career/srs.py`)
   - Cartes de révision avec intervalles SM-2, rappels quotidiens.
   - Endpoint `/career/srs/due`, `/career/srs/review`.
   - Tests : `tests/test_nage_srs.py`.

3. **Tableau de bord progression** (`career/dashboard.py` + UI)
   - Progression par chapitre, score moyen, points faibles, alertes "non maîtrisé".
   - Route `/career/dashboard`.

4. **Tuteur IA sourcé (RAG)** (`career/tutor.py`)
   - Ingestion PDFs du cours, réponses avec citations (page + extrait).
   - Route `/career/tutor/ask`.

5. **Export PDF fiches** (`career/export.py`)
   - Fiches de synthèse + plan de révision jour par jour jusqu'à vendredi.

6. **Offline (déjà posé)** : étendre le SW pour cacher les fiches générées (pas les données perso).

## Contraintes
- Fichiers réservés Codex : `desktop_static/**`, `devkit/**` → coordination OpenCode pour backend `career/**`.
- Tests ciblés uniquement, ruff clean, pas de force-push.
- Modèles coût nul uniquement.

## Livrable
- Branches `agent/n100-exam-*`, PR vers `codex/main-integration-20261103`, tests verts.
- Rapport `docs/agent-reports/NAGE-EXAM-READY.md` avec score simulé et plan J-1.
