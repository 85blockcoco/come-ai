# Registre d'employeurs finance — analyse de couverture

- **Mission** : analyser les employeurs connus à partir des fichiers existants, les classer par
  nature, qualifier leur preuve et leur risque d'inexactitude, et proposer 50 employeurs finance
  à vérifier ultérieurement.
- **Mode** : lecture seule. Aucun appel réseau, aucun changement dans
  `career/source_registry.py`, aucun ajout de source, aucun code de production modifié.
- **Base observée** : branche `audit/total-v3-2026-10-14` @ `fb46fcf`.
- **Sources de l'analyse** : `career/source_registry.py`, `career/connectors/`,
  `career/exploration.py`, `career/offer_qualification.py`, `career/service.py`,
  `scripts/live_source_check.py`, les trois instantanés
  `docs/career_intl/LIVE_SOURCE_CHECK_2026-10-18_*.json`, les rapports `docs/career_intl/*.md`,
  `docs/career_intl/agents/*.md`, `docs/agent-reports/*.md`, plus les catalogues evidence
  inertes et les rapports de sources présents dans les worktrees voisins
  (`AI-Excel-Agent-mission-03/31/46/47/48/49`, `AI-Excel-Agent-SRC-EUR/UKMEA/AMAP/INST`).
- **Preuve de non-modification** : `career/source_registry.py` SHA-256
  `f2098bf4375d6671ab590e07722c1016d9ef0172a3a10c418cadf4efdf294477` avant et après la mission ;
  21 entrées, identique au début et à la fin.

## Convention de preuve

| Marque | Signification |
|---|---|
| `LU` | lu dans le code ou un fichier du dépôt, avec emplacement |
| `MESURÉ` | vérifié par exécution dans cette session (aucun réseau) |
| `JUGÉ` | analyse de l'auditeur, déduction non prouvée |
| `NON VÉRIFIÉ` | ni testé ni lu ici ; aucune affirmation de vérité |

Aucun fait réseau n'est réutilisé comme preuve neuve : les statuts HTTP cités sont ceux
**enregistrés dans les rapports existants** à leur date, pas une observation de cette session.

---

## 1. Résumé exécutif

1. Le registre actif contient **21 sources** : 15 Greenhouse, 3 Lever, 3 Ashby, 0 SmartRecruiters
   (`LU`, `career/source_registry.py`).
2. **Aucune institution** n'est au registre. Les deux institutions les mieux documentées du dépôt
   (BCE, Groupe Banque mondiale) n'utilisent aucun ATS public : elles sont hors du modèle actuel.
3. **4 employeurs sur 21 sont hors finance** (Doctolib, Pigment, Contentsquare, Dataiku) et
   **1 est ambigu** (Thought Machine). Le registre n'est donc pas un registre « finance » : c'est un
   registre « ATS public atteignable », avec 5 entrées qui ne relèvent pas du secteur recherché.
4. **Toutes les 21 sources ont été lues avec succès** le 18/10/2026
   (`LIVE_SOURCE_CHECK_2026-10-18_WAVE2_FINAL.json`, 21/21 succès, 0 échec), mais **9 d'entre elles
   ont produit zéro offre retenue** : l'accès au flux ne dit rien de la couverture métier.
5. **Aucune source ne fournit de date de début ni de durée structurée.** Les dates ne peuvent venir
   que du texte libre de l'annonce. Sur les 45 offres retenues, **43 sont « à vérifier »** et
   **2 seulement sont conformes** ; 45/45 n'ont ni date de début, ni date de fin, ni langue.
6. **Le pays n'est pas une donnée du registre.** `CURATED_SOURCES` n'a pas de champ pays ; le champ
   `country` n'existe qu'au niveau de l'offre, et il manque sur 19 des 45 offres retenues.
7. **Le plafond `EXPLORATION_MAX_SOURCES = 24` est un plafond d'ordre, pas de volume** : le service
   parcourt `registry[:24]` et marque `not_queried` tout ce qui suit. **Ajouter 50 employeurs sans
   revoir ce plafond les rendrait invisibles** : ils seraient listés mais jamais consultés.

---

## 2. Cartographie du registre actif

### 2.1 Répartition par fournisseur et connecteur

| Fournisseur | Entrées | Connecteur (`LU`) | Statut réel | Limites structurelles (`LU`) |
|---|---:|---|---|---|
| Greenhouse | 15 | `career/discovery.py::GreenhouseJobBoardConnector` | actif par défaut, aucun verrou `enabled` | pas de pagination (1 GET), `GREENHOUSE_MAX_FEED_ROWS = 20 000`, `GREENHOUSE_MAX_JOBS = 150`, `GREENHOUSE_MAX_TIMEOUT = 8 s`, 8 Mio |
| Lever | 3 | `career/connectors/public_ats.py::LeverConnector` | `enabled_by_default = False` ; activé **uniquement** via `default_exploration_connectors()` après clic explicite | pagination `skip/limit`, 4 pages max, 400 lignes max |
| Ashby | 3 | `career/connectors/public_ats.py::AshbyConnector` | idem | **aucune pagination** (1 GET, flux non paginé), seul `publishedAt` est lu |
| SmartRecruiters | **0** | `career/connectors/public_ats.py::SmartRecruitersConnector` | enregistré et activé dans la map du service, mais **aucune source au registre** → jamais appelé | `ref` peut être une URL d'API et non un lien candidat |

