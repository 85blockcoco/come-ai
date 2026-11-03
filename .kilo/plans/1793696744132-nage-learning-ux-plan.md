# Plan — Continuer le travail NAGe (apprentissage + UX)

## Objectif
Produire le maximum de matériel d'étude et d'améliorations UX pour NAGe pendant ~1h, sans modifier le code source (mode plan).

## Tâches proposées (à exécuter en mode code)
1. Générer des fiches détaillées par notion (T1–T5) avec exemples et références d'examen.
2. Étendre le quiz JSON avec 50+ questions supplémentaires par topic.
3. Ajouter 10 nouveaux cas d'examen chiffrés (cap table, waterfall, down round, convertibles).
4. Créer un index Markdown des fiches et un plan de révision jour par jour.
5. Mettre à jour le prompt Codex pour ingérer les fiches dans `career/` et les afficher dans `desktop_static/`.
6. Ajouter des illustrations/schémas textuels (diagrammes ASCII) dans les fiches.

## Risques
- Volume important : découper en plusieurs batches pour éviter les timeouts.
- Illustrations : pas d'images binaires, utiliser des diagrammes texte.

## Validation
- Fichiers JSON valides (parse Python).
- Fiches Markdown lisibles.
- Prompt Codex à jour.

## Open questions
- Priorité : fiches détaillées vs quiz supplémentaires ? (recommandé : fiches d'abord, puis quiz)
