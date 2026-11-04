# Rangement NAGe — 4 novembre 2026

## Résultat concret

- Point d'entrée quotidien conservé : `~/Desktop/NAGe.app`, serveur 8765, dépôt `~/AI-Excel-Agent`.
- Neuf éléments techniques retirés du Bureau : quatre dossiers de transmission/rapports, deux ZIP du projet et trois anciens lanceurs. Les deux lanceurs VC autonomes restent exécutables depuis leur archive ; leur code et leur éventuel serveur 8767 sont préservés.
- 500 gabarits `missions_vc_md` retirés du projet actif après comparaison intégrale avec les blobs Git de c9a252b. Ils représentaient 24 corps de texte types après normalisation du numéro de thème, sans contenu pédagogique spécifique vérifié.
- Backup non suivi `desktop_static/app.js.backup` déplacé ; le vrai `app.js` reste intact.
- Quarantaine : `~/Documents/NAGe/Archives/2026-11-04_152145`. Manifeste source/destination, conservation vérifiée des inodes, et script `restaurer.py` qui refuse tout écrasement. Aucune suppression définitive.
- Guide durable : `docs/WORKSPACE.md`, repère utilisateur `~/Documents/NAGe/LISEZ-MOI.md`, emplacement des futurs worktrees `~/Documents/NAGe/Developpement`.
- Navigation de l'application : sortie V3 historique retirée, logo ramenant à l'accueil interne, stages et candidatures conservés. Les routes existantes, assets partagés et modules métier restent présents.

## Git et protection des travaux

Branche dédiée : `codex/nage-workspace-cleanup-20261104`, basée sur le studio `4fe8ceb` puis réconciliée avec le snapshot live `c9a252b`. Pas de modification de main ni de force-push. Les modifications installées du studio ont leur historique sur la branche publiée antérieure.

Inventaire à 15 h 19 : 690 worktrees enregistrés dont 663 existants et 27 signalés prunable ; 2 310 branches locales et 531 références distantes suivies. 2 185 branches locales sont ancêtres de main et 125 ne le sont pas. Cette propriété ne suffit pas à autoriser une suppression : les modifications locales et les dépendances doivent aussi être vérifiées. Aucun worktree ou branche supprimé/déplacé.

La comparaison initiale main/studio montre 262 fichiers uniquement dans main, 239 uniquement dans le studio et 128 modifiés. Certains modules Career de main ne sont pas présents comme fichiers dans le studio ; des contenus VC et éléments visuels suivent la divergence inverse. Ce rangement établit une référence locale utilisable et sauvegardée ; il ne certifie pas une convergence de toutes les fonctionnalités. Toute intégration dans main reste soumise à une validation séparée et à l'accord explicite de Côme.

Les inventaires détaillés sont archivés localement pour conserver les chemins et états sans les exposer dans un rapport distant. Les cours, données locales de révision et profils applicatifs sont préservés.

## Validation exécutée avant publication

```sh
.venv/bin/python -m pytest -q tests/test_v5_web.py tests/test_vc_course.py tests/test_vc_revisions_ui.py tests/test_vc_cases_routes.py
node --check v5_static/v5.js
node --check v5_static/revisions.js
node --check v5_static/vc_studio.js
git diff --check
```

Résultat : **24 passed en 7,08 s**, syntaxe JS et diff-check verts. Tests avec données synthétiques ; suite globale non lancée. Le rangement libère l'espace quotidien sans prétendre récupérer la place disque des centaines de worktrees préservés.