`career/connectors/__init__.py` crée les trois connecteurs publics avec `enabled=True`, mais
seulement dans la carte du service ; une construction directe de `LeverConnector()` /
`AshbyConnector()` / `SmartRecruitersConnector()` les laisse désactivés.

### 2.2 Incohérence de contrat à connaître avant toute extension

- `career/service.py` : `local_capabilities()` annonce `"providers": ["greenhouse"]` alors que la
  carte d'exploration contient `greenhouse`, `lever`, `ashby`, `smartrecruiters` (`LU`). Le rapport
  de capacité sous-déclare les connecteurs réellement câblés.
- `career/service.py` : la table SQLite `discovery_sources` porte
  `CHECK (provider IN ('greenhouse'))` (deux occurrences, lignes ~424 et ~625) et
  `create_discovery_source()` force `'greenhouse'`. Conséquence : un board **Lever/Ashby
  personnel** ne peut pas être enregistré, alors que les **sources curées** Lever/Ashby sont bien
  lues à l'exploration. Les deux chemins n'ont pas le même contrat.

---

## 3. Classification des 21 employeurs du registre

Légende des colonnes :

- **Pays** : `non stocké` = aucun champ pays dans le registre ; la valeur n'est **pas** déduite du
  nom ni du domaine. Les quelques signaux disponibles sont notés à part.
- **Preuve officielle** : présence d'une `provenance_url` HTTPS datée dans le registre, et existence
  d'une re-vérification indépendante déjà consignée dans le dépôt.
- **Connecteur** : fournisseur et état du connecteur au moment de l'analyse.
- **Risque** : `élevé` / `moyen` / `faible`, justifié en §5.

### 3.1 Banque

| Nom | Pays | Recrutement | Preuve officielle | Connecteur | Risque |
|---|---|---|---|---|---|
| OakNorth | non stocké | Ashby `oaknorth` | présente : `https://www.oaknorth.com/careers/` @ 2026-10-18T12:41:15Z ; lue 21 annonces brutes, 1 retenue | Ashby, actif via clic ; aucune pagination | élevé |
| Monzo | non stocké | Greenhouse `monzo` | présente : `https://monzo.com/careers/` @ 2026-10-18T12:41:15Z ; **re-vérifiée indépendamment** par M49 (GET 200, token `monzo` trouvé dans la page officielle, flux 200, 71 annonces) | Greenhouse, actif ; 0 offre retenue au dernier contrôle | moyen |

### 3.2 Gestion d'actifs

| Nom | Pays | Recrutement | Preuve officielle | Connecteur | Risque |
|---|---|---|---|---|---|
| Schonfeld | non stocké | Greenhouse `schonfeld` | présente : `https://www.schonfeld.com/careers/` @ 2026-10-13T22:06:00Z ; 69 annonces brutes, **12 retenues (plus gros volume du registre)** | Greenhouse | moyen |
| Point72 | non stocké | Greenhouse `point72` | présente : `https://careers.point72.com/` @ 2026-10-13T22:06:01Z ; 221 brutes, 3 retenues | Greenhouse | moyen |
| Qube Research & Technologies | non stocké | Greenhouse `quberesearchandtechnologies` | présente : `https://www.qube-rt.com/careers/` @ 2026-10-13T22:08:35Z ; 199 brutes, 1 retenue | Greenhouse | élevé |
| Flow Traders | non stocké | Greenhouse `flowtraders` | présente : `https://www.flowtraders.com/careers/job-search/` @ 2026-10-13T22:08:34Z ; 47 brutes, 2 retenues | Greenhouse | élevé |
| XTX Markets | non stocké | Greenhouse `xtxmarketstechnologies` | présente : `https://www.xtxmarkets.com/careers/` @ 2026-10-13T22:08:00Z ; **7 brutes, 0 retenue** | Greenhouse | élevé |
| Optiver | non stocké (suffixe `us` du board ≠ pays) | Greenhouse `optiverus` | présente : page de candidature d'un stage **Singapore** ; 164 brutes, 9 retenues | Greenhouse | élevé |
| Man Group | non stocké (board servi par `job-boards.eu.greenhouse.io`) | Greenhouse `mangroup` | présente : `https://www.man.com/careers` @ 2026-10-18T10:14:39Z ; 57 brutes, 5 retenues | Greenhouse | moyen |
| AQR | non stocké | Greenhouse `aqr` | présente : `https://careers.aqr.com/` @ 2026-10-18T10:14:39Z ; 56 brutes, **0 retenue** | Greenhouse | élevé |
| General Atlantic | non stocké | Greenhouse `generalatlantic` | présente : `https://www.generalatlantic.com/careers/` @ 2026-10-18T10:14:39Z ; 13 brutes, **0 retenue** | Greenhouse | élevé |

### 3.3 Assurance

| Nom | Pays | Recrutement | Preuve officielle | Connecteur | Risque |
|---|---|---|---|---|---|
| Alan | non stocké | Ashby `alan` | présente : `https://alan.com/careers` @ 2026-10-18T12:41:15Z ; 125 brutes, 2 retenues | Ashby, actif ; `employmentType` = `Full-time` sur des postes « Sales Planning & Strategy » présentés comme permanents | élevé |

**Alan est la seule assurance du registre.** C'est un trou structurel : le secteur assurance/actuarial
est explicitement absent du registre alors qu'il fait partie des domaines financiers cherchés.

### 3.4 Fintech

