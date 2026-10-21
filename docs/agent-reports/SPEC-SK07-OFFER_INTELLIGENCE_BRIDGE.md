# SPEC SK-07 — Offer Intelligence Bridge (CVBOOST-28)

**Branche** : `worker/cvboost-28-1792617869` (mission ré-émise) — contient
`agent/spec-sk07-offer-intelligence-bridge` (fusionné) et SK-01 / SK-02 / SK-03
**Base** : `main` local (`f5b22f2`) + fusion de SK-01 / SK-02 / SK-03 + pont SK-07
**Date** : 2026-10-21
**Auteur** : Agent Mission 28 (worker)

---

## 0. Pourquoi cette mission est rejouée

La mission SK-07 avait déjà été livrée sur `agent/spec-sk07-offer-intelligence-bridge`
(commits `2ba9898` + `4e2695c`, sur la fusion SK-01→SK-03 `4d95a54`). Le pilote a
relancé la mission (`cvboost-28-1792617869`) : le livrable précédent n'était pas
rejouable depuis `main`, et surtout **n'avait pas été relu sous l'angle
adversarial**.

Ce rejouement ne recrée donc pas un pont : il **reprend** la livraison existante
(ponteur, magasin, intégration service/route/prépa/lettre), la **rejoue** contre
la base courante, et lui ajoute une **revue adversariale** qui a trouvé et
corrigé **4 défauts réels** (section 5). Aucun module n'est dupliqué, aucun
analyseur parallèle n'est créé.

---

## 1. Ce qui a été livré

```
career/offer_intelligence.py                          # constructeur de snapshot (pur)
career/offer_intelligence_store.py                    # persistance versionnée (pur)
career/service.py                                     # import, explorer, détail, matching, prépa, kit
career/application_prep.py                             # la prépa lit le contrat canonique
career/application_studio.py                           # la lettre cite le contrat canonique
career/router.py                                      # GET /api/career/offer-intelligence/{job_id}
tests/test_offer_intelligence.py                      # 53 tests (37 rejoués + 16 nouveaux)
tests/fixtures/offer_intelligence/offers.json         # 8 offres synthétiques gelées
tests/fixtures/offer_intelligence/adversarial.json    # 7 cas adversariaux (précision des contradictions)
docs/agent-reports/SPEC-SK07-OFFER_INTELLIGENCE_BRIDGE.md   # ce rapport
```

**Quinze offres 100 % synthétiques** (aucune entreprise, aucun poste, aucune personne réelle),
**53 tests**, modules **purs, déterministes, hors ligne** : pas d'horloge (sauf injection),
pas de hasard, pas de réseau, pas de modèle.

