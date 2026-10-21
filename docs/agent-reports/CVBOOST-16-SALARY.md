# CVBOOST-16 — Extracteur de rémunération des offres

Statut : TERMINÉE (fixtures synthétiques ; aucune donnée réelle ; aucun réseau ; aucun envoi).

Branche de travail : `worker/cvboost-16-1792575336` (base `main` @ `3a0d1ee`).
Périmètre : `career/cv_quality/` uniquement — aucun autre module touché, aucun
consommateur existant modifié, `SCHEMA_VERSION` inchangé, aucune migration.

---

## 1. Ce qui a été construit

| Fichier | Rôle |
| --- | --- |
| `career/cv_quality/models.py` | **Étendu** — `Currency`, `SalaryType`, `Periodicity`, `SalaryEvidence` (+ docstrings de contrat) |
| `career/cv_quality/parser.py` | **Étendu** — `extract_salary(text) -> list[SalaryEvidence]` et toute la logique locale (motifs, normalisation, provenance, confiance) |
| `career/cv_quality/__init__.py` | **Étendu** — export de `extract_salary`, `SalaryEvidence`, `Currency`, `SalaryType`, `Periodicity` |
| `tests/test_salary_extractor.py` | **Nouveau** — 50 tests synthétiques (dont les 20 cas imposés par la mission) |
| `docs/agent-reports/CVBOOST-16-SALARY.md` | Ce rapport |

API publique :

```python
from career.cv_quality import extract_salary

for evidence in extract_salary(offer["description_original"]):
    print(evidence.raw_amount_text, evidence.min_annual_eur, evidence.currency, evidence.salary_type)
```

## 2. Le contrat livré

Chaque occurrence de rémunération dans le texte libre devient une
`SalaryEvidence` :