| Nom | Pays | Recrutement | Preuve officielle | Connecteur | Risque |
|---|---|---|---|---|---|
| Qonto | non stocké (provenance `/fr/careers`, indice faible) | Lever `qonto` | présente : `https://qonto.com/fr/careers` @ 2026-10-18T10:14:39Z ; 53 brutes, **0 retenue** | Lever, actif via clic | élevé |
| Robinhood | non stocké | Greenhouse `robinhood` | présente : `https://careers.robinhood.com/` @ 2026-10-18T10:14:39Z ; 152 brutes, 1 retenue (MBA Intern, Robinhood Ventures) | Greenhouse | moyen |

### 3.5 Conseil

| Nom | Pays | Recrutement | Preuve officielle | Connecteur | Risque |
|---|---|---|---|---|---|
| Lincoln International | non stocké | Greenhouse `lincolninternational` | présente : page campus @ 2026-10-14T08:33:28Z ; 42 brutes, 5 retenues, **1 des 2 offres « conformes » du registre** | Greenhouse | moyen |
| AlixPartners | non stocké | Greenhouse `alixpartners` | présente : page de candidature d'un poste précis @ 2026-10-14T08:33:29Z ; 115 brutes, 3 retenues | Greenhouse | moyen |

### 3.6 Institution

**Néant.** Aucune institution n'est au registre. Les institutions présentes dans le dépôt
(ECB, World Bank Group, EIB, EBRD, BIS, IMF, ESMA, AMF, ADB, AfDB, IDB, Banque de France,
Bank of England — `REPORT_SRC-INST.md` du worktree `AI-Excel-Agent-SRC-INST`) publient sur des
portails propriétaires, sans ATS Greenhouse/Lever/Ashby/SmartRecruiters. Le modèle actuel
(`CURATED_SOURCES` = couple ATS + token) **ne peut pas les représenter**. C'est une limite
d'architecture, pas un manque de candidates.

### 3.7 Hors finance

| Nom | Pays | Recrutement | Preuve officielle | Connecteur | Risque |
|---|---|---|---|---|---|
| Doctolib | non stocké | Greenhouse `doctolib` | présente : `https://careers.doctolib.com/jobs/` @ 2026-10-18T12:41:15Z ; 149 brutes, 1 retenue (« Stage – Consolidation et Contrôle financier, janvier 2027 », conforme) | Greenhouse | moyen |
| Pigment | non stocké | Lever `pigment` | présente : `https://www.pigment.com/careers` @ 2026-10-18T12:41:15Z ; 140 brutes, **0 retenue** | Lever | élevé |
| Contentsquare | non stocké | Lever `contentsquare` | présente : `https://contentsquare.com/careers/` @ 2026-10-18T12:41:15Z ; 21 brutes, **0 retenue** | Lever | élevé |
| Dataiku | non stocké | Greenhouse `dataiku` | présente : `https://www.dataiku.com/careers/` @ 2026-10-18T12:41:15Z ; 13 brutes, **0 retenue** | Greenhouse | élevé |

Ces quatre entrées occupent des places de consultation, des quotas de pagination et du budget
réseau pour des employeurs dont le métier principal n'est pas la finance. Seul Doctolib a produit
une offre financière réelle, et c'est un stage de consolidation comptable, pas un métier de marché.

### 3.8 Ambigu

| Nom | Pays | Recrutement | Preuve officielle | Connecteur | Risque |
|---|---|---|---|---|---|
| Thought Machine | non stocké | Ashby `thought-machine` | présente : `https://www.thoughtmachine.net/careers` @ 2026-10-18T12:41:15Z ; 40 brutes, **0 retenue** | Ashby | élevé |

Thought Machine édifie de la technologie de décision/exécution pour marchés financiers. Ce n'est ni
un établissement financier, ni un éditeur hors finance classique. La qualification « finance » d'une
offre chez Thought Machine doit être jugée sur le contenu du poste, jamais sur l'employeur.

### 3.9 Synthèse de la classification

| Catégorie | Nombre | Employeurs |
|---|---:|---|
| Banque | 2 | OakNorth, Monzo |
| Gestion d'actifs | 9 | Schonfeld, Point72, Qube RT, Flow Traders, XTX Markets, Optiver, Man Group, AQR, General Atlantic |
| Assurance | 1 | Alan |
| Fintech | 2 | Qonto, Robinhood |
| Conseil | 2 | Lincoln International, AlixPartners |
| Institution | **0** | — |
| Hors finance | 4 | Doctolib, Pigment, Contentsquare, Dataiku |
| Ambigu | 1 | Thought Machine |
| **Total** | **21** | |

**Aucune grande banque universelle ni aucune banque d'affaires française n'est au registre** :
ni BNP Paribas, ni Société Générale, ni Crédit Agricole, ni Goldman Sachs, ni JPMorgan. C'est le
manque le plus lourd de la couverture.

---

## 4. Employeurs documentés hors registre (constat, pas ajout)

Ces employeurs sont nommés et documentés dans des fichiers du dépôt, mais **ne sont pas** dans
`CURATED_SOURCES`. Ils sont listés ici pour que la couverture soit lisible ; aucune proposition
d'ajout n'est formulée ici.

