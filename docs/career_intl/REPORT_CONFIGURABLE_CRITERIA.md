# Rapport — critères Career configurables

Date : 18 octobre 2026

Branche isolée : `codex/configurable-search-criteria`

Point de départ fonctionnel : `800a5fb8b845ddfb017d441c5f3a608309f4e14b` (`night-W3-done`)

`main` observé et non modifié : `5ef814eb16f3357264624abdf0b8fd746315b7b1`

## Résultat livré

- Cases à cocher Stage, CDD, CDI et VIE, toutes sélectionnées par défaut.
- Cases janvier à décembre, avec janvier, février et mars sélectionnés par défaut.
- Raccourci « premier trimestre » qui sélectionne ou désélectionne janvier à mars sans modifier les autres mois.
- Durée minimale d'un stage enregistrée, six mois par défaut.
- Trois statuts conservés : `conforming`, `non_conforming`, `to_verify`.
- Absence de date, absence de durée d'un stage, type ambigu ou période insuffisamment précise : jamais promu automatiquement en offre conforme.
- Date limite passée, annonce clôturée, début passé, contrat ou mois non sélectionné : non conforme.
- Critères persistés localement, renvoyés par l'API, réutilisés par les connecteurs, le classement et la liste d'offres.
- Préférence distincte sur le niveau demandé : Bachelor/M1 prioritaire, M2 conservé, niveau absent ou ambigu à vérifier. Elle ne déclare ni diplôme ni note du candidat.
- Provenance affichée pour le type de contrat, le début, la durée et l'exigence académique lorsqu'un passage source est disponible.

Les contrats sélectionnés sont évalués avant la limite de résultats. Les compteurs d'exploration signifient désormais : offres conformes, offres à vérifier et offres exclues selon les critères enregistrés. Les valeurs inconnues ne sont pas transformées en faits.

## Développement piloté par les régressions

Le premier jeu de régressions ajouté a exposé huit défauts réels : perte de provenance du contrat, mois d'une date de candidature confondu avec le début, stage court sans date non exclu, critères contractuels personnalisés non reconnus comme configuration, et CDD/CDI/VIE éliminés trop tôt par l'ancien préfiltre. Résultat avant corrections : `8 failed, 18 passed`.

Les corrections ont ensuite été appliquées au parseur de faits, aux connecteurs et au service. Les cas couvrent notamment janvier, février, mars, avril, CDD, CDI, VIE, contrat contradictoire, date ou durée absente, offre expirée, intervalle de durée, plafond « up to », provenance et absence d'invention.

## Commandes réellement exécutées

Environnement commun aux commandes : clés cloud retirées, `HOME=/tmp/codex_home`, bytecode Python désactivé.

### Tests ciblés finaux

Commande :

```text
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q tests/test_career_configurable_contract_criteria.py tests/test_career_offer_qualification.py tests/test_career_discovery_selection.py tests/test_career_exploration.py tests/test_career_public_ats_connectors.py tests/test_career_explorer_regressions.py tests/test_career_stage_hunter.py tests/test_career_education_access.py
```

Sortie réelle :

```text
254 passed in 21.58s
```

### Suite complète

Commande :

```text
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q
```

Sortie réelle :

```text
1071 passed in 61.43s (0:01:01)
```

### Évaluations applicatives

Commande :

```text
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m evals run --target come-ai --strict --no-persist
```

Sortie réelle : exécution `d3d98590f67f`, 14 cas, 13 exécutés et réussis, zéro échec, un cas non pris en charge (`local_model_generation`), zéro appel API déclaré par la cible. Cette évaluation utilise l'application réelle sur des fixtures ; elle ne mesure pas la qualité de sources d'offres en direct.

### Contrôles statiques

`node --check career_static/career.js` et `git diff --check` ont terminé sans erreur.

## Recette navigateur réelle

Le serveur temporaire `scripts/criteria_browser_demo.py` lance l'application réelle sur une base temporaire et un connecteur Greenhouse injecté. Toutes les offres sont explicitement synthétiques, les liens utilisent `.test`, les clés cloud sont absentes et les connexions réseau sortantes sont bloquées au niveau socket. Aucun serveur existant n'a été redémarré.

Parcours observé dans le navigateur :

1. Les quatre contrats, janvier à mars, six mois et la préférence Bachelor/M1 puis M2 sont visibles par défaut.
2. L'exploration de sept annonces fictives garde six offres conformes : stages janvier, février et mars, CDD février, CDI mars et VIE janvier. Le stage d'avril est exclu.
3. Les cartes affichent le type exact, le mois et l'année provenant du passage source, la durée du stage et le passage académique cité.
4. Le raccourci premier trimestre a désélectionné janvier à mars ; avril seul a été enregistré, puis retrouvé après rechargement.
5. La recherche relancée avec avril seul a conservé exactement le stage d'avril.
6. Les critères par défaut ont été restaurés et leur persistance vérifiée après rechargement.

Cette recette prouve le parcours local avec des données synthétiques. Elle ne prouve ni la couverture, ni la fraîcheur, ni la disponibilité actuelle de sources Internet réelles.

## Confidentialité et limites

- Aucun document privé, profil réel, base utilisateur ou secret n'a été ouvert.
- Aucun fournisseur IA et aucune source externe n'ont été appelés pour ce lot.
- Les fichiers de garde de consentement et de masquage n'ont pas été modifiés.
- La préférence académique est explicative et souple ; l'admissibilité réelle reste à vérifier sur l'annonce et selon le profil approuvé.
- La livraison reste isolée de `main` tant qu'une revue d'intégration n'a pas accepté la pile W2/W3 dont elle dépend.

## Rejouer et revenir en arrière

Lancer la démonstration synthétique depuis ce worktree :

```text
env -u GEMINI_API_KEY -u GOOGLE_API_KEY -u OPENROUTER_API_KEY -u COME_AI_MEMORY_DIR HOME=/tmp/codex_home PYTHONDONTWRITEBYTECODE=1 /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m scripts.criteria_browser_demo --port 8916
```

Puis ouvrir `http://127.0.0.1:8916/career#career/stagehunter`.

Pour revenir au jalon précédent sans supprimer de travail, utiliser le worktree W3 ou créer un nouveau worktree depuis le tag `night-W3-done`. Aucun reset destructeur n'est nécessaire.
