# Prompt Codex — clôture et push de `codex/v3-stable-consolidation`

Contexte : le worktree `~/Documents/Codex/2026-10-25/codex-op-ration-v3-stable-consolidation/candidate-worktree`
contient `25bec6d` (perf dedup) et `2bc9d57` (docs evidence). La branche n'est **pas** sur origin.
La flotte a déjà livré et vérifié les missions 60, 61, 62, 63.

Objectif, dans cet ordre, et rien d'autre :

1. Termine la validation en cours. Si un test échoue, corrige la cause — ne désactive, ne skip, n'assouplis aucun test.
2. Commit final (message conventionnel, un seul sujet).
3. Pousse la branche : `git push -u origin codex/v3-stable-consolidation`
4. Prouve-le dans ta réponse :
   - `git ls-remote --heads origin codex/v3-stable-consolidation`
   - `git log --oneline -3 origin/codex/v3-stable-consolidation`
   - le résultat brut de la suite (passed/failed/skipped + durée)
5. Rapport final, 10 lignes max : SHA, tests, durée, fichiers changés, risques, ce qui reste hors périmètre.

Contraintes :
- Ne touche pas `main`, ne merge pas, ne force-push pas, pas de `git reset --hard`.
- Aucune donnée personnelle (email, téléphone, adresse, nom de recruteur) dans le dépôt.
- Si un rouge résiste > 15 min : commit, pousse, et écris-le noir sur blanc dans le rapport. Aucun statut vert sans preuve.
- Ne modifie pas les fichiers hors de ton périmètre (pas de scripts de flotte, pas de `missions_registry.json`).
