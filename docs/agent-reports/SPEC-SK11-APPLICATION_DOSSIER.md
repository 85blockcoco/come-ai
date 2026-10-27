# SPEC-SK11 — Dossier de candidature « 1 clic » et vérifiable

**Mission** : CVBOOST-32 — SK-11 — `docs/agent_missions/SPEC-SK11-APPLICATION_DOSSIER_PROMPT.md`
**Branche** : `worker/cvboost-32-1792626323`
**Base** : `main` (`f5b22f2` — merge(career): ATS diagnostics and targeted CV variants pipeline)

> **Note préalable** : le fichier de mission `docs/agent_missions/SPEC-SK11-APPLICATION_DOSSIER_PROMPT.md`
> était **absent** du dépôt — le pilote transmettait donc au worker la mention
> `[ERREUR: fichier introuvable: …]`. Le fichier a été **reconstruit** à partir de la description
>.registry (mission id `32`) et du format des prompts Spec Kit voisins, puis **livré avec la mission**
> pour que la mission soit rejouable. Il existe par ailleurs un `SPEC-SK11-GEO_FILTER_CONNECTORS.md`
> (SK-11 du filtre pays) : les deux SK-11 cohabitent, le registre fait foi sur celui-ci.

---

## 1. Ce qui a été livré

### 1.1 `career/application_dossier.py` — module pur du domaine (nouveau)

Un module **pur, déterministe, hors-ligne** : pas de réseau, pas d'horloge interne, pas d'aléatoire.
Même offre + mêmes faits ⇒ même dossier, mêmes verdicts, mêmes identifiants de claims.

```python
from career.application_dossier import build_application_dossier, export_dossier

dossier = build_application_dossier(offer, profile_facts, language=None, base_cv="")
dossier.language                  # "en" — la langue annoncée par l'offre
dossier.language_source          # "offer" | "user"
dossier.recommendations          # HIGHLIGHT / REPHRASE / DO_NOT_ADD / QUANTIFY / CONFIRM_LANGUAGE
dossier.coverage                  # exigence ↔ fait, avec verdict
dossier.diff                      # kept / added / removed (comparaison avant / après)
dossier.verification.claims       # une affirmation = une ligne, un verdict
dossier.verification.export_allowed   # False dès qu'une affirmation est "unsupported"
dossier.history                   # historique de versions

export_dossier(dossier, target_dir)    # refuse si export_allowed est False
```

**Les 6 livrables** produits depuis une seule offre :

| Livrable | Contenu |
|---|---|
| `cv_recommendations` | une action concrète par exigence, avec sa preuve |
| `adapted_cv` | CV ciblé reconstruit **uniquement** à partir de faits approuvés |
| `cover_letter` | lettre dont chaque phrase factuelle cite un fait |
| `prep_sheet` | faits d'offre à vérifier, couverture des exigences, points à ne pas inventer, points de discussion |
| `checklist` | relecture avant envoi, alimentée par les verdicts |
| `interview_questions` | questions adossées à une exigence et à un fait |

### 1.2 Le vérificateur — le cœur de la mission

Chaque phrase du dossier est découpée en phrase, puis reçoit **exactement un verdict** :

| Situation | Verdict |
|---|---|
| phrase citant ≥1 fait **approuvé** qui couvre bien la phrase | `supported` |
| phrase citant un fait **non approuvé** (proposé / rejeté / suspendu) | `to_verify` |
| phrase citant un fait approuvé qui **ne prouve pas** la phrase | `unsupported` |
| phrase écrite à la main, assertion candidate non prouvée | `unsupported` |
| phrase écrite à la main, ni assertion candidate ni contradiction | `to_verify` |

- « Assertion candidate » = première personne (`I `, `j'`, `mon `, `ich habe`, `ho `) **ou chiffre**.
- Une phrase de l'offre (`I am applying for the … role`) n'est **pas** une affirmation sur le
  candidat : elle est `to_verify`, jamais `unsupported`.
- **Une affirmation `unsupported` bloque l'export final.** `to_verify` n'est pas bloquant mais
  reste visible dans le dossier et dans la checklist.