| Employeur | Où il est documenté | Plateforme observée | État de la preuve |
|---|---|---|---|
| Goldman Sachs | M03, M31, M47 | `higher.gs.com` (application Next.js, rendu client) | page carrière 200, **0 offre dans le HTML** |
| JPMorgan Chase | M03, M31, M47 | Oracle Cloud HCM (`jpmc.fa.oraclecloud.com`) | page 200, portail lié mais non lu (budget exhausted) |
| Morgan Stanley | M03, M31, M47, C50-06 | `morganstanley.eightfold.ai` **et** Workday `ms.wd5.myworkdayjobs.com/External` | Workday GET 200 ; listing = POST, non testé |
| Barclays | M03, M31, M47, M50 | Radancy/TalentBrew (company 13015) | 10 offres visibles dans le HTML |
| Citi | M31, M47 | Radancy/TalentBrew (company 287) | 15 offres visibles ; 15 offres finance documentées mais **0 stage prouvé** |
| HSBC | M03, M47, M50 | `portal.careers.hsbc.com` (rendu client) | page 200, 0 offre en HTML |
| UBS | M03, M31, M46, M50 | BrassRing (`jobs.ubs.com/TGnewUI/...`, 17 occurrences `brassring`) | 0 empreinte Workday ; SPA |
| Deutsche Bank | M03, M46, C50-06 | `careers.db.com/cross/search` + Workday `db.wd3.../DBWebsite` | coquille 200 ; **GET sur le listing = HTTP 400**, listing = POST non documenté officiellement |
| BNP Paribas | M03, M31, M46 | Taleo (`bwelcome.hr.bnpparibas`) | 289 offres / 20 localités avec filtre Trainee ; 13 offres documentées ; M03 note la page groupe en 404 |
| Société Générale | M03, M31, M46 | Taleo (`socgen.taleo.net`) | pages détail OK, racine `/job-offers` en 404 |
| Crédit Agricole (CIB) | M03, M31, M46 | — | sous-domaines `careers/jobs.credit-agricole-cib.com` en **NXDOMAIN** |
| Rothschild & Co | M03, M46 | Workday `rothschildandco.wd3.../Rothschildandco_Lateral` | 111 résultats avec filtre Internships ; rendu SPA |
| BlackRock | M03 (hors catalogue), M48, M50 | TalentBrew | **15 offres finance documentées** (Londres, New York, Hong Kong), dates non prouvées |
| Amundi | M03 (hors catalogue), M48, M50 | `jobs.amundi.com` | 6 offres Luxembourg/Paris ; une porte une date de début `04/01/2027` |
| Allianz | M48 | Phenom (`career5.successfactors.eu`) | 3 offres documentées ; `employmentType` = `Permanent` sur un titled « Internship » |
| AXA Investment Managers | M48 | — | `301` vers `bnpparibas-am.com` (hors allow-list), non suivi |
| Ardian | M48 | — | chemin carrière deviné = **404** |
| Eurazeo | M48 | — | chemin carrière deviné = **404** |
| Alpha FMC | M49 | Greenhouse `alphafmcrolesearlycareers` + `alphafmcroles` | **seule source M49 recommandée pour patch registre** : 3 stages retenus, 0 strict |
| FT Partners | M49 | — | page officielle 200 **sans lien ATS** ; board `financialtechnologypartners vu par M31 non rattaché → refusé |
| GCM Grosvenor | M49 | — | page carrière **403** (anti-bot), aucun contournement tenté |
| Houlihan Lokey | M49 | — | **échec TLS**, nom SNI non reconnu |
| Gemini | M49 | — | page 200 rendue côté client, aucun lien ATS dans le HTML |
| Squarepoint | M49, SRC-EUR, SRC-AMAP | Greenhouse `squarepointcapital` (observé) | **domaine apex en page de parking** → provenance non prouvable en l'état |
| Coinbase / Stripe / Airwallex / Moniepoint / LionTree | registre de la base `0e42068` (branche du pack C50), non.porté sur la base courante | Greenhouse (4), Ashby (Airwallex) | registry historique ; C50-01 : Coinbase et Moniepoint **403** sur la page carrière, LionTree provenance **404** |
| Adyen / CVX / Trade Republic / Mollie | `README_CAREER_EXPLORER.md` | — | explicitement **non ajoutés** : preuve de rattachement au board absente ou flux vide |
| ECB / World Bank Group | SRC-INST | portail propriétaire (`talent.ecb.europa.eu`) | programmes vérifiés (durée, éligibilité, calendrier), **aucun ATS public** |
| Baird | C50-06, M50 | Workday `rwbaird.wd1.myworkdayjobs.com/careers` | **500 page de maintenance** Workday au 17/10 ; instabilité observée |

---

## 5. Risques d'inexactitude mesurés

### 5.1 Risques transversaux (MESURÉ sur les instantanés du 18/10)

| # | Risque | Mesure | Conséquence |
|---|---|---|---|
| R1 | **Aucune date de début ni durée structurée** | `start_date`, `end_date`, `duration_months` = `""`/`None` pour les 4 connecteurs (`discovery.py`, `public_ats.py`) ; les seules sources de dates sont des regex sur le texte libre | Un statut `conforming` repose sur une phrase d'annonce, pas sur un champ source |
| R2 | **Dates presque toujours absentes** | 45/45 offres retenues : `début` et `fin` manquants ; `mois de début` absent sur 41 ; `durée` absente sur 29 ; `publication` absente sur 42 | 43/45 en `to_verify` |
| R3 | **Pays non disponible** | `pays` manquant sur 19/45 ; le registre n'a aucun champ pays ; `criteria_admit` refuse d'inférer un pays depuis une ville | Aucun filtrage géographique fiable ; `localisation` ne peut pas être prouvée |
| R4 | **Langue jamais lue** | `langue` manquante sur 45/45 ; `languages_required` non alimenté par les connecteurs ATS publics | Une offre multilingue n'est pas distinguée |
| R5 | **Doublons de titre** | 5 paires de titres identiques avec des URL différentes : Man Group (×2), Optiver (×2), Alan (×2), Schonfeld (×2) | Le dédoublonnage est par URL canonique : deux postes réels au même titre restent deux cartes |
| R6 | **URL officielles non HTTPS** | les 5 URLs Lincoln International du registre sont en `http://` (`.../greenhouse?gh_jid=...`) ; `canonical_url` accepte `http` | Lien candidat en clair |
| R7 | **Le nom d'entreprise vient du registre, pas du flux** | `company = board.company` (Greenhouse) / `source.get("company")` (ATS publics) | Un board recyclé, revendu ou renommé attribue ses offres au mauvais employeur, silencieusement |
| R8 | **SmartRecruiters : `ref` peut être une URL d'API** | `official_url` = `applyUrl` **ou** `ref` (`api.smartrecruiters.com/...`) | Un lien non candidat peut être présenté comme lien de candidature |
| R9 | **Le « confirmed » du flux n'est pas une preuve métier** | Doctolib : 20 internships confirmés au niveau source, **1 seule** retenue après filtre finance ; Alan : 2 `confirmed` qui sont des postes **permanents** | Confondre `confirmed_count` (niveau source) avec une offre retenue finance |
| R10 | **Incohérence de capacité déclarée** | `local_capabilities().discovery.providers == ["greenhouse"]` alors que 4 providers sont câblés | Un rapport de capacité sous-estime la couverture réelle |
| R11 | **Plafond d'ordre, pas de volume** | `EXPLORATION_MAX_SOURCES = 24`, parcours `registry[:24]`, suites marquées `not_queried` | **50 ajoutés = 26 jamais consultés** |
| R12 | **Budget réseau partagé** | `EXPLORATION_NETWORK_BUDGET_SECONDS = 60` ; 21 sources lues en ~35 s (34,16 s entre la 1ʳᵉ et la 21ᵉ lecture) | ~3 s/source : le budget, pas le plafond, limite d'abord |
| R13 | **Contrat SQLite divergent** | `discovery_sources.provider CHECK IN ('greenhouse')` + `create_discovery_source` forcé à `'greenhouse'` | Un board personnel Lever/Ashby est impossible alors que les sources curées de ces providers sont lues |
| R14 | **Sources muettes** | 9 sources à 0 offre retenue : XTX Markets, AQR, General Atlantic, Qonto, Pigment, Monzo, Thought Machine, Contentsquare, Dataiku | Une source « qui marche » peut ne rien apporter ; distinction nécessaire dans tout reporting |