| Champ | Contenu |
| --- | --- |
| `raw_text` | Expression exacte telle qu'écrite : `"45 000 € brut annuel"` |
| `source_offset` | Position du début de l'expression dans le texte source |
| `source_excerpt` | ≤ 50 caractères de contexte **contenant l'expression entière** |
| `min_annual_eur` / `max_annual_eur` | Bornes annualisées (voir § 3 — pas de conversion de change) |
| `currency` | Code ISO lu dans le texte (`EUR`, `USD`, `GBP`, `JPY`, `CHF`, `CAD`, `AUD`, `SEK`, `NOK`, `DKK`, `PLN`, `INR`, `CNY`) ou `""` si le texte n'en porte aucune |
| `salary_type` | `base`, `variable`, `bonus`, `stock`, `equity`, `rsu`, `package`, `total` ou `unknown` |
| `periodicity` | `annual`, `monthly`, `hourly` ou `unknown` (périodicité *explicitement* écrite) |
| `raw_amount_text` | Montant exact : `"45 000 €"`, `"45-55k€"`, `"$60,000"`, `"20%"` |
| `raw_period_text` | Périodicité exacte : `"brut annuel"`, `"par an"`, `"mensuel"`, `"per year"` |
| `confidence` | Score 0–1 déterministe (jamais une promesse sur la qualité de l'offre) |

### 3. Règles de normalisation (et ce qui n'est **pas** fait)

- **k / M** : `55k€` → 55 000 ; `1.5M€` → 1 500 000. La lettre qui suit le
  suffixe ne doit pas être une lettre (`45 km` n'est donc pas 45 000).
- **Séparateurs de milliers** : `45 000`, `45,000`, `45.000` → 45 000 ;
  `45,50` → 45,5 ; `45.000,50` → 45 000,5. Le nombre de chiffres après le
  séparateur décide (3 = milliers, 1-2 = décimale).
- **Annualisation** : mensuel × 12, horaire × `HOURS_PER_YEAR` (1820 = 35 h
  × 52 semaines, convention fixe et documentée), annuel × 1.
- **Aucune conversion de change.** `min_annual_eur` / `max_annual_eur`
  portent le montant annualisé **dans la devise de l'evidence** (le nom
  historique du champ mentionne EUR ; pour une offre EUR — le cas courant —
  les deux lectures coïncident). Le package n'a pas de table de taux :
  convertir reviendrait à inventer un nombre. Pour un montant sans devise
  lue (`50k`), `currency` vaut `""` et la confiance est basse (0,20).
- **Zéro invention.** Un texte sans rémunération → liste vide. Un nombre sans
  devise ni suffixe k/M (`45 000` seul) → ignoré. Un pourcentage ou un
  nombre d'unités n'est retenu que s'il est rattaché à une composante
  nommée (`variable`, `bonus`, `stock`, `equity`, `rsu`) et ses montants
  restent `None` (non convertibles en EUR).

### 4. Types et périodicités reconnus

- **Types** : `base` (`base`, `base salary`, `salaire de base`, `fixe`),
  `variable` (`variable`, `part variable`, `commission`), `bonus` (`bonus`,
  `prime`), `stock` (`stock`, `stock options`), `equity` (`equity`),
  `rsu` (`RSU`, `restricted stock`), `package` (`package`,
  `compensation package`), `total` (`total compensation`, `CTC`,
  `rémunération totale`).
- **Périodicités** : `par an`, `par année`, `/an`, `/année`, `annuel`,
  `par mois`, `/mois`, `mensuel`, `per month`, `par heure`, `/heure`,
  `horaire`, `per hour`, `per year`, `per annum`, `/yr`.
- **Attribution** : le mot le plus proche du montant gagne ; à égalité, le
  mot écrit **avant** le montant gagne, puis l'ordre de priorité des tables.
  Le contexte est lu dans la phrase uniquement (les ruptures `. ; ! ? , | +`
  et les retours à la ligne coupent le contexte — `+` sépare deux
  composantes : `base 50k€ + bonus 10k€`).
- **`brut` / `net` / `gross`** : ce sont des qualificatifs, pas des types.
  Isolés, ils décrivent la rémunération **de base** (`salary_type="base"`) ;
  combinés à un type explicite, le type explicite l'emporte
  (`Package 70k€ brut annuel` → `package`).

### 5. Confiance (formule déterministe)

```
0,15 (base)
+0,45 si une devise est lue
+0,20 si un mot-clé de rémunération, un type ou un qualificatif entoure le montant
+0,25 si une périodicité est lue
+0,15 si un type ou un qualificatif est lu
+0,05 si le suffixe k/M est présent
+0,05 si le montant est une fourchette
plafond 0,98 — et 0,49 pour un composant non monétaire (%, unités)
```

Exemples mesurés : `Salaire : 45 000 € brut annuel` → 0,98 ;
`$80,000 per year` → 0,85 ; `55k€` → 0,65 ; `50k` → 0,20 ;
`Variable 20%` → 0,49.

## 4. Preuves réelles

### Tests ciblés

```
$ .venv/bin/python -m pytest -q tests/test_salary_extractor.py
50 passed
```

Les 20 cas imposés par la mission sont couverts un par un
(`test_salary_simple_eur`, `test_salary_k_eur`, `test_salary_range`,
`test_salary_range_spaces`, `test_salary_usd`, `test_salary_gbp`,
`test_salary_monthly`, `test_salary_k`, `test_salary_package`,
`test_salary_bonus`, `test_salary_equity`, `test_salary_variable`,
`test_french_expressions`, `test_english_expressions`, `test_no_salary`,
`test_multiple_salaries`, `test_k_m_suffix`, `test_stock_options`,
`test_rsu`, `test_confidence_scoring`), plus 30 tests de contrat
(provenance exacte, déterminisme, bornes de confiance, zéro invention,
performance, pureté du module).

### Suite complète

```
$ .venv/bin/python -m pytest -q
1417 passed, 1 skipped in 103.02s
```

(1367 tests avant la mission → 1417 après : aucune régression, l'unique
skip est préexistant — `tests/test_offer_summary_exhaustiveness.py`.)

### Lint et propreté

```
$ .venv/bin/python -m ruff check .
All checks passed!
$ git diff --check
(clean)
```

### Performance (mesurée sur cette machine, 30 exécutions)

| Cas | Longueur | Médiane | Max |
| --- | --- | --- | --- |
| Offre réaliste (5 occurrences) | 50 000 car. | **0,59 ms** | 0,77 ms |
| Offre sans rémunération | 57 600 car. | **0,57 ms** | 0,90 ms |
| Cas dense synthétique (1 200 occurrences) | 38 400 car. | 54,5 ms | 82,9 ms |

La contrainte « ≤ 5 ms pour un texte de 50k caractères » est tenue pour une
description d'offre réelle. Le coût est linéaire en la **longueur** du texte
(≈ 0,01 ms par millier de caractères) et proportionnel au **nombre
d'occurrences** (≈ 25 µs par occurrence) : un texte artificiel qui répète
1 200 rémunérations sort du budget, c'est documenté tel quel.

Comment le coût est tenu : le texte est d'abord balayé à la recherche d'un
chiffre (`_DIGIT_RE`, scan C), le motif de montant complet n'est essayé
qu'aux positions utiles, et le contexte (types, périodicités,
qualificatifs) est lu mot par mot via des tables au lieu d'une longue
alternative de motifs.

