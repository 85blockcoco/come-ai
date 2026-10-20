# Spec — Carte des offres et tri par correspondance

## Objectif
- Afficher une carte des offres disponibles dans l’interface Career.
- Permettre de trier les offres par correspondance croissante (et décroissante).

## Données déjà disponibles (backend)
- Offres : `city`, `country`, `official_url`, `qualification`, `stage_match.score`.
- Classement existant : `ranking_key` dans `career/exploration.py` (score décroissant en premier).

## Changements front-end proposés (career_static, à faire dans une mission dédiée)
1. `career_static/index.html`
   - Ajouter un conteneur `#stagehunter-map` (carte ou liste par ville).
   - Ajouter un sélecteur de tri : `asc` / `desc` sur le score de correspondance.

2. `career_static/career.js`
   - Fonction `renderStageMap(jobs)` : regroupe par `city`/`country`, affiche un marqueur ou une liste.
   - Fonction `sortStageJobs(jobs, direction)` : trie sur `stage_match.score` (ou `qualification` si absent).
   - Conserver la préférence de tri dans `localStorage` (clé `stagehunter_sort`).

## Contraintes
- Aucun appel réseau supplémentaire.
- Réutiliser les données déjà chargées.
- Ne pas modifier le backend.

## Critères d’acceptation
- La carte affiche au moins la ville et le nombre d’offres.
- Le tri ascendant affiche d’abord les moins bien notées.
- Le choix de tri persiste après rechargement.
