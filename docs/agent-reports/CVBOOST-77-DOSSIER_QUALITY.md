# SPEC-042 — Auditeur de qualité de dossier (anti-sur-promesse)

**Mission** : CVBOOST-77 · **Branche** : `worker/cvboost-77-1793235481253` (+ `agent/spec-042-dossier-quality`) · **Statut** : done

> Émettre, pour tout document de candidature produit (CV adapté, lettre, réponses de
> formulaire), un rapport de qualité déterministe qui détecte les informations inventées,
> les formulations exagérées, les qualifications hors contexte, les arguments faibles et
> le parasitage ATS — **avant** que l'utilisateur n'exporte.

## Livrés

| Fichier | Rôle |
|---|---|
| `career/claim_check.py` | Découpe phrase par phrase + verdict par claim (5 labels) + JSON + rapport lisible |
| `career/dossier_quality.py` | Score global 0-100 : 3 facteurs publiés, formules et entrées inspectables |
| `career/dossier_quality_rules.json` | Règles d'exagération **versionnées** (v1.0.0), éditables par l'utilisateur |
| `career/apply_kit.py` | Étape 2 du kit 1-clic (59) : audit du dossier **avant** export (`quality_audit`) |
| `tests/test_claim_check.py` | 89 cas (phrases inventées, outrées, hors contexte, chiffres déplacés, génériques, ATS…) |
| `tests/test_dossier_quality.py` | 27 cas (facteurs, formules, verdicts, blocage export, kit, bornes, déterminisme) |
| `docs/agent-reports/CVBOOST-77-DOSSIER_QUALITY.md` | Ce rapport |

## 1. `claim_check.py` — le verdict phrase par phrase

- **Découpe** : chaque phrase (CV, lettre, réponses de formulaire) devient un claim
  balisé section + offset ; les références d'offre, contacts et formules de politesse
  sont écartées (comptées dans `skipped`, jamais auditées).
- **Labels fermés** : `supported | inflated | out_of_context | invented | unverifiable`.
  Aucune autre catégorie, aucun modèle probabiliste : règles locales + lexique.
- **Preuve** : chaque claim est confronté à un *ledger* de faits approuvés
  (source : profil SK-10, réponses d'intake, service de preuves via
  `evidence_service` — niveau `declared/documented/verified/quantified` **+ date**
  `dated_at`). Seuls les statuts `approved` / `modified` comptent ; une preuve
  rejetée ou proposée n'est jamais une preuve.
- **Sorties** : `report.to_json()` (structuré) et `readable_report(report)` —
  pour chaque phrase : la phrase citée, la preuve trouvée (citation + niveau + date),
  la preuve manquante, et une **suggestion qui n'invente jamais** : elle renvoie
  vers un fait déjà approuvé du profil ou propose de retirer la phrase
  (test `test_suggestion_never_invents_a_fact`).
- **Déterminisme** : même document + mêmes preuves → rapport identique à l'octet près
  (`test_report_is_deterministic`).

## 2. `dossier_quality.py` — le score 0-100 transparent

Trois facteurs, poids fixés, **formule + entrées publiées dans le rapport** (JSON et Markdown) :

| Facteur | Poids | Formule |
|---|---|---|
| **Factualité** | 50 % | `100 × (étayées + 0,35 × non vérifiables − 0,50 × exagérées − 0,75 × hors contexte − 1,00 × inventées) ÷ affirmations auditées − 5 × listes ATS`, borné 0..100 |
| **Preuve** | 30 % | `100 × (0,50 × part des affirmations couvertes + 0,35 × niveau moyen de la preuve + 0,15 × part des preuves datées)`, borné 0..100 |
| **Argumentaire** | 20 % | `100 × (0,60 × exigences de l'offre couvertes + 0,40 × réponses récurrentes renseignées)` (renormalisées si une entrée manque) `− 10 × densité d'arguments génériques` ; **50 neutre** si aucune exigence ni réponse n'est fournie (jamais de faux pass) |

