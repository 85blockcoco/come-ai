# SPEC-018 — Web Researcher Intelligence

**Mission :** CVBOOST-53 · **Branche :** `worker/cvboost-53-1792701136` · **Worktree :** `AI-Excel-Agent-worker-cvboost-53-1792701136`

## Objectif

Produire, pour une offre de stage, une fiche entreprise **traçable** : stack technique,
valeurs, actualités publiques récentes et résumé GitHub. Chaque fait doit pouvoir être
cité (URL + extrait verbatim + date de récupération) ou ne pas exister.

## Livré

| Fichier | Rôle |
|---|---|
| `career/web_evidence.py` | Contrat de preuve web (`WebEvidence`), identifiants stables, centre de preuves classables |
| `career/web_sources.py` | Transport HTTPS stdlib, `robots.txt`, parsing HTML, détection de vocabulaire, lecteurs site / GitHub / recherche |
| `career/web_research.py` | Orchestrateur `WebFacts`, cache 24 h (documents par hôte + faits par offre), fusion d'une fiche utilisateur, fraîcheur |
| `tests/test_web_research.py` | 30 tests hors ligne (transport, recherche et horloge injectés) |
| `career/router.py` | 3 endpoints (dont alias sans préfixe), capacité `web_research` dans `/api/career/health` |

Aucun fichier existant d'un autre module n'est modifié : `service.py`, la base SQLite,
les connecteurs et le front restent intacts. L'intégration est additive.

## Contrat de preuve — « zéro invention »

`WebEvidence` porte `id`, `url`, `title`, `excerpt`, `source_kind`, `fact_kind`,
`retrieved_at`, `confidence`, `verifiable`.

- **Extrait verbatim** : quand `source_text` est fourni, `make_evidence()` échoue
  (`EvidenceNotVerifiable`) si l'extrait n'est pas une sous-chaîne du texte source, à
  normalisation d'espaces près. Les faits de site sont tous créés avec cette garde.
- **Id déterministe** : `web_` + 16 hex de `sha256(url canonique | fact_kind | extrait)`.
  Deux recherches sur les mêmes pages produisent les mêmes ids — une preuve web peut
  donc être citée à travers les runs.
- **Classement** : `fact_kind ∈ {stack, values, news, repo, about}` et
  `source_kind ∈ {company_site, github, search, user_provided}`. `WebEvidenceCenter`
  expose `by_fact()`, `ids` et `to_list()` : c'est le point d'entrée d'un futur evidence
  centre inter-sources.
- **Séparation honnête** : une fiche fournie par la personne utilise le schéma `user:`
  et `verifiable = false`. Une source GitHub ou un snippet de recherche est un
  **rendu de champs publics**, jamais une citation de prose inventée.
- **Déduplication** : même URL + même fait + même extrait ⇒ une seule preuve.

## Sources lues

1. **Site entreprise** : origine de `official_url`, puis `/`, `/about`, `/careers`,
   `/engineering-blog`. La page de l'offre elle-même n'est jamais recrawlée.
2. **GitHub** : organisation déduite d'un lien `github.com/<org>` présent sur le site,
   sinon slug déduit du nom (marqué `inferred`). Lecture de `/orgs/{org}` et des dépôts
   publics, langages, étoiles, date de push, puis releases récentes des 2 dépôts les
   plus étoilés. Aucune écriture, aucun token.
3. **Recherche** : `DuckDuckGoSearch` (API Instant Answer, sans clé) sur au plus 2
   requêtes construites uniquement à partir de l'offre (entreprise, ville, intitulé).
   Les snippets sont cités tels quels ; une date absente reste `null`.

`robots.txt` est lu et mis en cache par hôte. Un `Disallow` est respecté (page ignorée,
avertissement explicite). Un `robots.txt` absent, illisible ou injoignable **autorise**
la lecture — une panne transitoire ne doit pas rendre tous les sites illisibles.

## Réseau et sécurité

- Transport stdlib uniquement, HTTPS obligatoire en lecture, corps plafonné à 1,5 Mo,
  délai par défaut 8 s, 3 redirections maximum.