### 5.2 Risque par employeur (registre actif)

| Employeur | Niveau | Motif principal |
|---|---|---|
| XTX Markets | élevé | 0 retenue sur 7 annonces ; source sans valeur mesurée |
| AQR | élevé | 0 retenue sur 56 annonces |
| General Atlantic | élevé | 0 retenue sur 13 annonces |
| Qonto | élevé | 0 retenue sur 53 annonces |
| Pigment | élevé | 0 retenue sur 140 annonces |
| Thought Machine | élevé | 0 retenue sur 40 annonces ; secteur ambigu |
| Contentsquare | élevé | 0 retenue sur 21 annonces ; hors finance |
| Dataiku | élevé | 0 retenue sur 13 annonces ; hors finance |
| Qube RT | élevé | 1 retenue, `fixed_term` (« Reference Data Business Analyst »), pas un stage |
| Flow Traders | élevé | 2 retenues, toutes « Summer 2027 » sans mois de début ni durée |
| Optiver | élevé | 9 retenues dont 2 en contrat `ambiguous` (PhD) ; board `optiverus` et provenance « Singapore » : risque de lire un pays dans un suffixe |
| Alan | élevé | `employmentType = Full-time` ; les 2 offres retenues sont des postes permanents « Sales Planning & Strategy » ; **seule assurance du registre** |
| OakNorth | élevé | 1 retenue, « Industrial Training – Finance », 12 mois : formation, pas stage |
| Schonfeld | moyen | 12 retenues (dont 2 doublons de titre) ; 11/12 avec pays, mais dates et durées absentes |
| Point72 | moyen | 3 retenues, dont un poste `permanent` (Research Fellow) |
| Man Group | moyen | board servi par l'hôte `eu` alors que le registre déclare l'hôte standard ; 2 doublons de titre |
| Monzo | moyen | 0 retenue malgré 71 annonces ; provenance solide (re-vérifiée M49) |
| Robinhood | moyen | 1 retenue sur 152, pays absent, catégorie « venture » plutôt que gestion d'actifs |
| AlixPartners | moyen | 3 retenues `to_verify`, pays absent sur les 3 |
| Lincoln International | moyen | seule source conforme, mais URLs `http://` et provenance = page campus (pas la page board) |
| Doctolib | moyen | seul stage financier conforme du registre, mais employeur hors finance |

---

## 6. Lacunes de couverture par catégorie