> **Intégration en amont** — SK-07 consomme SK-01 (confiance), SK-02 (dates) et SK-03
> (adéquation). Les trois branches (`agent/spec-sk01-source-trust`,
> `agent/spec-sk02-offer-dates`, `agent/spec-sk03-requirements-fit`) ont été **fusionnées
> dans ce worktree** (commit `5d1abd7`, fusion propre, aucun conflit : ce sont des ajouts
> de fichiers purs). SK-04 (couverture) et SK-05 (progression d'exploration) ne sont pas
> consommés par le pont et restent sur leur branche, à intégrer séparément.

---

## 2. Le contrat : un snapshot unique, versionné

```python
from career.offer_intelligence import build_snapshot

snapshot = build_snapshot(offer_raw, qualified_data) -> OfferIntelligenceSnapshot
```

| Bloc | Contenu |
|------|---------|
| `job_id` | identité de l'offre |
| `schema_version` | version du contrat d'intelligence |
| `source_hash` | empreinte du **texte source exact** (sha256, 64 caractères) |
| `temporal_facts` | publication, deadline, start, end, duration — avec bornes, précision, état de confiance et preuve |
| `requirements` | les enregistrements canoniques de prérequis, avec leur identifiant stable |
| `contradictions` | les preuves **réellement** incompatibles, gardées côte à côte, jamais arbitrées |
| `missing` | ce que la source ne prouve pas — toujours « à vérifier » |
| `qualifications` | la qualification contractuelle **attribuée à la source**, avec sa provenance et ses champs inconnus |
| `trust` | la décision de confiance explicite (SK-01) |
| `geo` / `lang` | localisation et langues, avec leur preuve |
| `provenance_map` | pour chaque fait : le champ, le passage cité et ses offsets |

### Un fait temporel

```json
{
  "id": "tf_57f5143cb2d64ac4",
  "kind": "deadline",
  "precision": "exact_date",
  "value": "2026-11-15",
  "lower_bound": null,
  "upper_bound": null,
  "confidence_state": "confirmed",
  "source_fact_id": "deadline@description_original:0",
  "evidence": {
    "source_kind": "official_text",
    "source_id": "9001",
    "source_field": "description_original",
    "locator": "offset:0:25",
    "quote": "Apply by 15 November 2026",
    "start_offset": 0,
    "end_offset": 25
  }
}
```

### Une exigence

```json
{
  "id": "req_825e12e58aab2265",
  "text": "Advanced Excel",
  "source_field": "requirements",
  "locator": "line:1",
  "category": "technical_skill",
  "modality": "required",
  "confidence": 0.9,
  "negated": false,
  "injection_suspect": false,
  "evidence": { "quote": "Advanced Excel", "start_offset": 0, "end_offset": 14 }
}
```

---

## 3. Zéro divergence : une exigence, un identifiant, tous les écrans

Les six consommateurs de la mission lisent **le même snapshot** :

| Écran | Point d'entrée | Identifiants |
|-------|----------------|--------------|
| Explorer (liste) | `GET /api/career/jobs` | `job["offer_intelligence_summary"]["requirement_ids"]` |
| Fiche détaillée | `GET /api/career/jobs/{id}` | `job["offer_intelligence"]["requirements"][*]["id"]` |
| Pont (route dédiée) | `GET /api/career/offer-intelligence/{id}` | `snapshot["requirements"][*]["id"]` |
| Matching | `GET /api/career/stage-search/matches` | `match["requirement_ids"]` |
| Préparation CV | `GET /api/career/jobs/{id}/prep` | `prep["offer_intelligence"]["requirement_ids"]`, `prep["requirements"][*]["requirement_id"]`, `prep["cv_action_plan"][*]["requirement_id"]` |
| Lettre & checklist | `GET /api/career/applications/{id}/kit` | mêmes enregistrements canoniques |

Test de garde : `test_every_screen_shares_the_same_requirement_identifiers` compare les six
listes — elles sont **strictement égales**. Les écarts de couverture CV sont eux aussi
rattachés à l'exigence canonique (`test_the_cv_gaps_carry_the_canonical_requirement_id`).

Les identifiants viennent du contrat canonique existant
(`career.offer_requirements.analyze_offer`, `req_` + sha256) : **aucun second analyseur de
prérequis n'a été créé**. L'ancienne extraction lexicale de `application_prep.extract_requirements`
reste en place comme fonction de compatibilité (appelée sans snapshot) ; le chemin produit
(service, prépa, kit, lettre) lit désormais le contrat canonique.

---

## 4. Persistance versionnée, sans nouvelle colonne sur les offres

Table dédiée `job_offer_intelligence_snapshots` :

```
job_id | version | schema_version | source_hash | summary_json | snapshot_json | is_current | created_at | updated_at
```

`jobs` n'est **pas** touchée : pas de colonne ajoutée, pas de migration destructrice, pas de
réécriture des données de la personne. La table est créée par `CREATE TABLE IF NOT EXISTS`
(cf. `career/offer_intelligence_store.ensure_schema`), sans passage de `SCHEMA_VERSION`.

| Cas d'import | Comportement vérifié |
|--------------|----------------------|
| Texte identique | Même version, **mêmes identifiants**, pas de nouvelle ligne |
| Texte modifié | **Nouvelle version**, l'ancienne passe en historique |
| Note personnelle | Préservée (`test_the_notes_shortlist_and_application_survive_a_reimport`) |
| Shortlist | Préservé |
| Candidature | Préservée (id + étape) |
| Preuve obsolète | Retirée du snapshot courant, conservée dans l'historique (`test_a_stale_evidence_is_never_presented_as_current`) |

`source_hash` ne dépend que des **champs source** : une note, un raccourci ou une étape de
candidature ne change jamais l'empreinte (`test_source_hash_ignores_the_user_state_of_the_offer`).

**Correction de ce rejouement** : l'empreinte ne tronquait plus le texte à 30 000 caractères.
Un changement situé au-delà de la fenêtre lue par les analyseurs ne créait donc aucune
nouvelle version. L'empreinte couvre désormais **tout** le texte source
(`test_the_source_hash_covers_the_whole_source_text`) : « texte modifié → nouvelle analyse »
est vrai au sens fort, sans que la version ne dépende d'une limite technique.

---

## 5. Revue adversariale : 4 défauts réels trouvés et corrigés

La livraison précédente était complète mais n'avait pas été relue sous l'angle
« que se passe-t-il quand les énoncés sont compatibles ? ». Quatre défauts ont été
trouvés en rejouant le module contre des cas hostiles. **Aucun test existant n'a été
modifié pour les faire passer : les attentes ont été ajoutées, jamais relâchées.**

### 5.1 Une contradiction était inventée entre deux énoncés compatibles

`_facts_conflict` comparait les **chaînes** de valeur. Un champ structuré
`start_date = 2027-01-15` et une phrase « the programme starts in January 2027 »
devenaient donc **deux contradictions** (`temporal_conflict` **et**
`structured_vs_description`), alors que les deux énoncés disent la même chose.

*Effet utilisateur* : une offre parfaitement cohérente est annoncée comme
contradictoire. L'utilisateur apprend à ignorer le bandeau « contradiction », et la
promesse centrale de la mission (« zéro divergence », « les faits confirmés, les
contradictoires, les à vérifier ») devient fausse.

*Correction* : la comparaison se fait désormais sur les **intervalles prouvés**. Un fait
« mois seul » couvre tout son mois, un fait « jour » couvre ce jour : les deux sont
compatibles. Seuls des intervalles **disjoints** sont une contradiction
(`_date_interval`, `_duration_interval`, `_intervals_conflict`).

### 5.2 Une borne et une durée exacte étaient annoncées incompatibles

« The placement lasts up to six months » (maximum) et « the placement lasts six months »
(durée exacte) sont compatibles : la durée exacte satisfait le maximum. L'ancienne
comparaison de chaînes les déclarait contradictoires.

*Correction* : une borne manquante vaut « non bornée » d'un côté, pas « différente ».

### 5.3 Les faits de qualification perdaient leur preuve

`qualifications` ne gardait que les champs sources : la **provenance** de la qualification
contractuelle (le champ, la valeur, la citation) et ses **champs inconnus** étaient
jetés. Le snapshot affirmait donc « type de contrat : stage » **sans la preuve** qui
l'étaye — exactement ce que la mission refuse (« tous les faits confirmés possèdent une
citation »).