- Refus avant toute socket : `localhost`, noms `.local` / `.internal`, adresses IP
  privées ou non globales, URL avec identifiants, schémas non HTTP(S).
- Aucune exécution de HTML/JS, aucun envoi de données personnelles, aucun formulaire.
- Le texte distant est une donnée non fiable : il est parsé, jamais interprété comme
  instruction.

## Cache et mode hors ligne

- **Faits** : un JSON par offre (`offer:<id>`, sinon `company:<slug>`), TTL 24 h,
  écriture atomique et permissions `0600`.
- **Documents** : un JSON par hôte, TTL 24 h — un second run dans la fenêtre ne
  refait aucune requête.
- **Panne réseau** :
  - cache existant → faits en cache, `status="cached"`, `from_cache=true`,
    `stale=true` si la fenêtre est dépassée, avertissement lisible ;
  - aucun cache → `status="offline"`, `confidence=0`, listes vides, avertissement.
    Rien n'est inventé pour « remplir » la fiche.
- **`provide`** fonctionne sans réseau : la fiche utilisateur est fusionnée, étiquetée
  `user_provided`, et réinitialise la fraîcheur sans prétendre à une preuve web.

## API

```text
GET  /api/career/web/research/{job_id}[?refresh=true]
POST /api/career/web/research/{job_id}/provide
GET  /api/career/web/research/{job_id}/freshness
```

Alias sans préfixe (contrat SPEC-018) : `/web/research/{job_id}`,
`/web/research/{job_id}/provide`, `/web/research/{job_id}/freshness`.

`GET` renvoie `company`, `stack`, `values`, `recent_news`, `repos_summary`,
`evidence_ids`, `evidence[]`, `sources[]`, `fetched_at`, `confidence`, `status`,
`from_cache`, `stale`, `warnings`, `provided_at`.

`POST /provide` accepte `company`, `stack[]`, `values[]`, `notes`, `sources[]`
(`url`, `title`, `excerpt`, `fact_kind`), `news[]` (`title`, `url`, `date`, `excerpt`).
Les listes et textes sont bornés ; les URL non publiques sont ignorées avec un
avertissement.

`GET /freshness` renvoie `available`, `status` (`not_found|fresh|stale`),
`fetched_at`, `stored_at`, `age_seconds`, `ttl_hours`, `provided_at`,
`evidence_count`, `source_count`.

## Décisions et limites assumées

- **`skills.yaml` absent du dépôt** : le lexique stack/valeurs est embarqué dans
  `web_sources.py`, déterministe et extensible. Aucun fichier de configuration n'a été
  inventé.
- **Evidence centre absent à ce commit** : `WebEvidenceCenter` fournit le contrat
  minimal (classement par `fact_kind`, ids stables, export JSON) que le centre
  inter-sources pourra consommer tel quel.
- **Recherche** : l'API Instant Answer de DuckDuckGo donne des snippets encyclopédiques,
  pas un flux d'actualités daté. Les dates ne sont donc jamais fabriquées ; les
  actualités datées restent minoritaires tant qu'un fournisseur de news explicite n'est
  pas branché. Le provider est injectable (`SearchProvider`) pour cette évolution.
- **Pas de crawler récursif** : seules 4 pages de site + l'organisation GitHub sont
  lues. C'est volontairement borné (coût, robots, bruit).
- **Pas d'async natif** : l'orchestrateur est synchrone et exécuté dans le threadpool
  FastAPI (`run_in_threadpool`), comme le reste du service Career. Le cache et les
  transports sont injectables, donc testables hors ligne.

## Validation

| Commande | Résultat |
|---|---|
| `pytest -q tests/test_web_research.py` | **30 passed** |
| `pytest -q` (suite complète) | **1454 passed, 1 skipped** |
| `ruff check .` | **All checks passed** |
| `git diff --check` | **propre** |
| `create_app()` + routes web research | **import OK, endpoints servis** |

Le venv du worktree est absent (le dépôt hôte fournit `.venv`) ; les commandes ont été
exécutées avec `/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python`.
