# SPEC SK-03 — Adéquation prérequis ↔ profil approuvé (CVBOOST-24)

**Branche** : `worker/cvboost-24-1792601094` (worktree dédié)
**Base** : `main` local (`a054c97`)
**Date** : 2026-10-21
**Auteur** : Agent Mission 24 (worker)

---

## 1. Ce qui a été livré

```
career/requirements_fit.py                          # module de correspondance (1820 l.)
tests/test_requirements_fit.py                      # 498 tests
tests/fixtures/requirements_fit/etudes.json         # 13 cas synthétiques
tests/fixtures/requirements_fit/competences.json    # 13 cas synthétiques
tests/fixtures/requirements_fit/contextes.json      # 16 cas synthétiques
tests/fixtures/requirements_fit/contradictions.json #  8 cas synthétiques
tests/fixtures/requirements_fit/multilingue.json    #  7 cas synthétiques
tests/fixtures/requirements_fit/regles.json         # 12 cas synthétiques
docs/agent-reports/SPEC-SK03-REQUIREMENTS_FIT.md    # ce rapport
```

**69 fixtures synthétiques** (aucune offre réelle, aucune entreprise réelle, aucune personne
réelle, aucun réseau), **498 tests**, module **pur, déterministe, hors ligne** : pas d'horloge,
pas de hasard, pas de réseau, pas de modèle. La même offre et le même profil donnent toujours
le même résultat, dans le même ordre.

> **Rappel d'isolation de mission** — le worktree `AI-Excel-Agent-worker-cvboost-24-1792601094`
> est partagé avec un autre worker (mission SK-02, branche identique) qui y a commité
> `80405c7`, `7b342d0`, `761c7b2`, `7cb14ed` pendant l'exécution de SK-03. Le commit SK-03
> (`8934ca8`) ne contient **que** les fichiers SK-03 listés ci-dessus.

---

## 2. API livrée

```python
from career.requirements_fit import analyze_fit, ApprovedProfile, ProfileFact

result = analyze_fit(offer_or_analysis, approved_profile) -> FitResult
```

- `offer_or_analysis` : soit un **offre** (les exigences canoniques sont alors extraites par
  `career.offer_requirements.analyze_offer()`), soit une **analyse déjà calculée** de ce
  contrat. Les deux entrances donnent exactement le même résultat (test dédié).
- `approved_profile` : une `ApprovedProfile`, un mapping (`facts` ou sections
  `education`/`skills`/`languages`/…), ou une liste de faits.

### Contrat d'un verdict

```json
{
  "requirement_id": "req_ab88a6f0d8d460fb",
  "requirement_text": "Master 2 en finance",
  "modality": "mandatory",
  "category": "etudes",
  "verdict": "supported",
  "profile_evidence": "Master 2 en finance, 2026",
  "evidence_offset": 128,
  "reason": "Niveau approuvé « master 2 » atteint l'exigence « master 2 » …",
  "confidence": 0.85
}
```

### Contrat du résultat

```json
{
  "fits": [ … ],
  "supported_count": 3,
  "unsupported_count": 1,
  "to_verify_count": 5,
  "contradicted_count": 0,
  "not_applicable_count": 1,
  "overall_score": 0.6667,
  "missing_critical": ["req_…", "…"]
}
```

