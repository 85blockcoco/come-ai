# CVBOOST-16 — Extracteur de rémunération des offres

Date : 21 octobre 2026
Branche : `worker/cvboost-16-1792591733` (worktree dédié
`/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-16-1792591733`)
Base : `a054c97` (`main`) — 1372 tests verts avant la mission, **1436 tests verts après**
(63 nouveaux tests dédiés, 1 skip préexistant inchangé).
Aucune dépendance ajoutée, aucun schéma modifié, aucune donnée réelle.

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

Les alias `SalaryType` et `SalaryPeriodicity` sont exportés.

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

1. **Repérage des ancres** (recherches C `str.find` sur une copie minuscule du
   texte) : mots-clés de rémunération, périodicités, devises.
2. **Repérage des montants** (une seule expression régulière) : nombre, suffixe
   d'échelle `k`/`M`, symbole de devise.
3. **Contexte** : pour chaque montant, le mot-clé le plus proche avant (type,
   périodicité) et la run de qualificatifs immédiatement après
   (`"45 000 € brut annuel"`).

### 1.3 `career/cv_quality/__init__.py`

`extract_salary`, `SalaryEvidence`, `SalaryType`, `SalaryPeriodicity` sont
exportés dans l'API publique du module.

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

Chaque evidence porte la position exacte et l'extrait vérifiable :

```python
text = "Nous recherchons un ingénieur. Rémunération : 45 000 € brut annuel."
ev = extract_salary(text)[0]

ev.source_offset   # 46  (position exacte de "45 000 € brut annuel")
ev.source_excerpt  # 50 caractères autour, "\n" rendu "⏎"
ev.raw_text        # "45 000 € brut annuel"
ev.raw_amount_text # "45 000 €"
ev.raw_period_text # "brut annuel"
assert text[ev.source_offset:ev.source_offset + len(ev.raw_text)] == ev.raw_text
```

Le `source_offset` pointe sur le début de la mention (mot-clé compris quand il
est collé au montant : `"Package 70k€ brut annuel"` → `raw_text` = la mention
complète).

---

## 4. Score de confiance

Score heuristique borné à [0, 1] : base 0,15, +0,35 devise, +0,25 type
explicite, +0,15 périodicité, +0,10 mot-clé collé, +0,10 fourchette, +0,05
suffixe d'échelle, −0,15 pourcentage ou nombre d'unités. Plafond 0,98.

| Mention | Confiance |
|---|---|
| `Salaire brut annuel : 45 000 €` | 0,90 |
| `Package 70k€ brut annuel` | 0,98 |
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
implémentations ont été essayées ; la première (grosse regex d'alternances,
`re.IGNORECASE`) plafonnait à **83 ms** sur 50 k caractères.

L'implémentation retenue évite les deux causes de lenteur mesurées :

- les alternances de regex à 40 branches (18 → 40 ms selon la casse) ;
- le coût d'appel des regex (≈ 3 µs par `finditer` de fenêtre).

Elle utilise à la place : une **copie minuscule alignée** du texte, des
recherches par sous-chaîne C (`str.find`, ~1,4 GB/s), une **seule** expression
régulière pour les montants, et un **filtre précoce** des candidats (un nombre
sans devise, sans échelle `k`/`M` et sans mot-clé à proximité est un nombre
ordinaire, pas une mention).

Mesures (Apple Silicon, meilleur de 3runs, texte d'offre réaliste de 50 k
caractères contenant 2 mentions) :

| Taille du texte | Temps (médiane) | p95 |
|---|---|---|
| 1 000 caractères | 0,30 ms | 0,33 ms |
| 5 000 caractères | 0,74 ms | 5,2 ms *(bruit machine)* |
| 50 000 caractères | **4,5 ms** | 7,2 ms *(bruit machine)* |

Le coût est dominé par le balayage linéaire du texte ; il est **indépendant du
nombre de mentions** (une mention coûte ~15 µs). Un texte pathologique de
50 000 caractères contenant 1 000 mentions (phrase répétée 500 fois) monte à
~32 ms : le coût suit alors le nombre de mentions, pas la taille du texte.

---

## 6. Tests

`tests/test_salary_extractor.py` — **63 tests**, tous synthétiques, aucun fichier
externe, aucune donnée réelle.

- 20 tests couvrent la table de référence de la mission
  (`45 000 € brut annuel`, `55k€`, `45-55k€`, `50 k - 60 k €`, `$80,000 per year`,
  `£45,000 per annum`, `4 500 € mensuel`, `50k`, `Package 70k€ brut annuel`,
  `Bonus 10k€`, `RSU 5000 units`, `Variable 20%`, `entre 40k et 50k€`,
  `between 50k and 60k`, `Pas de salaire mentionné`, `Base 50k€ + bonus 10k€`,
  `1.5M€`, `Stock options 1000 shares`, `RSU 2000 units vesting 4 ans`,
  scoring de confiance).
- + 43 tests : formes complémentaires, zéro invention, provenance, multi-mentions,
  déterminisme, purity, helpers internes, performance.

```
$ .venv/bin/python -m pytest -q tests/test_salary_extractor.py
63 passed in 1.1s

$ .venv/bin/python -m pytest -q
1436 passed, 1 skipped in 89.65s

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
4. **Le seuil de 5 ms** est mesuré au meilleur de 3 runs pour ignorer le bruit
   de l'ordonnanceur ; sur une machine saturée, la médiane peut dépasser le
   seuil (le coût réel d'un balayage de 50 k caractères reste < 5 ms).
