# HANDOFF OpenCode → Codex — 12 missions restantes (29/10 16:05)

État flotte : **71/83 livrées (85,5 %)** · 0 worker actif · 7 échecs bloqués au
retry max (3) · 5 en attente de dépendance · charge machine 121 (trop élevée
pour relancer proprement).

Périmètre transféré : les 12 missions ci-dessous (backend career + specs).
OpenCode garde le superviseur, le registre et l'interface desktop.

## À traiter en premier (aucune dépendance, échouées 3× — probablement mal cadrées)

| # | Mission | Dernier échec |
|---|---|---|
| 39 | SPEC-009 — Browser E2E Tests Career | retry 3 |
| 66 | SPEC-031 — Minage FAQ sectorielle des offres | retry 3 |
| 70 | SPEC-035 — Journal d'audit des décisions | retry 3 |
| 71 | SPEC-036 — Bilan hebdo & objectifs | retry 3 |
| 73 | SPEC-038 — Connecteurs ATS banques (Workday/Greenhouse/SuccessFactors) | retry 3 |
| 74 | SPEC-039 — Ingestion email locale IMAP (réponses recruteur) | retry 2 |
| 77 | SPEC-042 — Auditeur de qualité de dossier (anti-sur-promesse) | retry 1 |

## Chaînes de dépendances (ne se débloquent que dans cet ordre)

- #39 → débloque #51 (SPEC-016 Automatisation contrôlée)
- #66 → débloque #68 (SPEC-033 Variantes traduites EN/DE/ES)
- #66 + #70 → débloquent #72 (SPEC-037 Briefing J-1)
- #77 → débloque #79 (SPEC-044 Instrumentation E2E 10 offres) → #80 (SPEC-045 Boucle d'apprentissage)

## Règles reprises de COORDINATION.md

1. `pytest -q tests/test_<zone>.py` uniquement — jamais la suite complète.
2. Branche poussée avant tout « fini » ; pas de merge sur `main` sans go de Côme.
3. `missions_registry.json` reste écrit par OpenCode : **signale-moi chaque
   livraison**, je marque `done` après vérif branche + tests.
4. Pas de données personnelles dans le dépôt, aucune soumission automatique.

## Comment signaler une livraison

Déposer `messages/codex_mission_<n>.md` avec : n°, branche, commit, tests
exécutés + résultats. OpenCode rejoue les tests ciblés puis passe le statut.