*Correction* : `qualifications.provenance` et `qualifications.missing_fields` sont
conservés (`test_the_qualification_facts_keep_their_evidence`). Ils décrivent l'offre,
jamais la personne : le snapshot reste sans donnée candidat.

### 5.4 Les écarts de couverture CV ne portaient pas l'identifiant canonique

Le panneau « préparation CV » listait des écarts (`gaps`) décrits par leur texte seul,
alors que le plan d'action, lui, portait déjà l'identifiant. Un même écart pouvait donc
être désigné par deux noms différents selon l'écran.

*Correction* : chaque écart est aligné sur le contrat canonique au moment de la
sérialisation (`CareerService._gaps_with_requirement_ids`, alignement textuel
déterministe déjà utilisé par le pont). Un écart sans counterpart canonique **reste sans
identifiant** : aucun identifiant n'est inventé.

### Preuves

`tests/fixtures/offer_intelligence/adversarial.json` — 7 cas gelés qui séparent
explicitement **compatible** et **contradiction** :

| Cas | Attendu | Test |
|-----|---------|------|
| Champ structuré 15 janvier + texte « janvier 2027 » | 0 contradiction | `month_and_exact_agree` |
| « up to six months » + « six months » | 0 contradiction | `upper_bound_and_exact_duration_agree` |
| Deux dates exactes incompatibles | 1 contradiction | `two_exact_dates_conflict` |
| Champ structuré contre texte | 2 contradictions | `structured_and_text_conflict` |
| Deux mois incompatibles | 1 contradiction | `two_months_conflict` |
| « at least eight months » + « up to four months » | 1 contradiction | `disjoint_duration_bounds_conflict` |
| Aucune date | 0 contradiction | `no_date_never_conflicts` |

