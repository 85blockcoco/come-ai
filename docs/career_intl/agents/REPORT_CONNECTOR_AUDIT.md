# Rapport d'audit indépendant — Connecteurs d'offres (ATS publics)

STATUT: TERMINÉ
MISSION: Audit indépendant des connecteurs Greenhouse, Lever, Ashby, SmartRecruiters
MODE: lecture seule, aucun appel réseau, aucun ajout de source, aucun code modifié

## Méthodologie et statuts

- **MESURÉ** : constat vérifié par exécution de code ou de tests dans cette session.
- **LU** : constat lu dans le code source (fichier:ligne).
- **JUGÉ** : analyse de l'auditeur, non une preuve.
- **NON VÉRIFIÉ** : non testé ni mesuré dans cette session; aucune affirmation de vérité.

Toutes les affirmations ci-dessous sont soit MESURÉES soit LUES. Les JUGÉS sont
explicitement marqués. Aucune information n'est inventée.

## Fichiers concernés (LU)

- `career/discovery.py` — connecteur Greenhouse (`GreenhouseJobBoardConnector`, `GreenhouseBoard`, `UrllibGreenhouseTransport`).
- `career/connectors/public_ats.py` — connecteurs Lever, Ashby, SmartRecruiters (`LeverConnector`, `AshbyConnector`, `SmartRecruitersConnector`, `PublicATSConnector`, `UrllibPublicATSTransport`).
- `career/connectors/__init__.py` — enregistrement (`CONNECTOR_SPECS`, `default_exploration_connectors`).
- `career/exploration.py` — `classify_internship`, `criteria_admit`, `ranking_key`, constantes `EXPLORATION_MAX_RESULTS=150`, `EXPLORATION_MAX_SOURCES=24`.
- `career/offer_qualification.py` — `qualify_offer`, `QualifiedOffer`.
- `career/source_registry.py` — 21 sources curées (15 greenhouse, 3 lever, 3 ashby, 0 smartrecruiters).
- `career/models.py` — `clean_text`, `canonical_url`, `_location_parts` (LU via import).
- `tests/test_career_public_ats_connectors.py` — tests synthétiques (187 lignes).
- `tests/test_career_verified_source_expansion.py` — tests sources vérifiées (100 lignes).
- `tests/fixtures/career_connectors_synthetic.json` — fixtures synthétiques.

## Constantes communes (MESURÉ)

- `MAX_RESPONSE_BYTES = 8 * 1024 * 1024` (8 MiB) — `public_ats.py:30`.
- `MAX_PAGES = 4` — `public_ats.py:31`.
- `PAGE_SIZE = 100` — `public_ats.py:32`.
- `MAX_ROWS = 400` — `public_ats.py:33`.
- `TIMEOUT_SECONDS = 8` — `public_ats.py:34`.
- `GREENHOUSE_MAX_RESPONSE_BYTES = 8 * 1024 * 1024` — `discovery.py`.
- `GREENHOUSE_MAX_JOBS = 150` — `discovery.py`.
- `GREENHOUSE_MAX_FEED_ROWS = 20_000` — `discovery.py`.
- `GREENHOUSE_TIMEOUT_SECONDS = 8` — `discovery.py`.
- `EXPLORATION_MAX_RESULTS = 150` — `exploration.py:22`.
- `EXPLORATION_NETWORK_BUDGET_SECONDS = 60` — `exploration.py:23`.

---

## 1. Greenhouse

### Fichiers concernés (LU)
- `career/discovery.py` : `GreenhouseJobBoardConnector`, `GreenhouseBoard`, `UrllibGreenhouseTransport`, `_normalise`, `_explicit_employment_type`, `_location_parts` (partagé).
- `career/exploration.py` : `classify_internship`, `criteria_admit`, `ranking_key`.
- `career/offer_qualification.py` : `qualify_offer`.
- `career/source_registry.py` : 15 sources greenhouse.

### Champs réellement lus (LU, `_normalise`)
- `raw["id"]` → `source_id` (obligatoire; offre ignorée si absent).
- `raw["title"]` → `title` (obligatoire).
- `raw["absolute_url"]` → `official_url` (obligatoire; offre ignorée si absent ou URL non canonique).
- `raw["location"]["name"]` → `city`, `country` via `_location_parts`.
- `raw["content"]` → `description_original` (HTML converti en texte borné à 30 000 car).
- `raw["metadata"]` → `employment_type` via `_explicit_employment_type` (uniquement si `internships_only=True`).
- `board.company` → `company` (pas depuis le flux; depuis la source curée).
- `posted_date`, `deadline_date`, `start_date`, `end_date`, `duration_months` : **non lus** (mis à `""` / `None`) — LU: `discovery.py` lignes `_normalise`.
- `employment_type` : lu uniquement en mode internships; en mode discovery normal, mis à `""` (LU).

