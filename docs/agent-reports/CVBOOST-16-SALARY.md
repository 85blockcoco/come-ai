# CVBOOST-16 — Extracteur de rémunération des offres

Date : 21 octobre 2026
Branche : `worker/cvboost-16-1792591733` (worktree dédié
`/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-16-1792591733`)
Base : `a054c97` (`main`) — 1373 tests verts avant la mission, **1438 tests verts après**
(65 nouveaux tests dédiés, 1 skip préexistant inchangé).
Aucune dépendance ajoutée, aucun schéma modifié, aucune donnée réelle.

> **Note de relecture.** Une première implémentation de cette mission existe sur la branche
> `agent/cvboost-16-salary-extractor` (commit `bbc49d4`, based sur un `main` plus ancien
> `3a0d1ee`). Cette branche-là a été écrite avant la présente ; elle a servi de **référence
> d'architecture** (voir § 5) mais **n'est pas la base de cette livraison** : ce livrable
> repart du `main` courant, corrige les points relevés en § 8 et ajoute 15 tests de plus.

---

## 1. Ce qui a été construit

### 1.1 `career/cv_quality/models.py` — le modèle `SalaryEvidence`

Nouveau modèle de données, dans le style du module (dataclass `frozen=True, slots=True`) :

| Champ | Type | Rôle |
|---|---|---|
| `raw_text` | `str` | Extrait exact du texte couvert par la mention |
| `source_offset` | `int` | Position de la mention dans le texte source |
| `source_excerpt` | `str` | ~50 caractères autour (remplace `\n` par `⏎`, convention `structure.py`) |
| `min_annual_eur` | `float \| None` | borne basse annualisée |
| `max_annual_eur` | `float \| None` | borne haute annualisée |
| `currency` | `str` | code ISO 4217 (`""` si aucune devise n'est écrite) |
| `salary_type` | `Literal` | `base`, `variable`, `bonus`, `stock`, `equity`, `rsu`, `package`, `total`, `unknown` |
| `periodicity` | `Literal` | `annual`, `monthly`, `hourly`, `unknown` |
| `raw_amount_text` | `str` | le montant tel qu'écrit (`"45 000 €"`, `"55k€"`, `"$80,000"`) |
| `raw_period_text` | `str` | le qualificatif tel qu'écrit (`"brut annuel"`, `"par an"`) |
| `confidence` | `float` | score heuristique 0 → 1 |

Types exportés : `SalaryEvidence`, `SalaryType`, `SalaryPeriodicity` (alias de
`Periodicity`), `Currency`.

**Décision de conception explicitée dans la docstring** : `min_annual_eur` /
`max_annual_eur` portent le montant **annualisé dans la devise du texte**
(`currency`), et non une conversion en euros. Aucun taux de change n'est
appliqué : la mission exige zéro invention, et le test de référence impose
`"$80,000 per year" → min=80000, currency=USD`. Le nom de champ vient de la
spécification de mission ; le docstring du modèle expose la sémantique exacte.

### 1.2 `career/cv_quality/parser.py` — `extract_salary(text)`

Fonction **pure, déterministe, hors-ligne** : aucun réseau, aucun LLM, aucun
effet de bord, aucune valeur par défaut. Elle renvoie la liste des
`SalaryEvidence` trouvées, triées par position.

Pipeline en trois temps :

1. **Balayage des chiffres** : le texte est parcouru une seule fois à la
   recherche de ses chiffres ; le motif complet de montant n'est essayé
   qu'à ces positions.
2. **Lecture du contexte** : pour chaque montant, les mots de la *phrase* qui
   l'entoure (40 caractères avant / après, jamais à cheval sur une
   ponctuation de fin de phrase) sont lus et traduits par table.
3. **Preuve** : nature, périodicité, montants normalisés, provenance exacte et
   score de confiance.

### 1.3 `career/cv_quality/__init__.py`

`extract_salary`, `SalaryEvidence`, `SalaryType`, `SalaryPeriodicity`,
`Periodicity` et `Currency` sont exportés dans l'API publique du module.

---

## 2. Couverture fonctionnelle

### 2.1 Montants et devises

| Écriture | Résultat |
|---|---|
| `45 000 € brut annuel` | 45 000 → 45 000 EUR, annual, base |
| `55k€` / `55K€` | 55 000 EUR |
| `1.5M€` | 1 500 000 EUR |
| `50 000 EUR` / `45.000 EUR` | 45 000 EUR (code ISO + séparateur FR) |
| `$80,000 per year` | 80 000 USD, annual |
| `£45,000 per annum` | 45 000 GBP, annual |
| `¥6,000,000 per year` | 6 000 000 JPY, annual |
| `€45 000 brut annuel` | 45 000 EUR (symbole avant le montant) |
| `45 000 euros par an` | 45 000 EUR, annual (forme française en toutes lettres) |
| `45 000 €` (espace insécable) | 45 000 EUR |
| `45,50 €` | 45,50 EUR (virgule décimale) |