| Catégorie attendue | Couverture registre | Lacune |
|---|---|---|
| Banque universelle | 0 | Goldman Sachs, JPMorgan, Morgan Stanley, Barclays, Citi, HSBC, UBS, Deutsche Bank — tous documentés hors registre, tous sur plateformes non couvertes |
| Banque française | 0 | BNP Paribas, Société Générale, Crédit Agricole — Taleo non couvert |
| Banque d'affaires / boutique | 0 | Rothschild & Co (Workday), Lazard, Evercore (non Atlantiques) |
| Gestion d'actifs classique | 4 | AQR et General Atlantic à 0 retenue ; Man Group OK |
| Gestion d'actifs quantitative | 5 | Qube RT, Flow Traders, XTX, Optiver : très peu de stages prouvés avec dates |
| Assurance | 1 | **seul Alan**, et ses offres retenues ne sont pas des stages |
| Conseil | 2 | pas de boutique française ni de conseil Big Four financier |
| Fintech | 2 | Qonto à 0 retenue ; Robinhood marginal |
| Private Equity | 1 | General Atlantic, 0 retenue ; aucune autre entrée |
| Institution | **0** | limite d'architecture (portails propriétaires) |
| Audit financier | 0 | aucun employeur du registre ne publie d'audit ; domaine de recherche sans source dédiée |

---

## 7. Liste de 50 employeurs finance à vérifier ultérieurement

> **Cette liste est une proposition de vérification, pas une modification du registre.**
> Aucun `board_token` n'est deviné. Aucun employeur de cette liste n'est ajouté à
> `CURATED_SOURCES`. Les colonnes « ATS observé » et « pays » reprennent uniquement ce que les
> fichiers existants ont constaté ; « non établi » signifie que le dépôt ne dit rien.
> Chaque ligne exige, avant toute proposition d'ajout : (a) page carrière officielle lue en GET
> borné, (b) lien **employeur → board** demonstrable dans le HTML de la page officielle,
> (c) réponse publique réelle du board, (d) exécution du connecteur existant sur cette réponse,
> (e) relecture du plafond `EXPLORATION_MAX_SOURCES` et du budget 60 s.

### 7.1 Banques (14)

| # | Employeur | Pays (déclaré par la source du dépôt) | ATS observé | Preuve actuelle dans le dépôt | Action de vérification |
|---:|---|---|---|---|---|
| 1 | Goldman Sachs | US (M03) | `higher.gs.com`, rendu client | page 200, 0 offre HTML | obtenir le board officiel et un flux lisible |
| 2 | JPMorgan Chase | US (M03) | Oracle Cloud HCM | page 200, portail lié non lu | qualifier le portail ou déclarer non exploitable |
| 3 | Morgan Stanley | US (M03) | Eightfold + Workday `ms.wd5` | Workday 200 ; listing POST | trancher Eightfold (non documenté) vs Workday (POST) |
| 4 | Barclays | GB (M03) | Radancy/TalentBrew (13015) | 10 offres HTML | exposer un flux public ou classer manuel |
| 5 | Citi | US (M47) | Radancy/TalentBrew (287) | 15 offres, 0 stage prouvé | isoler un stage avec dates |
| 6 | HSBC | GB (M03) | portail `portal.careers.hsbc.com` rendu client | page 200 | idem |
| 7 | UBS | CH (M03) | BrassRing `jobs.ubs.com` | 200, 1,83 Mio HTML, 0 empreinte Workday | lire la recherche BrassRing |
| 8 | Deutsche Bank | DE (M03) | `careers.db.com` + Workday `db.wd3` | GET listing = **400** | obtenir la preuve de l'endpoint public ou abandonner |
| 9 | BNP Paribas | FR (M03/M46) | Taleo `bwelcome.hr.bnpparibas` | 289 offres, filtre Trainee | valider le lien groupe → portail Taleo |
| 10 | Société Générale | FR (M03/M46) | Taleo `socgen.taleo.net` | pages détail OK | valider la page de recherche, pas la racine |
| 11 | Crédit Agricole (CIB) | FR (M03/M46) | inconnu | sous-domaines **NXDOMAIN** | localiser le point d'entrée officiel réel |
| 12 | Nomura | JP (M03) | Oracle Taleo (signature partielle) | page 200 | confirmer la signature avant tout adaptateur |
| 13 | Mizuho | JP (M03) | — | échec DNS/TLS/301 | re-tenter une fois, puis classer non couvert |
| 14 | Bank of China Luxembourg | LU (SRC-EUR) | SmartRecruiters `BankOfChinaLuxembourg` | candidat **NON VÉRIFIÉ** | vérifier page officielle + flux SmartRecruiters |

### 7.2 Conseil (7)

| # | Employeur | Pays | ATS observé | Preuve actuelle | Action |
|---:|---|---|---|---|---|
| 15 | Rothschild & Co | GB (M03) | Workday `rothschildandco.wd3` | 111 résultats Internships, SPA | établir la méthode POST Workday ou classer manuel |
| 16 | Lazard | US (M03) | inconnu | page carrière 200 | trouver le point d'entrée automatique |
| 17 | Evercore | US (M03) | inconnu | page carrière 200 | idem |
| 18 | Alpha FMC | GB (M49) | Greenhouse `alphafmcrolesearlycareers` | **recommandé par M49** : 7 annonces, 3 stages retenus | seul candidat Greenhouse réellement prêt ; à revoir avec le reste du lot |
| 19 | GCM Grosvenor | US (M49) | — | page carrière **403** | vérifier en navigateur humain, aucun contournement |
| 20 | Houlihan Lokey | US (M49) | — | échec TLS (SNI) | retester le TLS ; ne pas forcer |
| 21 | FT Partners | US (M49) | board `financialtechnologypartners` vu par M31, **non rattaché** | page 200 sans lien ATS | obtenir le lien depuis la page officielle, sinon refuser |