### Dates et durées disponibles (LU)
- Aucune date structurée lue depuis Greenhouse (posted, deadline, start, end = vide).
- Durée : `None` (non fournie par le flux).
- Seule source de dates : le texte de la description (parsé par `qualify_offer` via regex sur mois/années/durées).
- **MESURÉ** : test `test_career_verified_source_expansion.py` confirme que les offres Greenhouse n'ont pas de `start_date`/`end_date` structurés.

### Identifiants utilisés (LU)
- `source_id` = `raw["id"]` (clean_text, limit 240).
- `official_url` = `raw["absolute_url"]` (clean_text, limit 2000).
- Identifiant de board : `board_token` (regex `^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$`).
- Validation URL : host doit être `boards-api.greenhouse.io` (MESURÉ: transport refuse tout autre host).

### Pagination (LU)
- **Aucune pagination** : un seul GET sur `https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true`.
- Le flux complet est lu en une requête.
- `GREENHOUSE_MAX_FEED_ROWS = 20_000` : si le flux dépasse, erreur `too_many_rows`.
- `GREENHOUSE_MAX_JOBS = 150` : sélection par `heapq.nsmallest` des 150 meilleures offres.

### Limites (MESURÉ/LU)
- Taille réponse : 8 MiB max (LU: `GREENHOUSE_MAX_RESPONSE_BYTES`).
- Timeout : 8 s par requête (LU).
- Retry : 1 retry de 0.35 s sur erreur retryable (429, 5xx, timeout) — LU: `discover_ranked`.
- Budget réseau global : 60 s (LU: `EXPLORATION_NETWORK_BUDGET_SECONDS`).
- Délai entre requêtes : 0.25 s minimum (LU: `_request` dans public_ats; Greenhouse n'a pas de `_request`, donc pas de délai explicite entre tentatives — LU).
- `GREENHOUSE_TOKEN_RE` : token max 120 car.

### Erreurs gérées (LU)
- HTTP 429, 500/502/503/504 : retryable.
- HTTP 404 : board introuvable.
- HTTP 401/403 : accès refusé.
- URLError, timeout : retryable.
- Réponse > 8 MiB : `oversize`.
- JSON invalide : `invalid_json`.
- Flux > 20 000 entrées : `too_many_rows`.
- Format inattendu (pas de `jobs` list) : `invalid_payload`.

### Risques de faux « conforme » (JUGÉ)
- **Élevé** : aucune date structurée. `qualify_offer` doit extraire mois/durée depuis la description via regex. Une description vague ou incomplète laisse `start_month=None` → statut `to_verify` (pas `conforming`), ce qui est conservateur. Mais une description bien rédigée avec un mois et une durée explicite peut produire `conforming` sans vérification externe.
- **Modéré** : `employment_type` n'est lu qu'en mode `internships_only`. En mode découverte standard, le contrat est inconnu → `qualify_offer` tente de l'inférer depuis le titre/description. Un titre "Intern" sans mention explicite de contrat peut être classé `internship` par `classify_internship` (regex sur "intern") sans preuve de contrat formel.
- **Modéré** : `_explicit_employment_type` ne lit que les metadata nommées "employment type"/"requisition type"/"candidate type". Si Greenhouse expose le contrat dans un autre champ, il est ignoré.
- **Faible** : l'URL officielle est validée (`canonical_url` + host Greenhouse). Un poste avec URL invalide est ignoré (`invalid_count`).

### Tests existants (MESURÉ)
- `tests/test_career_verified_source_expansion.py` : 100 lignes, tests avec sources réelles (Greenhouse).
- `tests/test_career_explorer_web.py` : 96 lignes, HTTP end-to-end avec source synthétique Greenhouse.
- `tests/test_career_exploration.py` : 44 lignes modifiées.
- `tests/test_career_stage_hunter.py` : 51 lignes modifiées.
- `tests/test_career_discovery_selection.py` : 19 lignes.

### Tests manquants (JUGÉ)
- Pas de test unitaire isolé du `_normalise` Greenhouse avec un flux réel anonymisé.
- Pas de test de la limite `GREENHOUSE_MAX_FEED_ROWS` (20 000).
- Pas de test de retry sur 429/503.
- Pas de test de `_explicit_employment_type` avec metadata Greenhouse réels.
- Pas de test de `_location_parts` avec des localisations multi-villes réelles (London/Paris/HK/Tokyo).

---

## 2. Lever

### Fichiers concernés (LU)
- `career/connectors/public_ats.py` : `LeverConnector`, `_normalise_one` (appel `_common_job`).
- `career/source_registry.py` : 3 sources lever (qonto, pigment, contentsquare).
- `tests/test_career_public_ats_connectors.py` : tests synthétiques.

### Champs réellement lus (LU, `_normalise_one`)
- `raw["id"]` → `source_id`.
- `raw["text"]` → `title`.
- `raw["hostedUrl"]` → `official_url`.
- `raw["applyUrl"]` → `apply_url`.
- `raw["descriptionPlain"]` → `description_original` (texte brut, pas HTML).
- `raw["categories"]["location"]` → `city`, `country` via `_location_parts`.
- `raw["country"]` → `country` (fallback).
- `raw["categories"]["commitment"]` → `employment_type`.
- `posted_date` : **non lu** (passé `""` à `_common_job`).
- `deadline_date`, `start_date`, `end_date`, `duration_months` : **non lus** (vides/None).

### Dates et durées disponibles (LU)
- Aucune date lue depuis Lever.
- `posted_date` est explicitement `""` (LU: `LeverConnector._normalise_one` passe `""` comme `posted_date`).
- Durée : `None`.
- Source de dates : uniquement la description (parsée par `qualify_offer`).

### Identifiants utilisés (LU)
- `source_id` = `raw["id"]`.
- Identifiant de board : `board_token` ou `site` (regex `_IDENTIFIER`).
- URL validation : host doit être dans `_LISTING_HOSTS["lever"]` = `jobs.lever.co` ou `jobs.eu.lever.co` (LU: `_common_job`).

### Pagination (LU)
- Pagination par `skip`/`limit` query params.
- `build_endpoint` : `?mode=json&skip={offset}&limit={page_size}`.
- `_pages` : boucle jusqu'à `max_pages` (4), arrêt si `len(page) < page_size` ou `offset >= MAX_ROWS` (400).
- MESURÉ : test `test_connectors_bound_page_count_and_validate_employer_identifier` vérifie `max_pages=1`.

### Limites (MESURÉ/LU)
- Taille réponse : 8 MiB max (transport commun).
- Timeout : 8 s par requête.
- Délai entre requêtes : 0.25 s minimum (LU: `_request`).
- `max_pages` borné à `MAX_PAGES=4` (LU: constructeur `PublicATSConnector.__init__`).
- `page_size` borné à `PAGE_SIZE=100`.
- `max_results` borné à `EXPLORATION_MAX_RESULTS=150`.

### Erreurs gérées (LU)
- Transport commun : HTTPError (429 retryable, 5xx retryable, autres codes), URLError/timeout, oversize, invalid JSON.
- `_pages` : si la page n'est pas une liste → `invalid_payload`.
- `_normalise_one` : `KeyError`/`TypeError`/`ValueError` → offre ignorée (invalid_count++).
- `_common_job` : si `source_id` ou `title` manquant → `ValueError` "missing identity". Si URL invalide (host pas dans `_LISTING_HOSTS`) → `ValueError` "missing official URL".

### Risques de faux « conforme » (JUGÉ)
- **Élevé** : aucune date structurée. Même risque que Greenhouse.
- **Modéré** : `descriptionPlain` est du texte brut (pas HTML). Le HTML-escape n'est pas appliqué. Si la description contient du HTML, il sera traité comme texte (moins de risque d'injection, mais perte de structure).
- **Modéré** : `employment_type` = `categories.commitment`. Si Lever expose "Intern" dans commitment, c'est lu. Sinon, inconnu.
- **Faible** : validation URL stricte (host allow-list).

