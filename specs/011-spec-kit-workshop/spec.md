# Spec Kit de développement dans l’Atelier NAGE

Date : 31 octobre 2026. Priorité : Career, puis apprentissage et fiabilité.

## Parcours utilisateur

En tant que Côme, je veux transformer une amélioration de NAGE en mission
compréhensible, bornée et transmissible à OpenCode depuis l’application Bureau.
Je veux conserver les critères, le code de départ et les preuves de validation.

1. Ouvrir Atelier et choisir une priorité.
2. Ajuster l’objectif et les critères d’acceptation.
3. Préparer la mission, puis lire ou télécharger ses documents.
4. Transmettre le ZIP à OpenCode, ou ajouter la mission au moteur local existant.
5. Revoir la proposition et les tests avant toute application.

## Contrat

- FR-001 : créer un canevas local avec `spec.md`, `plan.md`, `tasks.md`,
  `OPENCODE_MISSION.md`, `mission.json` et `RESULT_TEMPLATE.json`.
- FR-002 : persister la mission et dédupliquer les créations identiques.
- FR-003 : limiter à huit fichiers source et huit fichiers de tests existants.
  Les fichiers de tests d’acceptation restent hors du périmètre modifiable.
- FR-004 : enregistrer SHA observé et empreintes des fichiers; refuser la mise
  en file si le code a changé depuis la préparation.
- FR-005 : conserver le moteur d’évolution existant et lui transmettre les tests
  ciblés pour la référence comme pour le candidat.
- FR-006 : préserver l’authentification locale du Dev Kit et exclure fichiers
  privés, liens symboliques, chemins absolus et commandes fournies par l’UI.
- FR-007 : la préparation et la mise en file ne lancent aucun modèle. Le moteur
  existant garde ses limites de requêtes, de temps, de prix et d’isolation.
- FR-008 : afficher l’Atelier même si l’ancien registre de flotte est absent.
- FR-009 : sauvegarder SQLite avant migration d’une base d’évolution existante.

## Recette synthétique

- Créer une mission, la relire et ouvrir ses six fichiers ZIP.
- Recharger l’application : la mission est retrouvée.
- Ajouter deux fois la même mission au backlog : une seule tâche existe.
- Modifier une source après création : la mise en file est refusée.
- Exécuter un seul test ciblé face à un autre module de tests qui échoue à
  l’import : le module non sélectionné n’est pas collecté.
- Vérifier le parcours sur petit écran, erreurs réseau et titre contenant HTML.

## Limites du lot

Les documents sont des canevas déterministes à préciser, pas une conception
architecturale produite par un modèle. Le ZIP transmet une mission; il ne prouve
ni son exécution par OpenCode ni son intégration. L’exécution locale existante
reste disponible dans l’Atelier avancé `/v5`, sans déploiement automatique.
