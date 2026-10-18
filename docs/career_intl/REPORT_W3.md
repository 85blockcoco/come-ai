# W3 — Connecteurs ATS publics bornés

Statut : **TERMINÉE dans une branche/worktree isolé, non intégrée à `main`**.

## Base et livraisons

- Branche W3 : `codex/w3-source-connectors`, créée depuis le candidat isolé `codex/career-v3-candidate` à `42e67e0` (T1 + W2, non fusionnés dans `main`).
- Base ultime : `main` reste `5ef814eb16f3357264624abdf0b8fd746315b7b1`.
- Les sources T1 et W2 restent intactes dans leurs worktrees respectifs. W3 n'a modifié aucun de ces worktrees.
- Aucun nouvel employeur, board slug ou identifiant n'a été ajouté à `career/source_registry.py`.
- Les nouveaux fournisseurs sont présents dans le map de `CareerService`, mais chacun est désactivé par défaut; le registre actuel ne contient encore que les huit boards Greenhouse vérifiés.

## Sources documentaires officielles consultées

- Lever : [API officielle Lever Postings](https://github.com/lever/postings-api). Elle documente les postings publiés, les pages `skip` / `limit`, les champs et les liens hébergés. L'API n'offre pas une recherche plein texte globale; l'adaptateur lit un nombre borné de pages puis filtre localement.
- Ashby : [Ashby Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api). Endpoint public de postings publiés et champs absents conservés comme inconnus. Le `jobPosting.list` privé, qui exige `jobsRead`, n'est pas utilisé.
- SmartRecruiters : [guide officiel Posting API](https://developers.smartrecruiters.com/docs/posting-api) et [endpoints officiels](https://developers.smartrecruiters.com/docs/endpoints). L'adaptateur force `destination=PUBLIC`, n'envoie aucune clé d'API et n'utilise jamais un résultat `INTERNAL`.

## Implémentation

- Nouveau package `career/connectors/` et contrat commun `PublicATSConnector`.
- Adaptateurs `LeverConnector`, `AshbyConnector`, `SmartRecruitersConnector`; métadonnées de documentation vérifiée, mais `enabled_by_default=False`.
- Transport HTTP standard : HTTPS uniquement, allow-list stricte des hôtes API, redirections interdites, User-Agent Côme AI, limite de réponse 8 MiB, timeout maximal 8 s, pagination plafonnée à 4 pages / 400 entrées / 150 résultats, temps d'attente doux entre pages.
- Aucune URL fournie par un board n'est suivie comme endpoint API; chaque identifiant d'employeur est validé avant construction d'une URL sur un hôte fixe. Une source doit comporter identifiant, employeur, date de vérification et provenance HTTPS avant toute requête.
- Les liens de posting sont restreints aux hôtes carrière officiels connus de chaque ATS. Les dates de début, durée, salaire et langues absentes restent vides/inconnues.
- La qualification commune W2 s'applique après normalisation; stage, durée et début ne sont pas déduits d'un score. Les sorties restent des compteurs cohérents avec `DiscoveryPayload`.
- `CareerService` connaît les connecteurs mais ne consulte pas de nouvelle source faute d'entrée validée dans le registre. Aucun connecteur réseau n'est activé implicitement.

## Tests synthétiques et parcours application_verified

- Fixtures étiquetées « synthetic, not validated against live APIs ».
- Tests de parsing des trois formats, contrats stables, désactivation par défaut, identifiants invalides, provenance manquante, liens hors hôte, paramètre SmartRecruiters `destination=PUBLIC`, et compteurs invariants.
- `REAL-014` utilise le client HTTP réel de l'app (`/api/career/stage-search/explore`) avec le connecteur Lever réel et un transport-fixture. Le contrôle de sockets de l'évaluation reste actif; `network_attempts=0`. Cette mesure prouve le raccordement du code, pas un appel à une source réelle.
- Les tests injectent les transports; ils n'accèdent pas au réseau.

## Contrôle réseau réel borné (hors tests)

Une seule lecture bornée de chaque endpoint d'exemple figurant dans sa documentation officielle a été effectuée avec le transport du connecteur, `page_size=1`, `max_pages=1` et aucun profil. Ces exemples ne sont pas des employeurs ajoutés au registre : `leverdemo`, le board d'exemple Ashby `Ashby`, et le company identifier d'exemple SmartRecruiters `smartrecruiters`.

Sortie observée :

```text
lever: OK raw=1 evaluated=1 qualified=0 retained=0
ashby: OK raw=63 evaluated=63 qualified=0 retained=0
smartrecruiters: OK raw=0 evaluated=0 qualified=0 retained=0
```

Ce test prouve seulement que les exemples publics répondaient à cet instant. Les postings présents étaient non qualifiés par le filtre conservateur (ou aucun posting dans l'exemple SmartRecruiters). **Il ne prouve ni couverture finance, ni adéquation à ton profil, ni la fraîcheur ou le nombre de vrais stages admissibles.** Ashby renvoie un flux non paginé dans cet endpoint; le nombre 63 vient de la réponse et n'est pas un objectif d'affichage.

## Résultats exécutés

Environnement : Python 3.12.10, macOS 14.8.9 x86_64; clés retirées de l'environnement; `HOME=/tmp/codex_home`; données de test synthétiques.

- `python -m pytest -q tests/test_career_public_ats_connectors.py evals/tests/test_come_ai_target.py` → **39 passed in 3.85s** (avant le garde final de vérification des sources).
- `python -m pytest -q` → **999 passed in 110.81s**, aucun échec ni skip affiché.
- `python -m evals run --target come-ai --strict --no-persist` → **14 total, 13 exécutés et réussis, 0 échec, 1 non pris en charge** (`REAL-013`, génération d'un modèle local absente de la cible). Pic mémoire 113.5 MiB; 2.082 s. Les appels API à 0 sont déclarés par la cible, pas mesurés indépendamment par le runner.
- Avertissement non bloquant : dépréciation de l'intégration Starlette/TestClient avec `httpx`.
- `git diff --check` → à revalider immédiatement avant commit.

## Limitations / prochaine action

- L'app n'affiche encore aucun board Lever/Ashby/SmartRecruiters : ajouter un employeur demande une preuve vérifiable de son URL de carrière officielle et de son identifiant ATS. La prochaine tranche utile est le registre d'employeurs finance, avec qualification et provenance pour chaque ajout; elle doit aussi revoir le plafond global des huit sources.
- SmartRecruiters peut renvoyer une référence API plutôt qu'un lien web de candidature dans la liste. Pour améliorer l'URL visible, une prochaine tranche pourra faire un nombre borné de lectures de détails publics, toujours avec `destination=PUBLIC` et sans auth.
- Aucun profil personnel, document/CV, historique de candidature, envoi, candidature externe ou modèle cloud n'a été utilisé.
- Les tests réels d'offres n'ont pas été effectués avec des employeurs finance enregistrés; le contrôle réseau était limité aux identifiants d'exemple officiels.

## Retour arrière

La branche `codex/w3-source-connectors` est isolée; aucun changement n'est dans `main`. Pour annuler W3 dans un candidat d'intégration, revert les commits W3 de cette branche. Ne supprimer ni worktree ni branche source automatiquement.