Le corpus gelé d'origine (8 cas) reste inchangé et passe **exactement** : le correctif
n'a pas relâché une seule attente existante.

---

## 6. Règles métier respectées

| Règle | Preuve |
|-------|--------|
| Une échéance n'est jamais une date de début | `test_a_deadline_is_never_reused_as_a_start_date` |
| Un mois seul ne devient jamais un jour | `test_a_month_only_statement_never_becomes_an_exact_day` |
| « up to six months » est un maximum, jamais un minimum | `test_an_upper_bound_never_proves_a_minimum` |
| Un fait confirmé porte sa citation et ses offsets | `test_every_confirmed_fact_carries_its_quote_and_its_offsets` |
| Une information manquante est « à vérifier », jamais « absente » | `test_a_missing_information_stays_to_verify_and_is_never_dropped` |
| Une contradiction garde les deux versions | `test_a_contradiction_keeps_both_sides_without_choosing_one` |
| **Deux énoncés compatibles ne sont jamais une contradiction** | `test_the_adversarial_corpus_separates_compatibility_from_contradiction` |
| **Deux énoncés incompatibles ne sont jamais masqués** | `test_a_real_conflict_is_never_hidden`, `test_a_disjoint_duration_is_never_hidden` |
| Une tentative d'injection reste une donnée inerte | `test_an_injection_attempt_stays_inert_data` |
| Une échéance dépassée reste visible | `test_an_expired_deadline_stays_visible` |
| Aucun appel réseau ni modèle | `test_the_snapshot_works_offline_without_any_model_call` (socket interdit) |
| Le snapshot ne contient aucune donnée de candidat | `test_the_snapshot_never_carries_candidate_profile_data`, `test_the_snapshot_stays_readable_without_any_candidate_data` |
| Une exigence inchangée garde son identifiant après un rafraîchissement | `test_an_unchanged_requirement_keeps_its_identifier_after_a_refresh` |

### Corpus gelé

`tests/fixtures/offer_intelligence/offers.json` — 8 cas, fr / en / de / it / es :
français complet · échéance ≠ début · allemand (durée exacte) · italien (mois seul) ·
espagnol (mois seul) · champ structuré contre texte · échéance dépassée · injection + troncature.

`tests/fixtures/offer_intelligence/adversarial.json` — 7 cas de précision des contradictions.

Les deux tests `test_frozen_corpus_classifies_every_fact_and_requirement` et
`test_the_adversarial_corpus_separates_compatibility_from_contradiction` comparent
**exactement** les faits, les exigences, les informations manquantes et le nombre de
contradictions de chaque cas.

---

## 7. Ce qui a été modifié dans l'existant (et pourquoi)

| Fichier | Modification | Statut |
|---------|--------------|--------|
| `career/offer_intelligence.py` | Builder du snapshot : comparaison des contradictions par **intervalles** (5.1, 5.2) ; conservation de la provenance de la qualification (5.3) ; empreinte du **texte entier** ; résumé enrichi (état géo / langue) | rejouement |
| `career/offer_intelligence_store.py` | Magasin versionné (inchangé, rejoué) | rejouement |
| `career/service.py` | Construction et versionnement du snapshot à l'import ; snapshot attaché au détail, résumé à l'explorer ; identifiants attachés au matching ; snapshot passé à la prépa, au kit et au tableau de bord ; **écarts de couverture alignés sur l'identifiant canonique** (5.4) | rejouement + 5.4 |
| `career/application_prep.py` | `prepare_application(..., intelligence=...)` : la liste des exigences est celle du contrat canonique et chaque élément porte son identifiant ; bloc `offer_intelligence` exposé ; **éléments `matched` / `unverified` portent l'identifiant** quand il existe | rejouement + identifiants |
| `career/application_studio.py` | `_offer_summary` cite les exigences canoniques quand le snapshot est présent | rejouement |
| `career/router.py` | `GET /api/career/jobs/{id}/offer-intelligence` et `GET /api/career/offer-intelligence/{id}` (alias, pas une copie) | rejouement |
| `tests/test_offer_intelligence.py` | 16 tests ajoutés (corpus adversarial, précision, provenance de qualification, empreinte complète, identifiants des écarts) | 16 ajoutés |