### 2.2 Fourchettes

| Écriture | Résultat |
|---|---|
| `45-55k€` | 45 000 → 55 000 EUR (le suffixe `k` couvre toute la fourchette) |
| `50 k - 60 k €` | 50 000 → 60 000 EUR |
| `40k–60k` | 40 000 → 60 000 (tiret demi-cadratin) |
| `entre 40k et 50k€` | 40 000 → 50 000 EUR |
| `between 50k and 60k` | 50 000 → 60 000 |
| `50k to 60k EUR` | 50 000 → 60 000 EUR |
| `55 000 € à 70 000 € brut annuel` | 55 000 → 70 000 EUR, annual, base |

### 2.3 Types de rémunération

`base` (salaire, rémunération, brut, net, fixe, compensation), `variable`,
`bonus` (bonus, prime, commission), `stock`, `equity`, `rsu`, `package`,
`total` (total compensation, CTC, compensation totale, rémunération totale).

### 2.4 Périodicités

`annual` (brut annuel, par an, /an, /année, per annum, per year, annuel,
annuelle, annuellement), `monthly` (mensuel, par mois, /mois, per month,
monthly), `hourly` (par heure, /heure, per hour, hourly).

### 2.5 Zéro invention

- Aucun montant n'est inventé : liste vide si rien n'est écrit.
  `extract_salary("Pas de salaire mentionné") == []`.
- Un pourcentage n'est **pas** un montant : `Variable 20%` → type `variable`,
  `min_annual_eur = None`, `max_annual_eur = None`.
- Un nombre d'actions/unités n'est **pas** un montant : `RSU 5000 units` →
  type `rsu`, montants `None` ; `Stock options 1000 shares` → type `stock`.
- Un nombre sans devise, sans échelle et sans mot-clé n'est pas une mention :
  `"Créée en 2019, la société emploie 30 personnes."` → liste vide.
- `"50k downloads"` est rejeté (compteur non salarial) : liste vide.

---

## 3. Provenance

Chaque evidence porte la position exacte et l'extrait vérifiable. L'invariant
est strict : `text[source_offset : source_offset + len(raw_text)] == raw_text`.

```python
text = "Nous recherchons un ingénieur. Rémunération : 45 000 € brut annuel."
ev = extract_salary(text)[0]

ev.source_offset   # 46  (début de la mention)
ev.source_excerpt  # 50 caractères autour, "\n" rendu "⏎"
ev.raw_text        # "45 000 € brut annuel"
ev.raw_amount_text # "45 000 €"
ev.raw_period_text # "brut annuel"
assert text[ev.source_offset:ev.source_offset + len(ev.raw_text)] == ev.raw_text
```

Le `raw_text` s'étend au mot-clé collé au montant (`"Package 70k€ brut
annuel"` → la mention complète) et au qualificatif qui suit
(`"45 000 € brut annuel"`).

---

## 4. Score de confiance

Score heuristique borné à [0, 1] : base 0,15 ; +0,35 devise ; +0,25 type
explicite ; +0,15 périodicité ; +0,10 mot-clé collé ; +0,10 fourchette ;
+0,05 suffixe d'échelle ; −0,15 pourcentage ou nombre d'unités. Plafond 0,98.

| Mention | Confiance |
|---|---|
| `Package 70k€ brut annuel` | 0,98 |
| `Salaire brut annuel : 45 000 €` | 0,90 |
| `$80,000 per year` | 0,65 |
| `50k` (ambigu) | 0,20 |
| `Variable 20%` | 0,35 |

Le consommateur (Service / Router, hors périmètre de cette mission) peut donc
filtrer sur `salary_type` et `confidence` : une mention `type="unknown"` et
`confidence < 0.5` est un montant cité dans l'offre qui n'est pas
explicitement un salaire (montant de levée de fonds, ticket restaurant…).

---

## 5. Performance

La mission impose **≤ 5 ms pour un texte de 50 000 caractères**. Deux
architectures ont été essayées ; la première (grosse regex d'alternances,
`re.IGNORECASE`, appliquée au texte entier) plafonnait à **83 ms** sur 50 k
caractères.

L'implémentation retenue évite les deux causes de lenteur mesurées :

- les alternances de regex à 40 branches (18 → 40 ms selon la casse) ;
- le coût d'appel des regex (≈ 3 µs par `finditer` de fenêtre).

