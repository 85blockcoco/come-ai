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

## Contrôles complémentaires et identité

Les 663 worktrees existants ont ensuite été vérifiés : 635 avec changements visibles, 28 propres dans le périmètre inspecté, zéro conflit d'index, zéro timeout. Les 27 répertoires manquants sont signalés sans prétendre les avoir inspectés. Aucune suppression de branche/worktree n'est déduite automatiquement de ces résultats.

Le dépôt exécuté a été aligné sur la branche cleanup après comparaison de l'arbre Git complet et commit de sauvegarde sur `archive/nage-desktop-pre-alignment-20261104` (`32a634a`). Les anciens changements de code installés sont ainsi committés ; le répertoire local non suivi `vc/` reste préservé.

Logo actualisé à la demande de Côme : SVG vert néon, motif de lignes sur vert profond, miroir conservé par construction, déclinaisons PNG et ICNS macOS. Ancienne identité conservée dans la quarantaine. Taille en-tête 56 px sur ordinateur / 40 px sur téléphone. Les quatre SVG passent `scripts/nage_intro_check.py` ; 21 tests ciblés ont été rejoués en 6,84 s. Recette navigateur réelle du serveur bureau : accueil → 28 leçons → accueil par le logo, aucune requête d'écriture ni erreur JS, pas de débordement à 390 px après correction des grilles min-content.

Côme a ensuite autorisé explicitement l'intégration dans main. Elle doit conserver le socle Career et les protections de main tout en apportant les révisions et l'identité vérifiées ; l'autorisation ne constitue pas une preuve de compatibilité.
