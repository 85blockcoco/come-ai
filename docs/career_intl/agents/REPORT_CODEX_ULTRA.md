# Rapport — CODEX ULTRA, validation Career

STATUT: PARTIELLE — pré-vol et sources validés, navigateur Career non exploitable dans cette session
MISSION: CODEX ULTRA — Rendu final Career

## Livré

La branche candidate `codex/profile-compatibility-ux` contient les lots Career déjà consolidés : exploration publique bornée, qualification prudente, classement explicable, critères configurables, préparation de candidature, profil local, raccourcis d'interface, carte/tri/fiche d'offre, résumé local et résumé cloud protégé par consentement, ainsi que les modules Study Coach et Consent Guard présents dans cette base.

La branche n'a pas modifié `main`.

## Backend

Pré-vol réussi :

- `py_compile` de `come_ai_web.py`, `hybrid_chat.py`, `career/service.py`, `career/router.py`, `career/application_prep.py` : succès.
- Import `create_app` : `IMPORT OK`.
- Endpoints de résumé présents pour GET et POST (`/api/career/jobs/{job_id}/summary`).
- Le résumé local est disponible par défaut ; l'amélioration distante exige un consentement explicite.

## UI

Les éléments attendus sont présents dans le code :

- carte `#stagehunter-map` ;
- sélecteur `#stagehunter-sort` ;
- fiche détaillée ;
- navigation entre offres ;
- parcours de préparation et suivi ;
- consentement explicite avant résumé cloud ;
- accueil « Aujourd'hui » et accès rapides ;
- import local du CV avec relecture.

Une session navigateur locale a démarré sur le port `8921` et l'application principale `/v5` s'est chargée. La navigation automatique vers `/career` n'a pas fourni de snapshot DOM exploitable après le changement de page. Le parcours Career visuel est donc NON VÉRIFIÉ dans cette session, même si les garde-fous UI et tests JavaScript sont verts.

## Tests

- Collecte : `1110 tests collected`.
- Suite complète isolée, sans clés cloud : `1110 passed in 69.61s`.
- `node --check career_static/career.js` : succès.
- Tests de consentement et Study Coach inclus dans la suite complète.

## Métriques live

Commande exécutée : `scripts/live_source_check.py`, avec HOME isolé et variables de clés retirées.

- Sources interrogées : 21.
- Sources réussies : 21.
- Sources échouées : 0.
- Sources non interrogées : 0.
- Offres retenues : 45.
- Les volumes bruts sont ceux renvoyés par les sources au moment du contrôle ; ils sont temporels et ne constituent pas une garantie permanente de disponibilité.

## Consentement et données

Aucune clé API n'a été affichée ou journalisée. Aucun CV, e-mail, téléphone ou profil personnel réel n'a été utilisé. Aucun fournisseur cloud n'a été sollicité pour le pré-vol, les tests ou le contrôle des sources.

## État Git

- Branche : `codex/profile-compatibility-ux`.
- HEAD avant ce rapport : `281e60418e941d9c9a12a073482776d1197b27a5`.
- `main` : `5ef814eb16f3357264624abdf0b8fd746315b7b1`.
- Aucun merge, push ou modification de `main`.

## Prochaine vérification recommandée

Relancer le serveur local sur un port libre, ouvrir directement `/career`, puis vérifier visuellement la carte, le tri persistant, la fiche détaillée et le bouton de résumé. Cette vérification doit rester séparée d'une éventuelle utilisation de données personnelles.

