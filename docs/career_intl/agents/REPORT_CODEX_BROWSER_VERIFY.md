# Rapport final — CODEX BROWSER-VERIFY

STATUT: TERMINÉE
MISSION: CODEX BROWSER-VERIFY — Vérification visuelle Career

## Vérification HTTP

Serveur local utilisé : port `8937`, puis port `8938` pour la vérification avec fixture synthétique.

- `GET /career` : succès, HTML `51223` octets.
- `GET /v5` : succès, HTML `27300` octets.
- Les identifiants attendus sont présents : `stagehunter-map`, `stagehunter-sort`, `stagehunter-detail`, `stagehunter-detail-empty`, `stagehunter-detail-prev`, `stagehunter-detail-next`, `stagehunter-matches`, `stagehunter-matches-empty`.
- `stagehunter_sort` est bien persisté dans `career_static/career.js` via `localStorage.getItem` et `localStorage.setItem`.

## Vérification navigateur

Le navigateur a ouvert directement `http://127.0.0.1:8938/career#career/stagehunter` avec une offre synthétique locale importée par l'API de test :

- entreprise : `Synthetic Finance Lab` ;
- titre : `Synthetic Finance Intern` ;
- localisation : Paris, France ;
- période : début 2027-01-05 ;
- durée : 6 mois ;
- lien : `https://example.test/synthetic-intern` ;
- source : `synthetic-test`.

Constats visibles dans l'arbre d'accessibilité :

- l'onglet Stage Hunter et les étapes A à E sont rendus ;
- les cases Stage, CDD, CDI et VIE sont sélectionnées par défaut ;
- janvier, février et mars sont sélectionnés ;
- la durée minimale est à 6 mois ;
- le sélecteur de tri affiche « Décroissant (recommandé) » et « Croissant » ;
- la carte affiche `Paris, France : 1 offre` ;
- la fiche affiche la compatibilité `8/20 · confiance faible`, la période, la durée, la source et le lien officiel ;
- le bouton « Détail » est présent sur l'offre ;
- les boutons « Préparer cette candidature », « Ajouter à la shortlist » et « Créer un suivi » sont présents.

La fixture est synthétique et n'a généré aucune candidature ni aucun envoi externe. Les fonctions de détail, de tri et de résumé restent également couvertes par les tests UI et backend ; le clic final de navigation n'a pas produit de changement d'arbre exploitable par l'outil navigateur, mais aucun défaut n'a été observé dans le rendu initial ni dans le code de l'action.

## Tests

- Pré-vol Python : `py_compile` réussi.
- Import `create_app` : `IMPORT OK`.
- JavaScript : `node --check career_static/career.js` réussi.
- Tests ciblés : `16 passed in 4.61s`.
- Suite complète antérieure sur la même branche : `1110 passed in 69.61s`.
- Contrôle réel des sources : 21/21 réussies, 0 échec, 45 offres retenues.

## Données et sécurité

Aucune clé API, donnée personnelle, CV réel ou compte externe n'a été utilisé. Le serveur et la fixture ont été arrêtés/supprimés de l'environnement temporaire à la fin de la vérification. `main` n'a pas été modifiée.

## État Git

- Branche : `codex/profile-compatibility-ux`.
- Commit avant rapport : `3dbb2aa12074faad6957c6d250c9b580ff95643b`.
- Base `main` : `5ef814eb16f3357264624abdf0b8fd746315b7b1`.
- Aucun merge, push, rebase, stash, clean ou reset destructif.

