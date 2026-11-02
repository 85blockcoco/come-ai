# Audit NAGe / Côme AI — 2026-11-02

## Verdict exécutif

La candidate est cohérente et utilisable pour un parcours Career local contrôlé.
Les domaines Career, lettres, shortlist, ATS/dossier, academics et Dev Kit passent
les validations ciblées disponibles. Le niveau de preuve est **RC fonctionnelle**,
pas encore « production finale » : la suite complète n'a pas été lancée, la recette
navigateur finale sur l'instance du bureau n'a pas été rejouée après les derniers
assets, et la performance `< 3 s` reste à remesurer sur une population synthétique
chargée dans cette version exacte.

## Preuves exécutées dans cet audit

### Tests automatisés

Campagne ciblée Career + Dev Kit + évolution + academics + UI :

```text
847 passed in 120.91s
```

Contrôles additionnels :

- Ruff sur les fichiers Dev Kit, Career et academics modifiés : vert.
- `node --check career_static/career.js` : vert.
- `node --check desktop_static/app.js` : vert.
- `node --test tests/js/career_list_loading.test.cjs` : 2 passed.
- `git diff --check` : vert.

Le test initial avait 843 réussites et 4 régressions UI. Elles ont été corrigées puis
la campagne complète a été rejouée à 847 réussites.

### Smoke HTTP de la candidate

Serveur lancé isolément sur `127.0.0.1:18960` puis arrêté proprement :

| Route | Code | Temps observé |
|---|---:|---:|
| `/api/health` | 200 | 29 ms |
| `/api/career/health` | 200 | 148 ms |
| `/career` | 200 | 11 ms |
| `/app` | 200 | 6 ms |
| `/api/career/dashboard` | 200 | 40 ms |
| `/api/career/application-pipeline` vide | 200 | 15 ms |
| `/api/academics/finance/calculate` | 200 | 15 ms |

Le pipeline vide n'est pas une mesure de charge. Les mesures antérieures sur données
synthétiques restent séparées : médiane candidate sous 3 s sur 1 000 offres, mais le
serveur partagé avait précédemment mesuré 3,378 s. Le contrat doit être remesuré avec
la candidate exacte et une base synthétique chargée.

## État par domaine

| Domaine | État | Niveau de preuve | Amélioration restante prioritaire |
|---|---|---|---|
| Lancement / navigation | Fonctionnel | routes HTTP 200 + tests UI | recette depuis l'icône exacte du bureau |
| Career health / profil | Fonctionnel local | tests Career + health 200 | valider un vrai parcours d'import synthétique après redémarrage |
| Découverte d'offres | Fonctionnel contrôlé | connecteurs et fixtures synthétiques | vérifier fraîcheur/provenance avec sources live autorisées |
| Dates / durée / langues | Fonctionnel sur fixtures | tests offer dates et qualification | élargir les cas multilingues contradictoires |
| Matching BBA/Bac+4/M2/MBA | Fonctionnel | tests éducation/qualification | exposer plus clairement le réglage dans l'UI finale |
| Shortlist | Fonctionnel | routes, persistance, exports, refus vide | test navigateur complet shortlist → dossier |
| CV / ATS | Fonctionnel local | tests ATS, variantes et routes | valider PDF/DOCX réels fournis par l'utilisateur, hors dépôt |
| Lettres | Fonctionnel local | render/check/approve/export + approbation liée au contenu | refaire recette navigateur après changement final de cache |
| Dossier de candidature | Fonctionnel local | routes ATS/checklist/preview | simplifier le parcours visible à trois actions |
| Soumission | Protégée | `automated_submission=false`, tests de garde | continuer à interdire tout envoi automatique |
| Suivi de candidature | Fonctionnel manuel | routes et tests de confirmation | revue UX des états `unknown` et `confirmed` |
| Coach entretien | Fonctionnel local | tests ciblés | davantage de scénarios finance synthétiques |
| Academics | Fonctionnel et borné | routes + boundaries + integration | recette navigateur PDF/Word/Excel unifiée |
| Dev Kit | Fonctionnel borné | 28 tests dédiés + CLI dry-run | matérialisation `spec → plan → tasks` encore à construire |
| Mémoire / V5 | Présent mais partiellement démontré | health HTTP et tests historiques | recette cloud/consentement avec fournisseur simulé |
| Performance | Partiellement prouvée | mesures historiques + smoke vide | mesure p50/p95 sur 150 et 1 000 offres actuelles |
| Sécurité locale | Bonne couverture ciblée | secrets, symlinks, consentement, exports | audit dépendances/licences et test adversarial final |

## Correctifs réalisés pendant l'audit

1. Suppression du dernier `window.prompt` dans le parcours de suppression Career ;
   confirmation explicite conservée avec le token serveur attendu.
2. Alignement des quatre versions de cache Career (`career.css`, `cv_plan.css`,
   `career.js`, `cv_plan.js`) sur `codex-v3-20261102-rc11`.
3. Rejeu des tests UI concernés : 9 passés.
4. Rejeu de la campagne domaine complète : 847 passés.

## Ce qui est réellement prêt

- Démonstration locale sans fournisseur cloud configuré.
- Import et qualification d'offres synthétiques.
- Classement explicable et shortlist persistante.
- Préparation CV/lettre avec contrôle factuel.
- Export local protégé et téléchargement contrôlé.
- Parcours de candidature manuelle sans soumission automatique.
- Dev Kit pouvant mettre les 200 missions en file, en aperçu ou en import borné.

## Ce qui n'est pas encore démontré

- La suite pytest complète du dépôt.
- Un parcours navigateur final exécuté depuis l'icône du bureau sur cette révision
  exacte après la correction des assets.
- Une mesure de performance réaliste sur une base de 150/1 000 offres construite
  par le serveur de cette candidate.
- La disponibilité réelle et la fraîcheur de chaque source internationale.
- La qualité sur le CV, les devoirs et les documents personnels de l'utilisateur.
- Une utilisation cloud avec consentement explicite et fournisseur réellement actif.

## Priorités P0 restantes

1. Rejouer la recette navigateur depuis l'instance du bureau : découverte → détail →
   shortlist → CV → lettre → approbation → export.
2. Charger 150 puis 1 000 offres synthétiques et remesurer p50/p95 du pipeline.
3. Vérifier la persistance après redémarrage pour shortlist, brouillon de lettre et suivi.
4. Finaliser le parcours trois interactions sans ouvrir une ancienne application parallèle.
5. Préparer le diff de fusion vers `main` après validation humaine de cette RC.

## Décision actuelle

**Candidate acceptable pour poursuite et démonstration locale contrôlée.**

**Merge dans `main` : non proposé dans cet audit**, tant que les cinq priorités P0
ci-dessus n'ont pas leurs preuves sur l'instance cible.