- `export_dossier()` **relance le vérificateur sur les corps qu'il est sur le point d'écrire** :
  un export ne peut jamais transporter une affirmation non prouvée, même si la vérification
  mémorisée est périmée.

### 1.3 `career/service.py` + `career/router.py` — orchestration locale

- Nouveau schéma **v9** (`SCHEMA_VERSION 8 → 9`) : table `application_dossiers`, migration
  additive `_migrate_to_v9`, **aucune donnée existante n'est réécrite**.
- `CareerService.build_application_dossier()` / `get_application_dossier()` /
  `update_application_dossier()` / `export_application_dossier()` /
  `list_application_dossier_versions()`.
- Endpoints :

| Méthode | Route |
|---|---|
| `POST` | `/api/career/applications/{application_id}/dossier` (corps : `{"language": ""}`) |
| `GET` | `/api/career/applications/{application_id}/dossier` |
| `PATCH` | `/api/career/applications/{application_id}/dossier` (corps : livrables édités) |
| `POST` | `/api/career/applications/{application_id}/dossier/export` |

### 1.4 `career_static/` — l'action « 1 clic »

- Nouveau `career_static/js/application_dossier.js` : rendu du dossier, verdicts, recommandations,
  comparaison avant/après, livrables, bouton d'export local.
- `career_static/career.js` : bouton **« Ouvrir le dossier vérifiable »** sur chaque candidature.
- `career_static/career.css` : styles dédiés (`.application-dossier*`).
- `career_static/index.html` : chargement du nouveau script (`defer`, avant `career.js`).

### 1.5 Tests

| Fichier | Tests | Objet |
|---|---|---|
| `tests/test_application_dossier.py` | 53 | contrat du module pur (langue, livrables, verdicts, zéro invention, diff, historique, export, hors-ligne, déterminisme) |
| `tests/test_application_dossier_integration.py` | 14 | service + HTTP + garde-fous UI (Node) |
| `tests/fixtures/application_dossier/*.json` | 6 offres | corpus synthétique multilingue (en, fr, de, it, injection, minimale) |

---

## 2. Preuves d'exécution

### 2.1 Boucle complète, sur l'offre synthétique `offer_en.json`

```
LANGUE: en offer | version 1
VERDICTS: 12 supported / 0 unsupported / 0 to_verify
EXPORT: True
--- RECOMMANDATIONS ---
  REPHRASE         | Excel, SQL                                       | Excel dashboards for sales rep
  HIGHLIGHT        | Master's degree in Finance                       | Master's degree in Finance
  REPHRASE         | English (Fluent)                                 | English C1
  DO_NOT_ADD       | 3 years of experience with Power BI              |
  DO_NOT_ADD       | English (Fluent), German                         |
  DO_NOT_ADD       | Student or recent graduate                       |
  REPHRASE         | English required.                                | English C1
  DO_NOT_ADD       | Excel and SQL are mandatory.                     |
  DO_NOT_ADD       | Familiarity with Power BI is a plus.             |
--- LETTRE ---
# Cover letter — Data Analyst Intern — Northwind Analytics
...
Elements documented in my approved profile:
- Excel dashboards for sales reporting
- Master's degree in Finance
- English C1
- SQL analysis at a retail company
...
No automatic submission: you review, then you send it yourself.
--- APRES EDITION (phrase ajoutée à la main) ---
  export_allowed: False
  BLOQUANT: I have 5 years of experience with Power BI and a C2 level in German.
```

### 2.2 Commandes

```
pytest -q tests/test_application_dossier.py            → 53 passed
pytest -q tests/test_application_dossier_integration.py → 14 passed
pytest -q                                              → 1491 passed, 1 skipped
ruff check .                                            → All checks passed!
git diff --check                                        → propre
```

> Le `1 skipped` est **préexistant** (`tests/test_offer_summary_exhaustiveness.py` : script ou base absents).

### 2.3 Zéro régression

Base avant mission : **1423 tests verts**. Après : **1491 verts** (+53 domaine, +14 intégration,
+1 previously failing test de version de schéma mis à jour de 8 → 9).

