# W2 — Qualification conservatrice des offres

Statut : **TERMINÉE dans un worktree isolé, non intégrée à `main`**.

## Révisions

- Base : `5ef814eb16f3357264624abdf0b8fd746315b7b1` (`main`, inchangée au dernier contrôle).
- Branche : `codex/w2-offer-qualification`.
- Commits de tests d'abord : `289d410` (contrats adversariaux), `7a47857` (parcours HTTP et exclusions), `b9d3055` (dates de début/fin).
- Le code W2 et le présent rapport sont les changements en cours à committer après vérification finale.
- Tag prévu : `night-W2-done`, seulement après les commits de code et de documentation.

## Livré et prouvé

- Nouveau `career/offer_qualification.py` : qualification factuelle et prudente des offres, contrat, dates, durée exacte ou intervalle, langue, pays/ville, URL officielle, source, statut de vérification, provenance et champs manquants.
- Les catégories de contrat distinguent notamment stage, alternance, CDI, CDD, VIE, autre et inconnu. Un indice contradictoire dans le contenu ne devient pas un stage confirmé par le seul titre.
- Les critères de six mois et début en janvier rendent `conforming`, `non_conforming` ou `to_verify`. Les valeurs absentes restent inconnues. Une annonce non vérifiée par URL officielle ne devient pas vérifiée.
- Les durées dérivées de dates suivent des bornes prudentes : la durée minimale est en mois calendaires complets ; un intervalle dont le minimum n'atteint pas six mois reste à vérifier, et non conforme n'est décidé qu'en cas de preuve suffisante.
- Branchement dans le connecteur Greenhouse et le service d'exploration : les offres déjà prouvées non conformes aux critères de durée/début ne sont pas conservées comme admissibles. Les candidates incertaines ne sont pas promues comme conformes.
- L'évaluation REAL-010..012 utilise le client HTTP réel de l'application (`/api/career/stage-search/explore`) avec un connecteur synthétique, sockets bloqués par le harnais et données fictives. Elle vérifie une offre conforme, les champs manquants et l'exclusion d'un contrat/durée non conforme. Ce n'est pas un appel de source réelle.

## Preuves exécutées

Environnement de test : Python 3.12.10, macOS 14.8.9 x86_64. Les secrets de fournisseurs ont été retirés de l'environnement, le `HOME` était factice, et les tests utilisaient uniquement des données synthétiques.

- Baseline avant W2 : `python -m pytest -q` → **749 passed in 47.28s**, aucun skip affiché.
- Après W2 : `python -m pytest -q` → **785 passed in 108.44s**, aucun échec ni skip affiché.
- Évaluation : `python -m evals run --target come-ai --strict --no-persist` → **12 total, 11 exécutés, 11 réussis, 0 échec, 1 non pris en charge** (`REAL-009`, génération par modèle local absente de cette cible). Temps 1.041 s, pic mémoire 112.6 MiB. Les 11 scénarios sont mesurés par la cible; les appels API = 0 sont déclarés par celle-ci et non mesurés indépendamment par le runner.
- Avertissement non bloquant observé : dépréciation Starlette/TestClient concernant `httpx`.
- `git diff --check` → succès avant le test complet.

Commandes reproductibles depuis le worktree (en gardant l'environnement de test synthétique) :

```sh
env -u GEMINI_API_KEY -u GOOGLE_API_KEY -u OPENROUTER_API_KEY HOME=/tmp/codex_home PYTHONDONTWRITEBYTECODE=1 /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q
env -u GEMINI_API_KEY -u GOOGLE_API_KEY -u OPENROUTER_API_KEY HOME=/tmp/codex_home PYTHONDONTWRITEBYTECODE=1 /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m evals run --target come-ai --strict --no-persist
git diff --check
```

## Fichiers et hunks partagés

- `career/offer_qualification.py` — nouveau module de logique.
- `tests/test_career_offer_qualification.py`, `tests/test_career_discovery_selection.py` — cas synthétiques ajoutés dans les commits tests-first.
- `career/discovery.py` — import du module et qualification avant l'admission Greenhouse; changement ciblé aux lignes voisines de la normalisation des offres (hunk de 15 lignes maximum).
- `career/service.py` — qualification des offres découvertes avant conservation; hunk ciblé de 9 lignes à l'exploration et 6 lignes au rafraîchissement (accroches brèves, logique métier déportée).
- `evals/come_ai_target.py` — scénario `application_verified` via le client HTTP réel et source synthétique; aucun trafic réseau externe n'est requis.
- `docs/career_intl/NIGHT_STATE.md` — état et point de reprise.

## Pas prouvé / limites

- Aucune source publique réelle n'a été consultée pendant les tests W2; la qualité, la fraîcheur et la couverture d'offres réelles restent non mesurées.
- Aucune navigation navigateur n'a été faite.
- Pas de CV, profil personnel, base réelle, fournisseur IA ou candidature utilisé.
- Cette tranche ne met pas encore à jour la sélection pour plusieurs pays, ne garantit pas que toutes les dates sont extraites du texte libre, et n'ajoute pas de connecteurs.
- Aucun merge, push ou déploiement dans `main`.

## Retour arrière

Le travail est isolé. Pour annuler W2 dans ce worktree après le tag, revenir au tag `night-W2-done` est le point de restauration de la tranche, et la branche `main` demeure intacte. Ne pas supprimer le worktree ni la branche sans instruction explicite.

## Prochaine action

Conformément à la nouvelle feuille de route de l'utilisateur, ne pas enchaîner W3. Examiner en lecture seule le diff et les tests de `codex/t1-privacy-guards`, puis définir le lot minimal de garde-fous confidentialité à intégrer avant tout enrichissement des sources ou transmission de profil à un service distant.
