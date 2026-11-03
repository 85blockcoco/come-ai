# MISSION N100-D04 — Registre de preuves (evidence)

## OBJECTIF
Registre append-only des preuves approuvées par l'utilisateur (facts, chiffres,
expériences). Fondation pour le CV factuel et le claim_check.

## PÉRIMÈTRE
Crée `career/evidence_registry.py` et `tests/test_evidence_registry.py`.

## CONTRAT
- ≥20 cas de test (synthétiques).
- Classes `Evidence`, `EvidenceRegistry` avec `add()`, `list()`, `get()`.
- Append-only : pas de update/delete.
- Hash-chaîné simple (prev_hash) pour détection d'altération.
- Rapport `docs/agent-reports/N100-D04-EVIDENCE_REGISTRY.md`.
- Branche `agent/n100-D04-evidence-registry`.