### 2.4 Campagne adversariale — un vrai défaut trouvé et corrigé

Un audit adverse du flux « profil modifié après la construction du dossier » a mis en évidence un
défaut **réel** :

> **Défaut (élevé)** — le dossier était vérifié contre l'**instantané** des faitsCapturé lors de
> la construction. Si la personne supprimait ou modifiait une ligne de son profil **après** avoir
> construit le dossier, la phrase du CV et de la lettre qui citait cette ligne continuait d'être
> considérée comme « prouvée », et l'export final passait. Un fait retiré du profil pouvait donc
> continuer à justifier une candidature.

**Correction** : la vérification et l'export sont désormais faits contre les faits **approuvés
courants** du profil, jamais contre l'instantané :

- `CareerService.update_application_dossier()` re-vérifie les corps édités contre
  `facts_from_profile(self._dossier_profile_facts())` ;
- `CareerService.export_application_dossier()` remplace les faits du dossier par les faits
  courants avant d'écrire les fichiers ;
- les identifiants de faits sont désormais **dérivés du contenu**
  (`profile_<sha256(category|valeur)[:12]>`) : réordonner le profil n'invalide aucune preuve,
  mais modifier ou supprimer une ligne le fait — exactement le comportement attendu.

**Test de non-régression** : `test_a_fact_removed_from_the_profile_stops_proving` — la ligne
« Excel, tableaux de bord » est retirée du profil, le dossier est ré-enregistré : l'affirmation
correspondante passe en `unsupported` et **l'export est refusé**.

Autres scénarios adversariaux sondés puis figés en tests : phrase inventée (chiffre, diplôme,
niveau de langue, certification), fait proposé / rejeté / nié, exigence sans preuve, texte d'offre
contenant une injection, réécriture manuelle de la lettre, réordonnancement des lignes de profil.

---

## 3. Règles non négociables — état

| # | Règle | Preuve |
|---|---|---|
| 1 | Une phrase factuelle = une preuve approuvée | `verify_dossier_text` : registered sentence → `fact_id` obligatoire ; `test_supported_claims_cite_an_approved_fact` ; les identifiants de faits sont dérivés du **contenu** et la vérification porte toujours sur les faits **courants** du profil (§ 2.4) |
| 2 | Zéro invention (diplôme, compétence, chiffre, niveau) | `test_invented_degree_is_unsupported`, `test_invented_figure_is_unsupported`, `test_invented_language_level_is_unsupported`, `test_invented_skill_is_unsupported` |
| 3 | Vérificateur obligatoire : 3 verdicts | `test_every_claim_has_a_known_verdict`, `test_counts_are_consistent` |
| 4 | `unsupported` bloque l'export final | `test_export_is_refused_when_an_claim_is_unproven`, `test_unsupported_edition_blocks_the_export` |
| 5 | Langue de l'offre par défaut, modifiable, tracée | `test_default_language_comes_from_the_offer`, `test_person_can_force_another_language`, `test_language_aliases_are_accepted` |
| 6 | Comparaison avant / après | `test_before_after_comparison_is_produced` (`kept` / `added` / `removed`) |
| 7 | Historique de versions | `test_history_keeps_every_version`, `test_versions_are_kept` |
| 8 | Aucun envoi automatique | `test_export_opens_no_socket`, `test_no_automatic_submission_anywhere`, `automatic_submission: false` dans le manifeste exporté |
| 9 | Hors-ligne et déterministe | `test_build_is_deterministic`, `test_no_clock_is_used`, `test_generated_at_is_supplied_by_the_caller` |
| 10 | Le texte de l'offre est une donnée, pas une instruction | `test_offer_injection_is_not_turned_into_a_requirement`, `test_offer_text_never_executes_an_instruction` (fixture `offer_injection.json`) |

---

## 4. Points d'attention pour la relecture

### 4.1 La couverture des exigences reste « à vérifier », jamais « non »
Comme SK-03, une exigence **sans** preuve approuvée est `to_verify` et non `unsupported` :
une absence de preuve ne prouve pas une absence de compétence. La distinction est faite au
niveau des **affirmations** (le dossier), pas des exigences (la couverture).