**Aucun test existant n'a été modifié** : le contrat gelé de `FitGap`
(`tests/test_cv_fit.py`) est resté intact — l'identifiant des écarts est attaché au
moment de la sérialisation, pas dans le modèle de données. `extract_requirements` garde
son comportement historique (l'extracteur lexical) pour les appels directs sans snapshot :
les tests historiques restent verts, le chemin produit lit le contrat canonique.

---

## 8. Validation

| Commande | Résultat |
|----------|----------|
| `pytest -q tests/test_offer_intelligence.py` | **53 passed** |
| `pytest -q tests/test_offer_dates.py tests/test_source_trust.py tests/test_requirements_fit.py` | **834 passed** (SK-01/02/03 fusionnés) |
| `pytest -q` (suite complète) | **2311 passed, 1 skipped** (skip pré-existant `test_offer_summary_exhaustiveness`) |
| `ruff check .` | **All checks passed** |
| `git diff --check` | **propre** |

Répartition : 2258 tests avant SK-07 (base `f5b22f2` + SK-01/02/03 fusionnés) → 2295 après
la première livraison du pont → **2311** après cette revue (seulement des tests ajoutés,
aucune attente existante relâchée).

---

## 9. Limites assumées

- **Le snapshot ne contient que des faits attribués à la source.** Le statut d'adéquation aux
  critères de la personne (`target_status`), l'admissibilité géographique et le statut de
  contrat dépendant du jour restent dans la couche de matching : une préférence modifiée ne
  doit pas créer une nouvelle version de l'analyse.
- **La confiance de la source est horodatée** (`checked_at`). C'est la seule valeur non
  déterministe du document ; les identifiants, eux, sont stables.
- **Le contrat SK-01/02/03 est réutilisé tel quel.** SK-07 n'améliore ni le détecteur de dates
  ni le classifieur de prérequis : il les branche. Une correction de ces modules se répercute
  automatiquement sur le snapshot.
- **Une contradiction est signalée par le pont et par l'analyseur temporel.** Quand les deux
  la voient (champ structuré contre texte), elle apparaît deux fois : une fois comme conflit
  de faits, une fois comme conflit champ-contre-texte. Les deux entrées pointent sur les
  mêmes deux énoncés ; aucune n'est arbitrée.
- **L'interface web n'a pas été refaite.** Les écrans consomment déjà `prep["requirements"]` ;
  ils montrent désormais les textes canoniques et disposent des identifiants dans la charge utile.
- **SK-04 et SK-05 ne sont pas fusionnés ici** : ils ne sont pas consommés par le pont.

---

## 10. Suite proposée

1. Exposer le bloc `offer_intelligence` dans l'interface (fiche détaillée : faits confirmés,
   contradictions, à vérifier).
2. Brancher SK-08 (enrichissement des connecteurs) sur `source_fields` pour que chaque fait
   conserve le nom exact du champ source.
3. Faire de `career.requirements_fit` (SK-03) le producteur des verdicts
   `supported / unsupported / contradicted / to_verify` dans le snapshot, pour que la
   correspondance profil ↔ offre soit elle aussi versionnée.
4. Rejouer la même revue adversariale sur SK-01, SK-02 et SK-03 : le défaut 5.1 (comparaison
   par chaînes) a été trouvé dans le pont, il peut exister dans les analyseurs amont.
