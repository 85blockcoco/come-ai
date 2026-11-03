# Prompt Codex — Outil d'apprentissage NAGe (à partir de 0, basé sur MES documents)

## Principe
L'utilisateur part de zéro et veut apprendre son cours. L'outil doit être un tuteur fondé UNIQUEMENT sur les documents fournis (PDFs cours). Pas d'examen blanc en premier : d'abord apprentissage guidé, puis consolidation, puis examen.

## Fonctionnalités professeur (à ajouter au pipeline)
- **Mode tuteur conversationnel** : explications pas-à-pas, reformulation, analogies, vérification de compréhension.
- **Quiz adaptatif** : difficulté qui monte selon les scores, feedback immédiat avec correction.
- **Plan de révision personnalisé** : basé sur les lacunes réelles, jour par jour jusqu'à vendredi.
- **Simulateur d'examen** : cas chiffrés type examen avec timer et correction détaillée.
- **Tableau de bord** : % de maîtrise par notion, alertes sur points faibles.
- **Mode "je n'ai pas compris"** : reformulation + exemple + exercice guidé.

## UX (amélioration à fond)
- Interface claire, navigation par chapitre, progression visible.
- Mode sombre/clair, responsive mobile, accessibilité (aria).
- Feedback immédiat, animations légères, skeleton loading.
- Recherche full-text dans le cours et les fiches.
- Raccourcis clavier, mode focus (sans distractions).
- Export PDF des fiches et du plan.
- Offline (SW étendu) pour réviser sans réseau.

- **Ingestion des fiches** : parser `docs/fiches/*.md` dans `career/ingest.py`, exposer via `/career/fiches`, afficher dans `desktop_static/`.

## Pipeline pédagogique (ordre)

1. **Ingestion & structuration** (`career/ingest.py`)
   - Parse PDFs du cours, découpe par chapitre/section, extrait définitions, formules, exemples.
   - Index vectoriel local (RAG) + métadonnées (page, section).
   - Tests : `tests/test_nage_ingest.py`.

2. **Tuteur IA sourcé** (`career/tutor.py`)
   - Réponses uniquement depuis les docs, avec citations (page + extrait).
   - Modes : explication, reformulation, exemple, "explique comme à un débutant".
   - Route `/career/tutor/ask`, `/career/tutor/explain`.

3. **Fiches de synthèse auto** (`career/summary.py`)
   - Génération de fiches par chapitre (définitions, points clés, formules).
   - Export PDF + vue web.

4. **Flashcards SRS** (`career/srs.py`)
   - Cartes auto-générées depuis les docs, révision espacée (SM-2).
   - Routes `/career/srs/due`, `/career/srs/review`.

5. **Quiz progressif** (`career/quiz.py`)
   - Questions générées depuis les docs, difficulté adaptative, feedback immédiat.
   - Pas d'examen blanc avant maîtrise ≥ 80% d'un chapitre.

6. **Plan de révision** (`career/plan.py`)
   - Plan jour par jour jusqu'à vendredi, basé sur la progression réelle.

7. **Examen blanc** (`career/exam.py`) — seulement en phase finale, après consolidation.

## Contraintes
- Aucune réponse hors documents (refuser si hors corpus).
- UI simple, mobile-friendly, offline (SW étendu pour cacher fiches).
- Backend `career/**` (OpenCode), UI `desktop_static/**` (Codex) → coordination.
- Tests ciblés, ruff clean, coût nul.

## Livrable
- Branches `agent/nage-learn-*`, PR vers intégration, rapport `docs/agent-reports/NAGE-LEARN-READY.md`.