### 4.2 Deux vocabulaires distincts, volontairement
- **Couverture exigence ↔ profil** : `supported` / `to_verify` / `contradicted` (aligné SK-03).
- **Affirmations du dossier** : `supported` / `unsupported` / `to_verify` (aligné la mission).
  C'est `unsupported` qui bloque l'export, parce que c'est une affirmation **non prouvée**,
  pas une exigence non couverte.

### 4.3 Point d'intégration SK-10 (profil candidat avec preuves approuvées)
`CareerService._dossier_profile_facts()` est **le point d'intégration unique** : il lit
aujourd'hui le profil local (`candidate_profile`, écrit par la personne ⇒ approuvé par
définition), ligne par ligne. Lorsque SK-10 sera intégré, c'est **ce seul point** qui doit
basculer sur les faits approuvés de `career/candidate_profile` (statuts `approved` / `modified`),
les autres statuts restant non probants. Le module accepte déjà les deux formes
(SK-03 `ProfileFact`, SK-10 `Fact`) via `facts_from_profile()`.

### 4.4 Le diff avant/après compare des lignes, pas des documents
Le « avant » est le CV tel que le workspace le connaît (profil local : formation, expériences,
compétences, langues) ; le « après » est le CV adapté. Le diff est **ligne à ligne**
(`kept` / `added` / `removed`), pas un diff de rendu : il dit ce qui change, pas comment la
mise en page change.

### 4.5 Un point de vigilance sur la détection de langue
La langue par défaut est celle **annoncée** par l'offre : champ explicite `language`, sinon
`languages_required`, sinon le **premier** marqueur de langue trouvé dans la description
(position, pas fréquence : « German, English » → `de`, « English (Fluent), German » → `en`).
En l'absence de tout marqueur, le défaut est `fr` (l'espace Career est francophone) et la
personne peut forcer la langue à tout moment.

---

## 5. Fichiers

| Fichier | Nature |
|---|---|
| `career/application_dossier.py` | **nouveau** — module pur du domaine (2 184 lignes) |
| `career/service.py` | modifié — schéma v9, 5 méthodes de service, pont profil → faits |
| `career/router.py` | modifié — 2 modèles + 4 endpoints |
| `career_static/js/application_dossier.js` | **nouveau** — rendu UI du dossier |
| `career_static/career.js` | modifié — bouton « Ouvrir le dossier vérifiable » |
| `career_static/career.css` | modifié — styles `.application-dossier*` |
| `career_static/index.html` | modifié — chargement du script |
| `tests/test_application_dossier.py` | **nouveau** — 53 tests |
| `tests/test_application_dossier_integration.py` | **nouveau** — 14 tests |
| `tests/fixtures/application_dossier/*.json` | **nouveau** — 6 offres synthétiques |
| `tests/test_qualification_snapshot_persistence.py` | modifié — version de schéma 8 → 9 |
| `docs/agent_missions/SPEC-SK11-APPLICATION_DOSSIER_PROMPT.md` | **nouveau** — fichier de mission reconstruit |
| `docs/agent-reports/SPEC-SK11-APPLICATION_DOSSIER.md` | **nouveau** — ce rapport |

---

## 6. Ce qui n'est **pas** fait (hors périmètre assumé)

- **Pas d'envoi automatique, et pas de « bouton postuler »** : c'est une règle de la mission.
  Le dossier écrit des fichiers, la personne envoie.
- **Pas d'export DOCX/PDF du dossier** : l'export écrit du Markdown + `verification.json` +
  `manifest.json`. Le kit CVBOOST-05 sait déjà produire du DOCX/PDF ; le brancher est une
  itération, pas un manque du cœur de mission.
- **Pas de bascule sur SK-10** : SK-10 n'est pas dans `main` (branche `agent/spec-sk10-candidate-profile`).
  Le point d'intégration est identifié (§ 4.3), l'interface est déjà compatible.
- **Pas de réécriture de `career/application_studio.py`** : le kit existant reste tel quel ;
  SK-11 est un dossier **vérifiable** au-dessus, pas un remplacement du kit.
