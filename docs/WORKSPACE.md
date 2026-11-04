# NAGe — repères de travail

## Application quotidienne

Ouvrir **NAGe.app** sur le Bureau. L'accueil et l'onglet **Revision** utilisent le serveur local `http://127.0.0.1:8765`. Le dépôt utilisé par le lanceur est `~/AI-Excel-Agent` ; ne pas le déplacer pendant qu'une migration des chemins n'a pas été validée.

La référence de cette installation est la branche `codex/nage-workspace-cleanup-20261104`. Elle reprend le studio de révision publié sur `codex/vc-learning-studio-20261104`, réconcilie le commit `c9a252b` sans conserver ses 500 gabarits dans l'arbre actif, et retire la navigation vers l'ancienne interface V3. Le module stages reste disponible dans la même installation.

**Cette référence locale validée n'est pas encore main.** Au contrôle du 4 novembre 2026, main et le studio suivent deux lignées divergentes. Une comparaison des arbres identifie aussi des modules Career présents dans main et absents comme fichiers du studio. Leur convergence nécessite une intégration séparée, des tests et l'accord de Côme ; aucune équivalence globale n'est présumée.

## Où sont les éléments à conserver ?

| Élément | Emplacement |
|---|---|
| Application du Bureau | `~/Desktop/NAGe.app` |
| Code exécuté | `~/AI-Excel-Agent` |
| Cours originaux, inchangés | `~/Desktop/EDHEC COURS/VENTURE CAPITAL` |
| Progression VC | `~/.nage/vc` |
| Profil de la fenêtre de l'application | `~/Library/Application Support/NAGE/window` |
| Sauvegardes d'installation | `~/Library/Application Support/NAGE/backups` |
| Quarantaine récupérable du rangement | `~/Documents/NAGe/Archives` |
| Nouveaux worktrees de développement | `~/Documents/NAGe/Developpement` |

Les anciens lanceurs VC sont conservés en quarantaine, avec leurs chemins d'origine dans un manifeste. Leur code reste dans le dépôt ; le serveur distinct éventuel sur 8767 n'est ni supprimé ni arrêté par ce rangement.

## Continuer sans recréer le désordre

1. Garder un seul raccourci NAGe sur le Bureau. Ne pas y créer de copies du dépôt, de rapports ou de lanceurs de test.
2. Lire `COORDINATION.md`, l'état Git et les notes des agents avant de choisir une mission. Ne pas éditer simultanément les mêmes fichiers.
3. Créer les nouveaux worktrees sous `~/Documents/NAGe/Developpement/<mission>` à partir de la référence convenue. Les anciens restent à leurs chemins tant que leurs changements, dépendances et processus n'ont pas été vérifiés.
4. Exécuter les tests ciblés, `git diff --check`, puis pousser les commits vérifiés sur une branche dédiée. Ne jamais annoncer un test collecté comme réussi.
5. Vérifier le même serveur que l'icône pour les livraisons utilisateur. Ne pas confondre un serveur de recette sur un autre port avec l'application quotidienne.
6. Garder les données et les supports personnels hors Git. Ne pas lire les fichiers `.env` ou publier les journaux de runtime pour un simple contrôle.
7. Archiver hors du Bureau les anciens rapports et points d'entrée. Avant toute suppression définitive, suppression de branche/worktree ou fusion dans main, présenter la liste et obtenir l'accord explicite demandé par Côme.

Les 500 fichiers `missions_vc_md` étaient des gabarits répétés, sans contenu pédagogique spécifique vérifié. Leur copie exacte est conservée dans la quarantaine et dans l'historique Git (`c9a252b`). Ils ne doivent pas être réimportés comme des leçons approuvées.
