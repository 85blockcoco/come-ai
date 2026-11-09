# Tasks Cycle 002 — Missions Key Clarification

| ID | Priority | Task | Description |
|----|----------|------|-------------|
| T001 | P0 | Modifier `extract_missions` | Add `heading_found` check: return `[]` when no explicit "Missions" section is detected |
| T002 | P0 | Tester le comportement | Vérifier que `extract_missions` retourne `[]` sans section "Missions" explicite |
| T003 | P1 | Valider avec le suite existante | S'assurer que tous les 147 tests passent |
| T004 | P1 | Vérifier `summarize_offer` | Vérifier que le résumé d'offre affiche correctement le'absence de missions |
| T005 | P2 | Documenter le changement | Mettre à jour la spécification avec les critères d'acceptation |

## Definition of Done
- [ ] Code modifié dans `career/cv_quality/missions_extractor.py`
- [ ] Tous les tests existants passent
- [ ] Comportement vérifié manuellement pour les trois cas :
  1. Pas de section "Missions" -> liste vide
  2. Section "Missions:" présente -> missions extraites
  3. Aucune régression sur les tests d'intégration