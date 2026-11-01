# N100 — J10 Rapport de recette Codex

Date : 2026-11-01  
Périmètre : U1 à U7, données synthétiques uniquement, aucune candidature envoyée.

## 1. Environnement vérifié

- Worktree : `/Users/comedelavenne/Documents/Codex/2026-10-25/n100-carrier-u2-base`
- Base initiale réellement publiée : `5d33f001597b8e7784fb6c7ed53afbccd45a0db1`
- Carrier observé pendant la recette : `99a20691499f71608fd58bbfa7e9594223163ddb`
- Interpréteur : `/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python`
- Serveurs de recette isolés : `127.0.0.1:18950` et `127.0.0.1:18951`, arrêtés après vérification.
- Aucun fichier `.env`, secret, CV réel ou donnée personnelle lu ou ajouté.

## 2. Livraisons

| Lot | Branche | Commit fonctionnel | Résultat |
|---|---|---|---|
| U1 lettres REST | `codex/n100-u1` | `c75a63c876e775169eda59843e57a69501cc0a61` | Vérifié puis intégré au carrier par OpenCode |
| U2 shortlist/urgence | `codex/n100-u2-20261101` | `a0e6eeb37520c4a092860849bb9b4a1b1dcee194` | 4 tests verts, intégration carrier en attente |
| U3 dossier/ATS | `codex/n100-u3` | `9c3303b7d41e6fadc7de8b5f5b59ac03be599105` | 4 tests verts, intégration carrier en attente |
| U4 écran lettres | `codex/n100-u4` | `36e607511cbd0215ed6e8eaca92519aacd20a061` | Tests statiques et navigateur réel verts |
| U5 accessibilité | `codex/n100-u5` | `bf2f24cf5bc2652378419700786197cdf5217fb7` | Tests statiques et navigateur réel verts |
| U7 routes academics | `codex/n100-u7` | `ae7581944226146545facc83c7bf77c081323542` | Contrat borné proposé, 14 tests verts |

## 3. Commande de validation finale

```bash
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q \
  tests/test_e2e_local_pipeline.py \
  tests/test_career_letter_routes.py \
  tests/test_career_shortlist_routes.py \
  tests/test_career_dossier_routes.py \
  tests/test_n100_letter_ui.py \
  tests/test_n100_career_accessibility.py \
  tests/test_academics_routes.py \
  tests/test_academics_integration.py
```

Sortie observée :

```text
................................                                 [100%]
34 passed in 9.51s
```

Contrôles complémentaires réellement exécutés :

```bash
ruff check academics/router.py career/router.py career/service.py come_ai_web.py \
  tests/test_e2e_local_pipeline.py tests/test_career_letter_routes.py \
  tests/test_career_shortlist_routes.py tests/test_career_dossier_routes.py \
  tests/test_n100_letter_ui.py tests/test_n100_career_accessibility.py \
  tests/test_academics_routes.py
node --check desktop_static/app.js
node --check career_static/career.js
git diff --check
```

Résultat : tous verts. La suite pytest complète n'a pas été lancée conformément au protocole de charge.

## 4. Recette des dix offres synthétiques

Le test `tests/test_e2e_local_pipeline.py`, livré par OpenCode au commit `99a2069`, a été repris et rejoué sur la branche cumulative Codex. Il couvre dix offres entièrement synthétiques et le flux backend :

1. qualification de l'offre ;
2. génération de lettre locale ;
3. contrôle factuel ;
4. constitution du kit ;
5. rapport final ;
6. absence d'envoi automatique.

Ce test fait partie des 34 tests verts ci-dessus. Aucune offre réelle ni donnée personnelle n'est utilisée.

## 5. Recette navigateur réelle

### Écran lettres — `/app#applications`

Instance : `http://127.0.0.1:18950/app#applications`

- offre synthétique `Synthetic Bank — Finance Intern` sélectionnée ;
- langue et ton disponibles ;
- lettre prévisualisée dans l'éditeur ;
- vérification factuelle lancée ;
- un blocage factuel affiché ;
- bouton `Approuver` désactivé tant que le blocage subsiste ;
- bouton d'export indisponible avant approbation ;
- aucun envoi déclenché.

### Accessibilité Career — `/career#career/applications`

Instance : `http://127.0.0.1:18951/career#career/applications`

- noms accessibles observés sur les filtres État, Réception et Échéance ;
- case `À traiter seulement` correctement nommée ;
- focus visible et statut local conservés ;
- aucun dépôt ou envoi déclenché.

Les deux serveurs de recette ont été arrêtés après vérification.

## 6. Sécurité et contrôle humain

- aucun endpoint de soumission automatique ajouté ;
- aucun appel réseau dans les nouveaux modules REST ;
- exports shortlist imposés dans le répertoire serveur ;
- export de lettre protégé par le parcours d'approbation humaine dans l'UI ;
- champs ATS préremplis localement, sans soumission ;
- dossier preview en lecture seule ;
- calculs académiques limités à une liste blanche d'opérations ;
- aucun dispatch Python arbitraire ;
- recherche académique conserve les placeholders lorsque les faits manquent.

## 7. Trous connus et risques résiduels

1. U2 à U7 ne sont pas encore intégrées dans `agent/n100-carrier-20261101` ; chaque branche doit être revue puis cherry-pickée dans l'ordre.
2. Le contrat REST U7 n'a pas été fourni par OpenCode. L'implémentation publiée est une proposition bornée à accepter ou ajuster avant intégration.
3. Le parcours navigateur U4 a vérifié le blocage de l'approbation, pas un export positif après résolution de tous les faits.
4. La suite complète n'a pas été exécutée ; la preuve finale porte sur 34 tests ciblés et les validations antérieures documentées.
5. Aucune fusion dans `main`, publication ou déploiement n'a été effectué.
6. Le contournement potentiel par le booléen client `approved` a été corrigé après cette campagne au commit `46abda86e024aea13bf6dccac9ab6164ac4ad654` : tous les formats vérifient désormais le registre serveur et le chemin d'export est imposé côté serveur.

## 8. Ordre d'intégration reproductible

Après revue OpenCode :

```bash
git fetch origin
git cherry-pick a0e6eeb37520c4a092860849bb9b4a1b1dcee194  # U2
git cherry-pick 9c3303b7d41e6fadc7de8b5f5b59ac03be599105  # U3
git cherry-pick 36e607511cbd0215ed6e8eaca92519aacd20a061  # U4
git cherry-pick bf2f24cf5bc2652378419700786197cdf5217fb7  # U5
git cherry-pick ae7581944226146545facc83c7bf77c081323542  # U7, après accord contrat
```

Rejouer ensuite les commandes de la section 3 sur le carrier obtenu. Ne pas fusionner dans `main` sans décision humaine explicite.