- **Verdicts** : `ready` (≥ 85, zéro exagération, zéro ATS), `review`, `blocked`
  (< 60, ou **n'importe quel claim `invented` / `out_of_context`** — un fait inventé
  bloque l'export quel que soit le score, testé).
- `export_allowed` accompagne toujours le score : le kit ne propose l'export que
  si l'audit l'autorise.
- Diagnostics complets : taux d'étayage, densité d'exagérations, niveaux de preuve,
  part datée, couverture exigences/réponses, détails par exigence.

## 3. Règles versionnées et éditables

`career/dossier_quality_rules.json` (version `1.0.0`, mis à jour 2026-10-29) :

- **Interdits factuels** : « expert » sans ≥ 5 ans appuyés, « senior » sans ≥ 3 ans,
  « confirmé » sans années, certification/diplôme/distinction sans preuve d'éducation.
- **Intéressement de la phrase** : promesses non documentées (« garanti », « promets »,
  « à coup sûr », « clé en main »), absolus (« 100 % », « toujours »), superlatifs,
  et appel sentiment (« passionné », « depuis toujours », « vocation »).
- **Parasitage ATS** : mot-clé répété **> 3 fois dans la même liste** (`ats_repetition_threshold`).
- **Arguments génériques** : lexique `generic_phrases` → signal `generic_argument`.
- Édition : fichier local classique, surcharge par `rules_path=` ou variable
  `COME_DOSSIER_QUALITY_RULES` ; une version invalide retombe sur les règles
  intégrées **avec un avertissement** (jamais un crash). Changer le fichier change
  le verdict, jamais les faits du profil (testé).

## 4. Intégration au kit 1-clic (59)

`build_apply_kit()` assemble le dossier puis l'audite ; le rapport remonte tel quel :

- champ **`quality_audit`** de l'`ApplyKit` (serialisé par `asdict()` dans
  `CareerService.build_apply_kit` → endpoint `POST /api/career/apply-kit/{job_id}`) ;
- **étape 2 de la checklist** « audit qualité du dossier avant export », placée
  avant les exports, avec score + verdict dans la note — l'utilisateur voit l'audit
  **avant** de choisir `export_urls` (ROI : corrections en 30 s avant détection par
  le recruteur) ;
- sources auditées : CV markdown + lettre markdown générés, réponses d'intake,
  exigences de l'offre (`prepare_application`), faits approuvés du profil.

Aucune réécriture du brouillon : l'auditeur ne corrige jamais à la place de l'utilisateur.

## 5. Tests — 116 cas (≥ 60 exigés)

`tests/test_claim_check.py` (89) + `tests/test_dossier_quality.py` (27), dont :

- **phrase inventée** (10 cas paramétrés) : chiffre absent, entité absente, compétence absente ;
- **légèrement outrée** (13 cas) : « expert », « senior », « garanti », « toujours », superlatifs, appel sentiment ;
- **hors contexte / chiffres déplacés** (8 cas + dédié) : un chiffre vrai resitué à une autre réalité, unité incohérente, faits de contextes différents assemblés ;
- **arguments faibles / génériques** (8 cas + densité) : « motivé », « dynamique », argument générique qui fait baisser l'argumentaire ;
- **ATS guessing** : répétition au-dessus/au seuil exact, seuil personnalisable ;
- **débordement** : contacts, formules et références d'offre jamais audités ;
- facteurs/formules/verdicts, blocage export sur fait inventé, neutralité 50,
  bornes 0..100, déterminisme, règles éditables, round-trip de la preuve
  (`dated_at` conservé), intégration kit.

## 6. Validation exécutée

```
pytest -q tests/test_claim_check.py tests/test_dossier_quality.py → 116 passed
pytest -q (suite complète) → 2962 passed, 14 failed, 10 skipped
  — les 14 échecs sont PRÉEXISTANTS sur la base 69b55c6 (vérifié stash ↔ re-run,
    liste FAILED identique : explorer/exploration/search_ux/connectors_enrich/
    cv_fit ; aucun n'importe claim_check/dossier_quality/apply_kit)
ruff check career/claim_check.py career/dossier_quality.py career/apply_kit.py tests/… → All checks passed
ruff check . → 9 erreurs, identiques à la base (career/connectors/*.py, non touchés)
./checklist_codex.sh secrets → TOUT VERT ; ./checklist_codex.sh devkit → TOUT VERT
git diff --check → propre
```

## 7. Notes d'honnêteté

- **Recherche avant écriture** : une livraison SPEC-042 antérieure existait sur la
  branche sœur `worker/cvboost-77-1793233986734` (commit `fd9c9ae`, même base
  `69b55c6`), lue et audité ligne à ligne avant d'être reprise comme base — aucun
  travail perdu, aucune v2 recréée à zéro.
- **Correction apportée à cette base** : l'adaptateur de preuves n'acceptait pas la
  clé canonique `dated_at` (ni `proof_date`) → les dates de preuve étaient silencieusement
  perdues, donc la composante « preuve datée » du facteur Preuve ne se déclenchait
  jamais avec cette forme de payload. Corrigé + 3 tests de non-régression ajoutés.
- `checklist_codex.sh` ne peut pas être « tout vert » sur cette base : ses étapes
  `main` (pytest complet) et `lint` échouent sur les 14 tests et 9 erreurs ruff
  **préexistants** listés ci-dessus — aucun n'est introduit par cette mission.