### Tests existants (MESURÉ)
- `tests/test_career_public_ats_connectors.py` : 187 lignes.
- Tests : enregistrement, désactivation par défaut, mapping synthétique, refus si désactivé, validation identifiant, source non vérifiée, timestamp, comptes, URL étrangère refusée.
- Fixtures synthétiques : `tests/fixtures/career_connectors_synthetic.json`.

### Tests manquants (JUGÉ)
- Pas de test avec un flux Lever réel anonymisé.
- Pas de test de pagination multi-page (skip/limit).
- Pas de test de `_common_job` avec `employment_type` manquant.
- Pas de test de la limite `MAX_ROWS=400` pour Lever.
- Pas de test de `posted_date` (toujours vide pour Lever).

---

## 3. Ashby

### Fichiers concernés (LU)
- `career/connectors/public_ats.py` : `AshbyConnector`, `_normalise_one`.
- `career/source_registry.py` : 3 sources ashby (oaknorth, thought-machine, alan).
- `tests/test_career_public_ats_connectors.py`.

### Champs réellement lus (LU, `_normalise_one`)
- `raw["id"]` ou fallback depuis `jobUrl` → `source_id`.
- `raw["title"]` → `title`.
- `raw["jobUrl"]` → `official_url`.
- `raw["applyUrl"]` → `apply_url`.
- `raw["descriptionPlain"]` → `description_original`.
- `raw["address"]["postalAddress"]["addressLocality"]` ou `raw["location"]` → `city`.
- `raw["address"]["postalAddress"]["addressCountry"]` → `country`.
- `raw["employmentType"]` → `employment_type`.
- `raw["publishedAt"]` → `posted_date` (normalisé en date ISO via `datetime.fromisoformat`).
- `deadline_date`, `start_date`, `end_date`, `duration_months` : **non lus** (vides/None).

