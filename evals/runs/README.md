# Exécutions de démonstration

Ces rapports ont été produits par de **vraies exécutions** du runner dans ce
worktree, le 13 octobre 2026, avec la cible simulée fournie.

| Fichier | Ce qu'il démontre |
|---|---|
| `demo_1_cible_simulee.md` | Le runner charge les 60 cas, exécute 49 cas, marque 11 comme non pris en charge, mesure durée et mémoire. |
| `demo_2_injection_fautes.md` | Avec une faute injectée (`wrong_answer`), 26 cas tombent : la détection fonctionne. |
| `demo_3_comparaison_regressions.md` | `compare` signale les 26 régressions entre les deux runs. |
| `*.json` | Runs bruts utilisés pour la comparaison (schéma `come-evals-run/1`). |

⚠️ Ces exécutions utilisent une **cible simulée** : elles valident le
laboratoire (runner, détection, métriques, comparaison) et ne mesurent
**aucune** qualité de modèle IA réel. Les nouvelles mesures de services réels
se trouvent séparément sous `.devkit/evals/runs/` ; voir `../README.md`.

# Archives simulées — ne pas utiliser comme mesure de Côme AI

Ces fichiers sont conservés tels que livrés par OpenCode. Ils proviennent de
cibles simulées de la version initiale du laboratoire. Le résultat 49/49 valide
la cible idéale et le runner, pas les services ou modèles de Côme AI. Les anciens
libellés de coût, de mémoire et de score ne constituent pas des mesures actuelles.
Les nouvelles preuves sont sous `.devkit/evals/runs/` avec provenance explicite.
