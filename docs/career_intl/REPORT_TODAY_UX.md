# Amélioration d'utilisation — accueil « Aujourd’hui »

## Livraison

- Branche : `codex/profile-compatibility-ux`
- Base conservée : `main` reste inchangée.
- Changement : le tableau de bord charge automatiquement le profil local et affiche sa préparation sur 20, l'action suivante et un bouton direct vers « Mon profil ».

## Pourquoi

Le parcours quotidien ne doit pas obliger l'utilisateur à parcourir plusieurs onglets pour savoir quoi faire. L'accueil donne désormais une décision immédiate : compléter le profil ou continuer vers les offres. Le texte rappelle que la note est une mesure de complétude et non une prédiction d'embauche.

## Vérifications

- `node --check career_static/career.js` : succès.
- Tests UI et profil : `16 passed in 3.42s`.
- Suite complète avec environnement local isolé et secrets cloud retirés : `1097 passed in 86.08s`.
- Aucun schéma de base, connecteur ou garde-fou de confidentialité modifié.

## Limites

L'état affiché dépend du profil local réellement enregistré. Aucun CV personnel n'a été importé dans cette livraison et aucun appel cloud n'est requis pour calculer la carte.