### Dates et durées disponibles (LU)
- `posted_date` : lu depuis `publishedAt` (format ISO, normalisé).
- `start_date`, `end_date`, `duration_months` : non disponibles dans le flux Ashby (vides/None).
- Source de dates de début/fin : uniquement la description (parsée par `qualify_offer`).

### Identifiants utilisés (LU)
- `source_id` = `raw["id"]` ou fallback depuis le path de `jobUrl`.
- Identifiant de board : `board_token` ou `job_board_name` (regex `_IDENTIFIER`).
- URL validation : host doit être dans `_LISTING_HOSTS["ashby"]` = `jobs.ashbyhq.com`.

### Pagination (LU)
- **Aucune pagination** : un seul GET sur `https://api.ashbyhq.com/posting-api/job-board/{board}`.
- Le flux complet est lu en une requête (tous les jobs listés).
- Filtre : `parse` ignore les items avec `isListed is False`.

### Limites (MESURÉ/LU)
- Taille réponse : 8 MiB max (transport commun).
- Timeout : 8 s par requête.
- Délai entre requêtes : 0.25 s (mais une seule requête).
- `max_pages` : ignoré (pas de pagination, `_pages` retourne une seule page).
- `page_size` : ignoré.

### Erreurs gérées (LU)
- Transport commun.
- `_raw_items` : si `payload` n'est pas un dict avec `jobs` list → `invalid_payload`.
- `_normalise_one` : `KeyError`/`TypeError`/`ValueError` → offre ignorée.
- `_common_job` : validation URL (host allow-list).

### Risques de faux « conforme » (JUGÉ)
- **Modéré** : `publishedAt` donne la date de publication, pas la date de début de stage. Le statut `conforming` dépend du mois de début (extrait de la description ou du titre). Une offre avec `publishedAt` récent mais sans mois de début explicite reste `to_verify`.
- **Modéré** : `employmentType` est lu. Si Ashby expose "Full-time" pour un stage, `classify_internship` peut le classer `confirmed` si "intern" apparaît dans le titre, même si le contrat est full-time. C'est le même risque que Greenhouse.
- **Faible** : validation URL stricte.

### Tests existants (MESURÉ)
- `tests/test_career_public_ats_connectors.py` : tests synthétiques (mapping, désactivation, comptes, URL étrangère).
- Fixtures : `ashby` dans `career_connectors_synthetic.json`.

### Tests manquants (JUGÉ)
- Pas de test avec un flux Ashby réel anonymisé.
- Pas de test de `publishedAt` normalization (date ISO).
- Pas de test de `isListed=False` filtering.
- Pas de test de fallback `source_id` depuis `jobUrl`.
- Pas de test de `address.postalAddress` parsing avec des données réelles.

---

## 4. SmartRecruiters

### Fichiers concernés (LU)
- `career/connectors/public_ats.py` : `SmartRecruitersConnector`, `_normalise_one`.
- `career/source_registry.py` : **aucune source smartrecruiters** (0 source).
- `tests/test_career_public_ats_connectors.py`.