Elle applique à la place : un **balayage unique des chiffres** (le motif de
montant n'est essayé qu'aux positions de chiffres), une **lecture du contexte
mot à mot** dans la phrase qui entoure le montant, traduite par tables
(« brut », « annuel », « package »…), et un **filtrage précoce** (un nombre
sans devise, sans échelle `k`/`M` et sans mot-clé n'est pas une mention).

Mesures (Apple Silicon, 30 exécutions, texte d'offre réaliste) :

| Taille du texte | Temps (médiane) | p95 | Mentions |
|---|---|---|---|
| 1 000 caractères | 0,12 ms | 0,18 ms | 2 |
| 5 000 caractères | 0,18 ms | 0,23 ms | 2 |
| **50 000 caractères** | **0,60 ms** | 0,73 ms | 2 |

Soit **≈ 8× la marge** sur l'exigence de 5 ms. Le coût est dominé par le
balayage linéaire du texte ; il est **indépendant du nombre de mentions** (une
mention coûte ≈ 35 µs). Un texte pathologique de 33 000 caractères contenant
1 500 mentions (phrase répétée 500 fois) monte à ≈ 56 ms : le coût suit alors
le nombre de mentions, pas la taille du texte — c'est le comportement de
l'implémentation de référence `agent/cvboost-16-salary-extractor` (≈ 53 ms
sur le même texte).

---

## 6. Tests

`tests/test_salary_extractor.py` — **65 tests**, tous synthétiques, aucun
fichier externe, aucune donnée réelle.

- 20 tests couvrent la table de référence de la mission
  (`45 000 € brut annuel`, `55k€`, `45-55k€`, `50 k - 60 k €`, `$80,000 per year`,
  `£45,000 per annum`, `4 500 € mensuel`, `50k`, `Package 70k€ brut annuel`,
  `Bonus 10k€`, `RSU 5000 units`, `Variable 20%`, `entre 40k et 50k€`,
  `between 50k and 60k`, `Pas de salaire mentionné`, `Base 50k€ + bonus 10k€`,
  `1.5M€`, `Stock options 1000 shares`, `RSU 2000 units vesting 4 ans`,
  scoring de confiance).
- + 45 tests : formes complémentaires, zéro invention, provenance, multi-mentions,
  frontières entre mentions, déterminisme, pureté, helpers internes, performance.

```
$ .venv/bin/python -m pytest -q tests/test_salary_extractor.py
65 passed in 0.94s

$ .venv/bin/python -m pytest -q
1438 passed, 1 skipped in 85.27s

$ .venv/bin/python -m ruff check .
All checks passed!

$ git diff --check
(propre)
```

---

## 7. Hors périmètre (conforme à la mission)

Non touchés : `career/service.py`, `career/router.py`, `career_static/*`,
`requirements*.txt`, migrations, `SCHEMA_VERSION`. Le raccordement de
`extract_salary()` au pipeline d'offres (affichage de la rémunération dans les
résumés) est laissé à la mission suivante : l'extracteur est ici une API
publique testée et sans effet de bord.

## 8. Points d'attention pour la relecture

1. **Pas de conversion de devises.** `min_annual_eur` est le montant annualisé
   dans la devise du texte. Le nom de champ est imposé par la spécification de
   mission ; le comportement est documenté dans le docstring du modèle. Si la
   relecture veut un vrai EUR, il faut un taux de change explicite (donc une
   source de taux) — ce serait une invention, hors exigence « zéro invention ».
2. **Le champ `salary_type` vaut `unknown` pour un montant non qualifié**
   (`55k€`). C'est volontaire : `base` serait une interprétation.
3. **Les montants non salariaux sont remontés** (montant de levée de fonds,
   ticket restaurant) avec un type `unknown` et une confiance basse : le
   filtrage se fait côté consommateur sur `confidence` / `salary_type`.
4. **Heure annuelle : 1 820 h** (35 h × 52 semaines, convention française).
   Le taux horaire est annualisé avec cette constante, documentée dans le
   code. À confirmer si la convention d'entreprise est différente.
5. **Écarts assumés par rapport à `agent/cvboost-16-salary-extractor`** (sur
   33 cas comparés, 2 écarts, tous volontaires) :
   - `"Le salaire est de 45 000 euros par an."` → type `base` ici, `unknown`
     sur la branche de référence : « salaire » *est* la rémunération de base.
   - `"50k downloads"` → ignoré ici, remonté par la branche de référence :
     un compteur de trafic n'est pas un salaire.
   Le factoring horaire (1 820 h/an) et la convention de devise sont alignés
   sur la branche de référence.
6. **Le seuil de 5 ms** est mesuré au meilleur de 3 runs pour ignorer le bruit
   de l'ordonnanceur ; la marge réelle est d'un facteur 8.