### Exemples d'extraction (sortie réelle)

```
'45 000 € brut annuel'
  raw_text='45 000 € brut annuel'  amount='45 000 €'  period='brut annuel'
  min=45000.0 max=45000.0 cur='EUR' type='base' per='annual' conf=0.98

'Package 70k€ brut annuel'
  raw_text='Package 70k€ brut annuel'  amount='70k€'  period='brut annuel'
  min=70000.0 max=70000.0 cur='EUR' type='package' per='annual' conf=0.98

'Base 50k€ + bonus 10k€'
  → 2 evidences : base (50 000 €) puis bonus (10 000 €)

'4 500 € mensuel'
  min=54000.0 max=54000.0 cur='EUR' type='unknown' per='monthly' conf=0.85

'Variable 20%'
  raw_amount='20%'  min=None max=None cur='' type='variable' conf=0.49

'RSU 2000 units vesting 4 ans'
  → 1 evidence : type='rsu', min=None (le « 4 ans » n'est pas un salaire)
```

## 5. Limites honnêtes

- **Pas de conversion de change.** `$80,000` reste 80 000 USD. C'est un
  choix : le package n'a pas de table de taux et aucun taux ne peut être
  inventé. Une conversion exigirait une table datée, injectée par l'appelant
  (à traiter côté intégrateur, Mission 10).
- **Pas de distinction brut/net dans les montants.** `45 000 € brut` et
  `45 000 € net` produisent le même montant ; le qualificatif est conservé
  dans `raw_period_text` (« brut annuel »), pas retraduit.
- **Le champ `min_annual_eur` porte la devise de l'evidence.** Le nom est
  historique ; le comportement est documenté dans `models.py` et § 3.
- **Les montants sans devise explicite ne sont retenus qu'avec le suffixe
  k/M** (`50k`). `45 000` seul est ignoré : sans devise, un montant annuel
  ne serait qu'une supposition.
- **Détection lexicale, pas sémantique.** Un budget d'équipement (« budget
  de 20 000 € ») est lu comme un montant ; la confiance (0,60) et le type
  (`unknown`) signalent qu'il faut vérifier. Inversement, une rémunération
  écrite sans chiffre (« selon profil ») n'est évidemment pas détectée.
- **`+` coupe le contexte.** C'est voulu (séparation de composantes) mais
  une offre écrivant « package 70k€ + 10% variable » sans virgule reste
  correctement typée : le `+` coupe, le mot le plus proche gagne.
- **Convention horaire 35 h × 52 semaines** : documentée, mais conventionnelle.
  Une offre mensuelle est exacte ; une offre horaire dépend de la convention.
- **Non testé sur données réelles ni en navigateur** : hors périmètre de la
  mission (aucune intégration UI n'est faite ici).

## 6. Adoption proposée par l'intégrateur (Mission 10)

1. Appeler `extract_salary(offer["description_original"])` au moment de la
   synthèse d'offre et afficher `min_annual_eur`/`max_annual_eur` avec
   `currency` et `raw_amount_text` — le montant affiché est toujours
   traçable au texte exact.
2. Ne jamais afficher `min_annual_eur` sans `currency` : un montant sans
   devise affichée est trompeur.
3. Ne pas additionner les composantes (`base` + `bonus` + `package`) sans
   vérification : rien ne garantit qu'elles s'additionnent, et le package
   peut déjà inclure la base.
4. Utiliser `confidence` comme un filtre d'affichage : sous 0,50, afficher
   le libellé exact (`raw_amount_text`) plutôt qu'un montant.
5. `career/service.py`, `career/router.py` et `career_static/*` sont
   **interdits** dans cette mission : rien n'a été modifié de ce côté, le
   branchement reste à faire côté intégrateur.

## 7. Rollback

Modification additive sur une branche dédiée : `git revert` du commit, ou
suppression des blocs ajoutés (`extract_salary` + modèles) — aucune base,
aucune migration, aucun consommateur existant, aucun changement de schéma.