### Champs réellement lus (LU, `_normalise_one`)
- `raw["id"]` → `source_id`.
- `raw["name"]` → `title`.
- `raw["applyUrl"]` ou `raw["ref"]` → `official_url`.
- `raw["applyUrl"]` → `apply_url`.
- `raw["description"]` → `description_original`.
- `raw["location"]["city"]` → `city`.
- `raw["location"]["country"]` → `country`.
- `raw["typeOfEmployment"]["label"]` → `employment_type`.
- `raw["releasedDate"]` → `posted_date` (normalisé via `datetime.fromisoformat`).
- `raw["company"]["name"]` → `company` (fallback : `source.get("company")`).
- `deadline_date`, `start_date`, `end_date`, `duration_months` : **non lus** (vides/None).

### Dates et durées disponibles (LU)
- `posted_date` : lu depuis `releasedDate`.
- `start_date`, `end_date`, `duration_months` : non disponibles dans le flux SmartRecruiters.
- Source de dates de début/fin : uniquement la description.

### Identifiants utilisés (LU)
- `source_id` = `raw["id"]`.
- Identifiant d'entreprise : `company_identifier` ou `board_token` (regex `_IDENTIFIER`).
- URL validation : host doit être dans `_LISTING_HOSTS["smartrecruiters"]` = `www.smartrecruiters.com`, `careers.smartrecruiters.com`, `api.smartrecruiters.com`.
- `official_url` = `applyUrl` ou `ref`. Note : `ref` est une URL API (`api.smartrecruiters.com/...`), pas un lien candidat. **LU: commentaire dans le code** : "The documented list response's `ref` is an official API detail URL; a human apply link is used when a source supplies one directly."

### Pagination (LU)
- Pagination par `offset`/`limit` query params.
- `build_endpoint` : `?limit={page_size}&offset={offset}&destination=PUBLIC`.
- `_pages` : boucle jusqu'à `max_pages` (4), arrêt si `rows < page_size` ou `offset >= total` (totalFound) ou `offset >= MAX_ROWS` (400).
- **MESURÉ** : test `test_smartrecruiters_always_requests_public_destination` vérifie `destination=PUBLIC` dans l'URL.

### Limites (MESURÉ/LU)
- Taille réponse : 8 MiB max (transport commun).
- Timeout : 8 s par requête.
- Délai entre requêtes : 0.25 s minimum.
- `max_pages` borné à `MAX_PAGES=4`.
- `page_size` borné à `PAGE_SIZE=100`.

### Erreurs gérées (LU)
- Transport commun.
- `_raw_items` : si `payload` n'est pas un dict avec `content` list → `invalid_payload`.
- `_normalise_one` : `KeyError`/`TypeError`/`ValueError` → offre ignorée.
- `_common_job` : validation URL.

### Risques de faux « conforme » (JUGÉ)
- **Élevé** : `official_url` peut être une URL API (`ref`), pas un lien candidat cliquable. Le test `test_foreign_posting_url_is_not_admitted` vérifie que les URL étrangères sont refusées, mais une URL API SmartRecruiters (`api.smartrecruiters.com/...`) est acceptée car dans `_LISTING_HOSTS`. Cela peut produire un lien non utilisable pour le candidat.
- **Modéré** : aucune source SmartRecruiters dans le registre curé (0 source). Le connecteur est enregistré et activé dans `default_exploration_connectors`, mais aucune source ne l'utilise. **MESURÉ** : `source_registry.py` ne contient aucun provider `smartrecruiters`.
- **Modéré** : `releasedDate` donne la date de publication, pas la date de début de stage.
- **Faible** : validation URL stricte.

### Tests existants (MESURÉ)
- `tests/test_career_public_ats_connectors.py` : tests synthétiques.
- `test_smartrecruiters_always_requests_public_destination` : vérifie `destination=PUBLIC`.
- Fixtures : `smartrecruiters` dans `career_connectors_synthetic.json`.

### Tests manquants (JUGÉ)
- Pas de source réelle SmartRecruiters dans le registre (0 source curée).
- Pas de test avec un flux SmartRecruiters réel anonymisé.
- Pas de test de `ref` vs `applyUrl` (lien API vs lien candidat).
- Pas de test de `releasedDate` normalization.
- Pas de test de `totalFound` pagination.

---

