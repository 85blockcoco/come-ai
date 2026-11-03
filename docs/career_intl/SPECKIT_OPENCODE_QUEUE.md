# Spec Kit → OpenCode Go queue

## État de consolidation (2026-10-25)

Les quatre contributions Career de cette file sont déjà intégrées dans la candidate `codex/v3-stable-consolidation`; ce ne sont pas des missions OpenCode Go exécutées pendant cette session. Les modules et validations ciblés sont :

| Mission | État dans la candidate | Preuve ciblée |
|---|---|---|
| OCG-SK-01 — Confiance des sources | Intégrée dans `career/source_trust.py` | `tests/test_source_trust.py` — 66 passés |
| OCG-SK-02 — Dates et échéances | Intégrée dans `career/offer_dates.py` | `tests/test_offer_dates.py` — 270 passés |
| OCG-SK-03 — Profil ↔ prérequis | Intégrée dans `career/requirements_fit.py` | `tests/test_requirements_fit.py` — 499 passés |
| OCG-SK-04 — Couverture des sources | Intégrée dans `career/source_coverage.py` | `tests/test_source_coverage.py` — 30 passés |

Ces validations sont synthétiques et hors ligne. Aucun CV personnel, modèle externe ou appel de source live n’a été utilisé. Aucun dispatch OpenCode Go n’a été effectué : cette session ne fournit pas d’outil OpenCode Go et le Dev Kit du dépôt ne déclare actuellement que les providers locaux Ollama et distants Gemini/OpenRouter avec contrôles de prix. La file reste comme plan de provenance, pas comme preuve d’exécutions déléguées.

Use one isolated worktree per task from the reviewed release candidate.  Each
agent must run the Spec Kit sequence `specify → plan → tasks → implement`, add
tests before production code, commit its work, and report exact test commands.
No task may edit another task's files, call a paid model, read personal files or
merge into `main`.

## OCG-SK-01 — Official source trust

Create `career/source_trust.py` and dedicated tests.  Decide whether an offer
URL is an official employer/ATS source using connector identity, canonical
host rules and explicit registry evidence.  Never equate a metadata boolean
with proof.  Return `verified`, `unverified` or `contradictory`, with reasons.
Include Greenhouse, Lever, Ashby and SmartRecruiters synthetic cases, redirects
represented as fixtures, lookalike domains and missing URLs.  No live network.
Do not modify qualification or UI files.

## OCG-SK-02 — Date and deadline evidence

Create `career/offer_dates.py` and dedicated multilingual fixtures/tests.
Extract publication, application deadline, start month/year and explicit date
ranges separately, each with exact quote and source field.  Detect conflicts
between structured fields and text.  Never turn a deadline into a start date,
never invent a day, and keep ambiguous numeric dates unknown.  Cover French,
English, German, Italian and Spanish.  Do not modify persistence or UI files.

## OCG-SK-03 — Prerequisite-to-profile fit

Build an adapter above the existing `career/offer_requirements/` contract in a
new module `career/requirements_fit.py`.  Compare only approved, synthetic
profile facts against sourced required/preferred criteria.  Return satisfied,
missing, contradictory and unknown groups with evidence IDs.  A missing fact
is not a failed requirement.  Add adversarial tests for Bachelor/M1/M2,
languages, work authorization, graduation dates and years of experience.  Do
not modify the extractor or candidate profile storage.

## OCG-SK-04 — Coverage and health evidence

Create a read-only aggregator `career/source_coverage.py` over existing source
health records and connector results.  Report sources attempted/succeeded,
unique employers, exact offers before/after deduplication, verified official
offers, geography-known offers and qualification-status counts.  Keep live and
synthetic metrics in separate namespaces.  Add tests only with synthetic data;
never inflate counts or perform a network call.

## Acceptance shared by every task

- The feature spec contains measurable criteria and explicit non-goals.
- Unknown remains unknown; provenance survives transformations.
- Targeted tests and the complete suite pass with zero new skip/xfail.
- `git diff --check` and syntax checks pass.
- The report distinguishes unit fixtures, application-level execution and any
  unverified live behavior.
- The branch is committed and left unmerged for Codex review.
