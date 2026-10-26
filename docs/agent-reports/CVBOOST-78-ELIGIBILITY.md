# CVBOOST-78 — SPEC-043 — Vérificateur d'éligibilité par offre

**Statut :** livré · **Branche :** `agent/spec-043-eligibility` (base `2e52575`) · **Priorité :** P0 (audit externe 23/10 §4-2)

## Ce qui est livré

### 1. `career/rules_eligibility.json` — PROFIL APPROUVÉ versionné, éditable

Fichier de règles locales (schéma `eligibility_rules`, `version: 1`) contenant les
tickets remplis par la personne, **jamais devinés** :

| Ticket | Contenu |
|---|---|
| `profile_approved` | verrou principal : `false` par défaut, aucun ÉLIGIBLE possible tant qu'il n'est pas passé à `true` |
| `rules.contract.accepted` | contrats recherchés (`internship`, `apprenticeship`, `fixed_term`, `permanent`, `VIE`, `graduate`) |
| `rules.duration.minimum_months` | durée minimale acceptée (1–24) |
| `rules.education` | `profile_level` (bac → doctorat) et `profile_fields` (filières) |
| `rules.work_authorization` | **WORK AUTH explicite** : `status` (étudiant, salarié…), `work_permits` (codes ISO-2 ou régions fermées `EU`/`EEA`), `visa_sponsorship_needed` (`true`/`false`/`null` = non rempli) |
| `rules.location` | `countries`, `excluded_countries`, `excluded_cities`, `work_modes` |
| `rules.languages.profile_levels` | `{langue: niveau}` (CECRL a1→c2 ou `native`) |

Le fichier livré a tous les tickets vides (`profile_approved: false`) : hors du
démarrage, aucun verdict positif n'est possible sans relecture humaine.

### 2. `career/eligibility.py` — moteur pur, déterministe, hors-ligne

- **Aucune IA décisionnelle** : le moteur ne lit aucun texte libre, il consomme
  les faits déjà extraits par les couches déterministes existantes —
  `offer_qualification` (contrat, durée, pays — sk02/sk13), faits de conditions
  SK-17 (`visa_sponsorship`, `remote`/`hybrid`/`onsite`), relevés
  `offer_requirements.analyze_offer` (niveau d'étude, filière, langues), repli
  `education_access`.
- **8 clauses** : contrat, durée, niveau d'étude, filière, permis de travail
  (ticket pays), sponsorisation de visa (ticket), localisation (pays/ville),
  mode de travail, langues.
- **Principe « jamais de verdict positif implicite »** : toute donnée manquante
  (ticket vide, extraction non exécutée, exigence illisible, langue hors
  vocabulaire, mode de travail contradictoire) produit `À VÉRIFIER` avec le
  point cité dans `points_a_verifier`. « Extraction absente » n'est jamais
  traitée comme « absence d'exigence ».
- **Sortie** : `{verdict, clauses: [{rule, label, exigence_offre, fait_profil,
  statut_ok, preuve{offre, profil}}], etat_suivant, points_a_verifier,
  motifs_non_eligibilite, rules_version, profile_approved}` avec
  `etat_suivant` ∈ `classable` / `a_verifier` / `exclue_du_classement`.
- Validation stricte des règles (`validate_rules` + `RulesError`) : section
  inconnue, statut/permis/niveau/mode de travail inconnus → erreur signalée,
  jamais une valeur devinée.

### 3. Branchement radar / dailies (CVBOOST-35)

- `apply_eligibility_to_offers(offers, rules, conditions_by_offer=…,
  requirements_by_offer=…)` annote chaque offre (`offer["eligibility"]`) et
  re-classe le lot : les **NON ÉLIGIBLES passent en fin de liste** — marquées,
  sorties du classement par défaut, mais visibles avec leurs motifs pour
  apprendre pourquoi. Entrée jamais mutée.
- `eligibility_ranking_key` : clé de classement autonome, composable avec la
  clé de pertinence d'`exploration.ranking_key`.
- `career/exploration.py::ranking_key` intègre le verdict SPEC-043 comme second
  critère : une offre annotée NON ÉLIGIBLE passe sous les autres ; sans
  annotation (`eligibility` absent), **l'ordre existant est inchangé**.

## Décisions notables

1. **Salvage** : une tentative antérieure de la même mission (ordre
   cvboost-78-1793025534312, worktree abandonné sans commit) avait laissé
   `career/eligibility.py` + `career/rules_eligibility.json` non committés,
   sans tests ni rapport. Ce travail a été revu, corrigé et complété plutôt que
   réécrit (travail repris : oui, signalé au lieu d'être dissimulé).
2. **Corrections apportées au moteur récupéré** :
   - tables de niveaux d'étude indexées en espace normalisé (`normalized_text`
     écrit « bac+3 » → « bac 3 » : l'ancienne table rendait tout niveau invalide) ;
   - exigence « langue maternelle » (`native`) face à un profil C2 : `À VÉRIFIER`
     et non un blocage (un diplôme ne prouve pas une langue maternelle) ;
   - exigence de langue hors vocabulaire fermé : clause dédiée `À VÉRIFIER`
     au lieu d'un « aucune langue exigée » implicite ;
   - `requirements` passé en argument prime sur ceux portés par l'offre ; une
     entrée non-liste (champ tableau brut) compte comme extraction absente ;
   - clé de classement : score entier ou flottant.
3. **SK-17/SK02 non présents sur cette branche** : les modules d'extraction de
   conditions et de dates n'existent pas encore ici ; le moteur dégrade
   proprement (`conditions=None` → `À VÉRIFIER`) et le contrat de forme des
   faits est verrouillé par les tests (dataclass `to_dict`).
4. **Filière** : un écart de filière n'est jamais un blocage prouvé (« ou
   équivalent ») → `À VÉRIFIER`, jamais NON ÉLIGIBLE.

## Tests — 88 cas (contrat ≥ 45)

`tests/test_eligibility.py` : chargement/validation des règles (10), forme de
sortie (6), anti-faux-positifs (3), contrat (7), durée (5), école (10), WORK
AUTH pays (6), visa (6), localisation/mode de travail (14), langues (7),
agrégation (6), radar/classement (8). Matrice de mission couverte : alternance
OK, statut étudiant vs CDI, visa inconnu, durée courte, école exigence
manquante, langues, missing cond data → `À VÉRIFIER`, aucun ÉLIGIBLE sans
preuve citée (`assert_no_false_eligible`).

## Vérifications

```
pytest -q tests/test_eligibility.py → 88 passed
pytest -q (suite complète)          → 1630 passed, 2 failed (pré-existants, voir ci-dessous), 1 skipped
doctest career/eligibility.py       → 4 ok
ruff check (fichiers mission)       → All checks passed!
./checklist_codex.sh                → TOUT VERT (DevKit 207 passed, secrets ok)
git diff --check                    → propre
```

**2 échecs pré-existants** : `tests/test_geo_ranking.py::test_ranking_integration_uses_the_total_score`
et `::test_internship_selection_reports_the_geographic_signal` échouent aussi
sur la base `2e52575` sans la moindre modification (vérifié par stash de
`career/exploration.py`) — hors périmètre de la mission, à traiter séparément.

## Files d'entrée pour l'intégration

- Verdict d'une offre : `check_eligibility(offer, rules, conditions=…, requirements=…)`.
- Lot du radar : `apply_eligibility_to_offers(offers, rules)`.
- Règles à éditer par la personne : `career/rules_eligibility.json`.