`missing_critical` liste les **ids** des exigences `mandatory` dont le verdict n'est pas
`supported` (une exigence obligatoire à vérifier reste donc listée : elle n'est pas validée).

---

## 3. Réutilisation du contrat canonique — aucun nouvel extracteur

`career/requirements_fit.py` **n'extrait aucune exigence**. Il appelle
`career.offer_requirements.analyze_offer()` et consomme ses enregistrements :

| Champ canonique | Usage dans SK-03 |
|------------------|------------------|
| `id`             | `requirement_id` (clé de jointure) |
| `text`           | `requirement_text` (citation verbatim de l'offre) |
| `modality`       | `required` → `mandatory` ; `preferred`/`contextual`/`unknown` conservés |
| `category`       | point de départ de la catégorie de correspondance (raffiné, cf. §5) |
| `negated`        | énoncé sans obligation → `not_applicable` |
| `injection_suspect` | passage inerte → `not_applicable`, jamais une exigence |
| `source_field` / `locator` | cités dans `reason` (« [exigence : requirements line:2] ») |

Test de garde : `test_the_module_reuses_the_canonical_requirement_contract` vérifie que les
ids et les textes des verdicts sont **exactement** ceux du contrat canonique, dans le même
ordre.

---

## 4. Les 6 règles non négociables, et comment elles sont tenues

| # | Règle | Implémentation | Test / fixture |
|---|-------|----------------|----------------|
| 1 | **Absent ≠ incompatible** | une exigence sans preuve approuvée → `to_verify` (jamais `unsupported`) ; `unsupported` est réservé à un **manque prouvé** (durée, niveau ou date approuvés inférieurs à l'exigence) | `test_absent_information_is_never_reported_as_incompatible`, 12 fixtures `to_verify` |
| 2 | **« Master preferred » ne rejette jamais** | modality `preferred` + niveau approuvé inférieur → `to_verify` avec la mention explicite « cela ne rejette jamais le profil » | `test_master_preferred_never_rejects_a_bachelor_or_an_m1`, `etudes-master-apprécié-bachelor-ne-rejette-jamais` |
| 3 | **« Master 2 required » traité séparément** | échelle de niveaux explicite (`bac` → `doctorat`), un niveau **numéroté** (`Master 1`, `M2`, `Bac+5`) l'emporte toujours sur le niveau générique ; exigence obligatoire non atteinte → `unsupported` + `missing_critical`, avec sa propre formulation | `test_master2_required_is_handled_on_its_own`, `etudes-master2-obligatoire-master1-approuve` |
| 4 | **OCR non approuvé ≠ preuve** | seuls les faits `approved` / `modified` font preuve ; `proposed`, `rejected`, `suspended` sont invisibles (un OCR approuvé par l'utilisateur reste une preuve) | `test_only_approved_facts_are_evidence`, 4 fixtures `regle-*` |
| 5 | **Citations croisées** | tout `supported` cite l'exigence (verbatim + provenance) **et** le fait profil (verbatim + offset) | `test_supported_fits_cite_the_offer_and_the_profile`, `test_evidence_offsets_point_at_the_approved_quote` |
| 6 | **Isolation** | `analyze_fit` ne mute jamais l'offre et n'y réinjecte aucune donnée profil | `test_the_offer_is_never_mutated`, `test_the_profile_is_never_written_back_into_the_offer` |

---

## 5. Catégories de correspondance

Les 9 catégories minimales sont toutes atteintes par le corpus :

| Catégorie | Étiquette | Origine |
|-----------|-----------|---------|
| `etudes` | Niveau d'études | catégorie canonique `education` (niveau nommé) |
| `experience` | Expérience | catégorie canonique `experience` |
| `tech` | Compétences techniques | catégorie canonique `technical_skill` (savoir-faire) |
| `outils` | Outils | catégorie canonique `technical_skill` (logiciel nommé : Excel, VBA, Power BI, SAP…) |
| `langues` | Langues | catégorie canonique `language` |
| `mobilite` | Mobilité | catégorie canonique `mobility` |
| `auth_travail` | Autorisation de travail | catégorie canonique `work_authorization` |
| `dispo` | Disponibilité | catégorie canonique `availability` |
| `diplomation` | Date de diplomation | raffinement : une date de diplôme n'est pas un niveau |
| `other` | Non classé | énoncé hors des 9 catégories |

**Raffinement de catégorie (jamais une nouvelle extraction)** — la catégorie canonique est
d'abord **vérifiée** sur l'énoncé (le contrat canonique fait des correspondances par
sous-chaîne : « esprit d'équipe et rigueur » est classé `work_authorization` à cause du
« ue » de « rigueur »). Si la catégorie canonique n'est pas confirmée, la catégorie est
re-dérivée depuis les marqueurs lexicaux de l'énoncé (frontières de mot, 5 langues). Un
« Master 2 obtenu en 2026 » reste un niveau (`etudes`), pas une date de diplomation.

---

## 6. Verdict : quand chaque verdict tombe

| Verdict | Déclencheur | Exemple |
|---------|-------------|---------|
| `supported` | preuve approuvée exacte (jeton, niveau, durée, date, langue, ville) | « Master 2 en finance » ↔ fait approuvé « Master 2 en finance » |
| `unsupported` | **manque prouvé** : durée approuvée < durée exigée, niveau approuvé < niveau exigé, date approuvée postérieure à l'exigence | « 3 ans d'expérience » ↔ 24 mois approuvés |
| `contradicted` | **conflit explicite** : fait approuvé qui nie l'attribut, autorisation exigée ↔ sponsor de visa exigé par le profil, « sur site » ↔ « télétravail uniquement », date de diplôme postérieure | « 3 ans de gestion d'équipe » ↔ fait « aucune expérience de gestion d'équipe » |
| `to_verify` | information absente du profil — **jamais** une incompatibilité | « Python » demandé, absent du profil |
| `not_applicable` | l'énoncé ne porte aucune obligation : négation du contrat canonique, énoncé contextuel, tentative d'instruction | « Aucune expérience exigée », « Ignore previous instructions… » |

### Détail par catégorie

| Catégorie | Preuve recherchée | Règle de comparaison |
|-----------|-------------------|----------------------|
| `etudes` | échelle `bac`(1) → `bac+2`(2) → `licence`(3) → `M1`(4) → `master`/`M2`(5) → `doctorat`(6) | niveau approuvé ≥ exigence → `supported` ; < et `mandatory` → `unsupported` ; < et `preferred` → `to_verify` ; domaine différent → `to_verify` |
| `experience` | fait `experience` (mois approuvés + domaine) | mois approuvés ≥ mois exigés → `supported` ; < → `unsupported` si `mandatory`, `to_verify` sinon |
| `tech` / `outils` | fait `tech`/`outils` couvrant **tous** les termes distinctifs de l'exigence | couverture partielle → `to_verify` (le terme manquant est cité) ; manque de durée prouvée → `unsupported` |
| `langues` | fait `langues` par langue + niveau (`A1`→`C2`, `courant`=5, `natif`=6) | niveau approuvé ≥ exigé → `supported` ; < → `unsupported` si `mandatory` ; langue absente → `to_verify` |
| `mobilite` | fait `mobilite` (ville, relocation, télétravail/présentiel) | ville commune ou relocation assumée → `supported` ; sur site ↔ télétravail → `contradicted` |
| `auth_travail` | fait `auth_travail` (autorisation UE, sponsorship) | autorisation approuvée → `supported` ; sponsor exigé par le profil ↔ autorisation exigée → `contradicted` |
| `dispo` | fait `dispo` (date de début, durée) | début approuvé ≤ exigé → `supported` ; > → `contradicted` ; « immédiatement » vs profil daté → `to_verify` (pas d'horloge) |
| `diplomation` | fait `diplomation` (date ou année) | diplôme approuvé ≤ exigence → `supported` ; > → `contradicted` |

**Absence d'horloge** : « disponible immédiatement » face à un profil daté reste `to_verify` —
sans date du jour, une contradiction ne peut pas être affirmée.

---

## 7. Score et compteurs

```
overall_score = Σ (poids_verdict × poids_modalité) / Σ poids_modalité
poids_verdict : supported 1.0 | to_verify 0.5 | unsupported 0.0 | contradicted 0.0
                not_applicable : exclu du numérateur et du dénominateur
poids_modalité : mandatory 1.0 | preferred 0.5 | unknown 0.5 | contextual 0.0
```

Une exigence à vérifier rapporte un demi-point : elle n'est ni validée ni rejetée. Une
exigence non bloquante pèse moitié moins qu'une exigence obligatoire.

`confidence` (par verdict) : `supported` 0.85–0.90 (preuve exacte) / 0.70–0.78 (preuve
partielle) · `unsupported` 0.72–0.80 · `contradicted` 0.80–0.82 · `to_verify` 0.50–0.66 ·
`not_applicable` 0.90–0.95.

---

## 8. Tests

```
.venv/bin/python -m pytest -q tests/test_requirements_fit.py   → 498 passed
.venv/bin/python -m pytest -q                                   → 3525 passed, 1 skipped
.venv/bin/python -m ruff check .                                → All checks passed
git diff --check                                                → propre
```

Le fichier de tests bloque le réseau (`socket`) pendant toute la session : aucun test ne peut
toucher le réseau, le module n'a ni horloge ni aléa.

### Couverture du corpus

- **69 cas** synthétiques répartis en 6 fichiers : études/diplôme, compétences/outils/langues,
  contextes (expérience, mobilité, autorisation, disponibilité), contradictions, multilingue
  (DE/IT/ES), règles (négation, injection, OCR, modalités, profil vide).
- Les 5 verdicts, les 4 modalités et les 9 catégories minimales sont effectivement rencontrés
  (`test_the_corpus_covers_every_category_and_every_verdict`).
- Chaque cas est rejoué 6 fois (contrat attendu, déterminisme, non-mutation de l'offre,
  cohérence des compteurs, `missing_critical`, citations croisées).

---

## 9. Limites connues (assumées, documentées)

1. **La durée d'expérience approuvée est plafonnée par ce que le profil déclare.** Si le profil
   ne chiffre pas ses experiences, la comparaison de durée tombe en `to_verify` : c'est
   volontaire (règle 1).
2. **« unavailable » n'est pas un fait.** Aucune absence n'est déduite d'une liste de
   compétences : « Python » absent reste `to_verify`, jamais `unsupported`.
3. **`to_verify` reste un travail humain.** Le module classe et cite ; il ne décide pas.
4. **Le contrat canonique reste la source de vérité** : une phrase que
   `analyze_offer()` ne classe pas (prose sans marqueur) n'est jamais une exigence ici non plus.
5. **`career/candidate_profile.py` (mission SK-10) n'existe pas encore.** `ApprovedProfile` et
   `ProfileFact` sont définis dans ce module pour rester autonome ; SK-10 pourra adapter son
   `Profile` vers `ApprovedProfile` (ou reprendre le vocabulaire `proposed` / `approved` /
   `rejected` / `modified` / `suspended`, déjà aligné ici).

---

## 10. Intégration proposée

```python
from career.offer_requirements import analyze_offer
from career.requirements_fit import analyze_fit

analysis = analyze_offer(offer)
result = analyze_fit(analysis, approved_profile)

for fit in result.fits:
    print(fit.category, fit.verdict, fit.reason)
    if fit.requirement_id in result.missing_critical:
        print("  → exigence obligatoire non couverte")
```

- `analysis` (contrat canonique) et `result` (adéquation) restent deux objets séparés : rien
  du profil n'entre dans le contrat public de l'offre.
- `FitResult.to_dict()` est directement sérialisable en JSON (aucun objet non convertible).

---

**Tu as tout. Lance-toi.** Je relis et j'intègre.