### 7.3 Gestion d'actifs et assurance (8)

| # | Employeur | Pays | ATS observé | Preuve actuelle | Action |
|---:|---|---|---|---|---|
| 22 | BlackRock | US/GB (M48) | TalentBrew `careers.blackrock.com` | **15 offres documentées** (Londres, New York, HK) | qualifier le flux TalentBrew ;extraire les dates |
| 23 | Amundi | FR/LU (M48) | `jobs.amundi.com`, plateforme non identifiée | 6 offres, une avec début `04/01/2027` | identifier la plateforme, puis lire le flux |
| 24 | Allianz | DE (M48) | Phenom `career5.successfactors.eu` | 3 offres ; `employmentType = Permanent` sur un titre Internship | trancher le conflit contrat/titre |
| 25 | AXA Investment Managers | FR (M48) | — | `301` hors allow-list, non suivi | relire la cible de redirection manuellement |
| 26 | Ardian | FR (M48) | — | chemin deviné **404** | retrouver la page carrière réelle |
| 27 | Eurazeo | FR (M48) | — | chemin deviné **404** | idem |
| 28 | Baird | US (C50-06/M50) | Workday `rwbaird.wd1` | **500 maintenance** au 17/10 | recontrôler la stabilité du tenant |
| 29 | Credit Suisse | CH (M31) | — | catalogue M31 : `inactive`, fusionné avec UBS | **ne pas rouvrir** ; garder la trace historique uniquement |

### 7.4 Fintech (14)

