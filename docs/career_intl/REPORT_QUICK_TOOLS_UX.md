# Interface — accès rapide aux outils Career

## Livraison

Le tableau de bord contient maintenant une grille « Tous tes outils Career ». Elle expose uniquement des vues existantes et réellement câblées :

- Explorer les stages (`stagehunter`)
- Construire mon profil (`profile`)
- Préparer un dossier (`studio`)
- Suivre mes candidatures (`applications`)
- M'entraîner (`interviews`)
- Gérer mes sources (`discover`)

Chaque carte utilise le mécanisme local `data-view-action` et n'invente aucune nouvelle capacité. Les boutons sont utilisables au clavier, s'adaptent aux petits écrans et restent dans l'identité visuelle verte existante.

## Vérifications

- `node --check career_static/career.js` : succès.
- Tests UI et profil : `17 passed in 5.74s`.
- Suite complète : `1098 passed in 76.89s`.
- Aucun appel réseau, aucune clé, aucune donnée personnelle et aucune modification de schéma.

## Limite

Cette livraison améliore l'accès aux fonctionnalités déjà disponibles ; elle ne prétend pas rendre opérationnelles les fonctions encore marquées comme non vérifiées dans les autres rapports.