## Synthèse comparative (JUGÉ)

| Critère | Greenhouse | Lever | Ashby | SmartRecruiters |
|---|---|---|---|---|
| Dates structurées | Aucune | Aucune | `publishedAt` (publication) | `releasedDate` (publication) |
| Durée structurée | Non | Non | Non | Non |
| Date de début | Non | Non | Non | Non |
| Pagination | Non (1 requête) | Oui (skip/limit) | Non (1 requête) | Oui (offset/limit) |
| Limite flux | 20 000 lignes | 400 lignes (MAX_ROWS) | Pas de limite explicite (transport 8 MiB) | 400 lignes (MAX_ROWS) |
| Host validation | `boards-api.greenhouse.io` | `jobs.lever.co`, `jobs.eu.lever.co` | `jobs.ashbyhq.com` | 3 hosts smartrecruiters |
| Source curée | 15 sources | 3 sources | 3 sources | 0 source |
| Risque faux conforme | Élevé (dates depuis description) | Élevé (dates depuis description) | Modéré (publishedAt != début) | Modéré (releasedDate != début) |

## Points communs (LU)

- Tous les connecteurs utilisent `_common_job` qui produit le même schéma normalisé.
- `posted_date` est normalisé via `datetime.fromisoformat` (si présent).
- `start_date`, `end_date`, `duration_months` sont toujours vides/None pour tous les connecteurs.
- La qualification (`qualify_offer`) extrait les dates/durées depuis la description via regex.
- L'URL officielle est validée contre une allow-list de hosts par provider.
- Les connecteurs sont désactivés par défaut (`enabled_by_default = False`).
- `default_exploration_connectors` les active uniquement dans le service (avec sources curées).

## Risques transversaux (JUGÉ)

1. **Aucun connecteur ne fournit de date de début structurée.** Toutes les dates de début sont extraites par regex depuis la description. C'est le principal risque de faux « conforme » : une description bien rédigée peut produire un statut `conforming` sans vérification externe.
2. **Aucun connecteur ne fournit de durée structurée.** La durée est extraite par regex. Une durée mentionnée dans une phrase ambiguë peut être mal interprétée.
3. **`classify_internship` se base sur des regex sur le titre et la description.** Un titre contenant "intern" sans contrat formel peut être classé `confirmed`. C'est un risque de faux positif pour les offres qui mentionnent "intern" dans un contexte non contractuel.
4. **`criteria_admit` rejette les offres `non_conforming` mais laisse passer les `to_verify`.** Une offre avec un mois de début inconnu est `to_verify` et peut être retenue si elle passe les critères de domaine/localisation. C'est volontaire (conservateur) mais peut inclure des offres non vérifiables.
5. **Greenhouse n'a pas de pagination.** Un board avec > 20 000 entrées est rejeté (`too_many_rows`). Un board avec 15 000 entrées est entièrement chargé en mémoire (8 MiB max).
6. **Ashby n'a pas de limite de lignes explicite.** Seule la limite de 8 MiB du transport s'applique. Un flux Ashby très volumineux pourrait consommer jusqu'à 8 MiB.

## Tests manquants transversaux (JUGÉ)

- Test de bout en bout avec un flux réel anonymisé pour chaque provider.
- Test de la limite `GREENHOUSE_MAX_FEED_ROWS` (20 000).
- Test de la limite `MAX_ROWS` (400) pour Lever et SmartRecruiters.
- Test de retry sur 429/503 pour Greenhouse.
- Test de `_explicit_employment_type` avec metadata Greenhouse réels.
- Test de `_location_parts` avec des localisations multi-villes réelles.
- Test de `publishedAt`/`releasedDate` normalization avec des données réelles.
- Test de `isListed=False` filtering pour Ashby.
- Test de `ref` vs `applyUrl` pour SmartRecruiters.
- Test de la pagination multi-page pour Lever et SmartRecruiters.

## NON VÉRIFIÉ

- La disponibilité réelle des endpoints ATS n'a pas été testée (aucun appel réseau).
- La structure réelle des réponses ATS n'a pas été validée contre la documentation officielle (seules les fixtures synthétiques sont utilisées).
- Le comportement des connecteurs avec des données réelles (champs manquants, formats inattendus) n'a pas été mesuré.
- La performance des connecteurs avec des flux volumineux n'a pas été mesurée.

---

Rapport produit sans modification de code. Aucun appel réseau. Aucune donnée personnelle.