| # | Employeur | Pays | ATS observé | Preuve actuelle | Action |
|---:|---|---|---|---|---|
| 30 | Coinbase | US (C50-01) | Greenhouse `coinbase` | board 200 / 226 annonces, page carrière **403** | re-vérifier la provenance en navigateur humain |
| 31 | Stripe | US (C50-01) | Greenhouse `stripe` | board 200 / 732 annonces, page 200 | seule source historique à 0 signal croisé roto |
| 32 | Airwallex | non établi (C50-01) | Ashby `airwallex` | board 200, payload > 3 Mio (plafond d'audit) | rejouer avec le plafond applicatif 8 Mio |
| 33 | Moniepoint | non établi (C50-01) | Greenhouse `moniepoint` | board 200 / 158 annonces, page carrière **403** | idem Coinbase |
| 34 | Adyen | NL (README) | — | explicitement **non ajouté** | obtenir la preuve employeur → board |
| 35 | Trade Republic | DE (README) | — | explicitement **non ajouté** | idem |
| 36 | Mollie | NL (README) | Ashby (hors connecteur au moment du lot) | mentionné sans preuve complète | vérifier l'Ashby board et son rattachement |
| 37 | CVX | — (README) | — | non ajouté, non expliqué | clarifier l'identité de l'employeur avant toute action |
| 38 | Gemini | US (M49) | — | page 200 client-side, aucun lien ATS | idem FT Partners |
| 39 | Binance | HK (SRC-AMAP) | Lever `binance` | candidat **NON VÉRIFIÉ** (résultat de recherche) | vérifier page officielle + flux |
| 40 | Animoca Brands | HK (SRC-AMAP) | Lever `animocabrands` | candidat **NON VÉRIFIÉ** | idem |
| 41 | Amber Group | HK (SRC-AMAP) | Lever `ambergroup` | candidat **NON VÉRIFIÉ** | idem |
| 42 | Revaia | FR (SRC-EUR) | SmartRecruiters `Revaia` | candidat **NON VÉRIFIÉ** | idem |
| 43 | Satispay | IT (SRC-EUR) | Ashby `satispay` | candidat **NON VÉRIFIÉ** | idem |

### 7.5 Institutions (7) — hors modèle actuel

| # | Institution | Pays | Système | Preuve actuelle | Action |
|---:|---|---|---|---|---|
| 44 | BCE | zone euro (SRC-INST) | portail `talent.ecb.europa.eu` | programme traineeship **vérifié** (durée 3-6 mois extensible à 12, éligibilité UE, 1 170 €/mois puis 2 120 €) | décider d'un connecteur portail, ou assumiter une saisie manuelle |
| 45 | Groupe Banque mondiale | international (SRC-INST) | portail WBG | programme Pioneers **vérifié** (4 semaines à 6 mois, 2 cycles/an) | idem |
| 46 | BIE | LU (SRC-INST) | non vérifié | candidat listé, non consulté | vérifier la page officielle |
| 47 | BERD | GB (SRC-INST) | non vérifié | candidat listé, non consulté | idem |
| 48 | FMI | US (SRC-INST) | non vérifié | candidat listé, non consulté | idem |
| 49 | BIS | CH (SRC-INST) | non vérifié | candidat listé, non consulté | idem |
| 50 | ESMA / AMF | FR/UE (SRC-INST) | non vérifié | candidats listés, non consultés | regulator ≠ employeur : à traiter séparément |

### 7.6 Priorité de vérification proposée

| Rang | Critère | Employeurs |
|---:|---|---|
| 1 | Preuve déjà presque complète, coût de vérification faible | Alpha FMC (18), Monzo re-vérifié, Stripe (31), Airwallex (32) |
| 2 | Offres déjà documentées, dates manquantes | BlackRock (22), Amundi (23) |
| 3 | Banques françaises à fort volume, plateforme identifiée | BNP Paribas (9), Société Générale (10) |
| 4 | Blocages réseau/anti-robot, à requalifier en navigateur humain | GCM Grosvenor (19), Coinbase (30), Moniepoint (33), Baird (28) |
| 5 | Candidats NON VÉRIFIÉ, preuve à construire depuis zéro | 39-43, 14 |
| 6 | Hors modèle actuel, décision d'architecture à prendre | 44-50 |

---

## 8. Ce qu'il faut corriger avant d'ajouter une seule source

`JUGÉ`, dérivé des constats ci-dessus :

1. **Décider du plafond avant la liste.** `EXPLORATION_MAX_SOURCES = 24` est un plafond d'ordre :
   ajouter 50 entrées les ferait toutes outlier en `not_queried`. Trois options : un registre
   segmenté par catégorie avec sélection explicite, un tri déterministe qui fasse remonter les
   sources du brief actif, ou un relevé du plafond **avec** une mesure du budget 60 s
   (≈3 s/source mesurés : 21 sources ≈ 35 s).
2. **Ajouter un champ pays au registre**, avec la source du pays (page officielle, pas le nom de
   domaine). 19/45 offres n'ont pas de pays ; le filtrage `localisation` est aujourd'hui inexploitable.
3. **Séparer « source lisible » et « source utile »** dans le rapport : 9 sources sur 21 lisent un
   flux et rendent zéro offre. Sans cette distinction, « 21/21 succès » se lit comme une couverture.
4. **Ajouter `employment_type` réellement lu** : Ashby renvoie `Full-time` sur des postes Alan
   présentés comme permanents, et Allianz renvoie `Permanent` sur un titre « Internship ». Le
   contrat ne doit pas être déduit du seul titre.
5. **Réviser `local_capabilities().discovery.providers`** pour refléter les 4 connecteurs câblés.
6. **Trancher le contrat SQLite** `discovery_sources.provider` si l'on veut des boards personnels
   Lever/Ashby ; sinon le dire explicitement dans l'interface.
7. **Décider du sort des 4 entrées hors finance** (Doctolib, Pigment, Contentsquare, Dataiku) :
   les garder comme « terrain d'emploi financier » assumé, ou les sortir du registre finance. Les
   mesures montrent qu'elles consomment 5 places sur 21 pour 1 offre utile.

---

## 9. Limites de ce rapport

1. **Aucun appel réseau.** Aucun statut HTTP n'a été observé dans cette session. Tous les statuts
   cités sont ceux enregistrés dans les rapports existants, à leur date (13-18 octobre 2026).
2. **Registre non modifié.** SHA-256 identique avant/après, 21 entrées, aucune source ajoutée.
3. **Les employers hors registre n'ont pas été re-vérifiés.** §4 et §7 reproduisent ce que les
   fichiers disent, y compris leurs contradictions (par exemple `squarepoint.com` en page de parking
   dans M49 alors que SRC-EUR propose un token Greenhouse `squarepointcapital`).
4. **Le pays des 21 employeurs du registre est déclaré « non stocké »** partout où le dépôt ne
   l'atteste pas. Aucune valeur n'a été déduite d'un nom, d'un TLD ou d'un suffixe de board
   (`optiverus`, `boards.eu.greenhouse.io`), précisément parce que ces indices sont trompeurs.
5. **Helvetia Re** apparaît dans des fixtures de test de worktrees voisins : c'est une donnée
   synthétique, pas une source. Elle est donc exclue de toute liste.
6. **Les worktrees voisins sont hors de la base courante.** `AI-Excel-Agent-mission-03/31/46/47/48/49`,
   `AI-Excel-Agent-SRC-EUR/UKMEA/AMAP/INST` portent des bases divergentes ; leurs catalogues sont
   inertes et ne sont pas câblés. Ils servent ici de pistes, pas de preuves de production.
7. **Aucune adequacy au profil** n'est évaluée : aucun profil, CV, document ou critère personnel
   n'a été lu.

---

## 10. Vérifications exécutées dans cette session

Toutes hors ligne, sans secret en environnement, `HOME` factice, bytecode désactivé.

```text
.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_career_verified_source_expansion.py tests/test_career_public_ats_connectors.py
→ 25 passed in 8.67s

.venv/bin/python -m pytest -q -p no:cacheprovider
→ 1 failed, 1110 passed in 167.16s
   FAILED tests/test_task_queue.py::test_cooperative_cancellation_stops_worker_without_executing_untrusted_code

.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_task_queue.py
→ 5 passed in 2.10s
```

Le test en échec est **hors périmètre de cette mission** (`task_queue`, annulation coopérative) et
**passe isolément** : c'est un test temporel (`started.wait(timeout=1.0)`, boucle `checkpoint()` avec
`time.sleep(0.01)`) qui est instable sous charge de la suite complète. Il n'a pas été touché et n'est
**pas** imputé au registre. Aucun test Career ne fails.

Autres contrôles :

```text
git diff --check                                  → sortie vide, exit 0
git status --porcelain                            → aucun fichier suivi modifié
shasum -a 256 career/source_registry.py           → f2098bf4375d6671ab590e07722c1016d9ef0172a3a10c418cadf4efdf294477 (identique avant/après)
```

## 11. Retour arrière

Aucun. Cette mission n'écrit que ce rapport, fichier non suivi
`docs/career_intl/agents/REPORT_FINANCE_COVERAGE.md`. Aucun code, aucune base, aucun worktree voisin,
aucune branche et aucun registre n'ont été modifiés. Supprimer ce fichier restaure l'état exact
observé au début.