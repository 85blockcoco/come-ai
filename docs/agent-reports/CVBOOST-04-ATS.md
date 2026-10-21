# CVBOOST-04 — Contrôle ATS local PDF/DOCX

> **Mission 04** — analyser le fichier exporté (PDF / DOCX / TXT) pour repérer les
> **risques ATS** (Applicant Tracking System), **sans jamais appeler de service distant**.
> Base : `main` / branche `agent/cvboost-04-ats` — 100 % local, déterministe, hors-ligne.

---

## 1. Livrable

| Fichier | Rôle | État |
|---|---|---|
| `career/cv_quality/ats.py` | **nouveau** — 9 détecteurs + score pondéré + label | 100 % local, déterministe |
| `career/cv_quality/models.py` | étendu — `ATSFinding`, `ATSCheckResult`, `ATSRiskLevel` | compatible Mission 01 |
| `career/cv_quality/__init__.py` | export de `run_ats_check`, `run_ats_check_bytes`, `run_ats_check_file` | API publique |
| `tests/test_cv_quality_ats.py` | **42 tests** — fixtures PDF/DOCX synthétiques | tous verts |
| `docs/agent-reports/CVBOOST-04-ATS.md` | ce rapport | — |

**Hors périmètre respecté** : `career/service.py`, `career/router.py`, `career_static/*`,
`requirements*.txt`, migrations, `SCHEMA_VERSION` — **aucun fichier touché**.

---

## 2. API publique

```python
from career.cv_quality import run_ats_check, run_ats_check_bytes, run_ats_check_file

# 1) Analyse complète (structure PDF/DOCX réelle : positions, images, tableaux, colonnes)
result = run_ats_check_file("cv.pdf")
result = run_ats_check_bytes(data, "pdf", expected_sections=["Expérience", "Projets"])

# 2) Analyse à partir d'un DocumentInput existant (Mission 01) — repli texte
result = run_ats_check(document, expected_sections=None)
```

`run_ats_check(document, *, expected_sections=None, file_bytes=None)` :

| Argument | Rôle |
|---|---|
| `document` | `DocumentInput` (Mission 01) — texte + métadonnées |
| `expected_sections` | sections attendues ; défaut `["Expérience", "Formation", "Compétences"]` |
| `file_bytes` | octets bruts optionnels : active l'analyse **structurelle** complète |

> `file_bytes` est **optionnel** : sans lui l'analyse reste correcte mais porte sur le
> texte aplati (pas de position, pas d'image, pas de tableau natif). Les octets sont
> réinjectés par `run_ats_check_bytes` / `run_ats_check_file`, qui sont les points
> d'entrée recommandés côté application.

### Sortie

```python
ATSCheckResult(
    findings=[ATSFinding(code, risk_level, message, page, bbox, evidence_excerpt, error)],
    risk_score=0,          # 0-100, pondéré (LOW=5, MEDIUM=20, HIGH=50), plafonné à 100
    risk_label="LOW",      # "LOW" | "MEDIUM" | "HIGH"
    pages_analyzed=1,
    parse_errors=[],
    risk_interpretation="Faible risque",
)
```

* `ATSFinding.page` : numéro de page **1-based** (`0` = constat global au document).
* `ATSFinding.bbox` : `(x0, y0, x1, y1)` en points PDF, ou `None` quand la position
  n'est pas connue (DOCX).
* `ATSFinding.evidence_excerpt` : extrait vérifiable (≤ 160 caractères, une seule ligne).
* `ATSFinding.error` : `"PARSE_ERROR"` pour les constats d'échec d'extraction.

---

## 3. Vocabulaire prudent

Le module parle exclusivement de **risques** et de **relecture conseillée** :

| Label | Interprétation affichée |
|---|---|
| `LOW` | « Faible risque » |
| `MEDIUM` | « Risque modéré — relecture conseillée » |
| `HIGH` | « Risque élevé — restructuration recommandée » |

Aucun verdict binaire « pass/fail », aucune formulation de « rejet certain ».

---

## 4. Les 9 détecteurs

| # | Code | Niveau | Heuristique |
|---|---|---|---|
| 1 | `READING_ORDER` | MEDIUM | Flux non linéaire : > 2 sauts par page — sauts verticaux inversés (y remonte) **ou** sauts latéraux entre colonnes sur la même ligne (lecture ligne à ligne d'un tableau) |
| 2 | `TEXT_IN_IMAGES` | HIGH | Page porteur d'images avec < 50 % de surface textuelle extractible (ou < 50 caractères) → document scanné/aplati |
| 3 | `NESTED_TABLE` | MEDIUM | Tableau natif DOCX (y compris **imbriqué** dans une cellule) ou grille PDF (≥ 3 lignes alignées sur ≥ 2 colonnes) |
| 4 | `MULTIPLE_COLUMNS` | MEDIUM | > 1 colonne de texte de largeur < 60 % de la page (PDF : regroupement des x) ou colonnes déclarées (DOCX : `w:cols w:num`) |
| 5 | `HEADER_FOOTER` | LOW | En-tête / pied de page répété sur ≥ 2 pages consécutives (même bande, même contenu) ou en-tête/pied déclaré dans la mise en page DOCX |
| 6 | `DECORATIVE_CHARS` | LOW | Glyphes décoratifs et ligatures (`ﬁ`, `ﬂ`, `•`, `◆`, `►`, `★`…) hors ASCII mappables |
| 7 | `UNREADABLE_LINKS` | LOW | URL complète visible dans le texte (au lieu d'un libellé d'ancrage) |
| 8 | `MISSING_SECTION` | HIGH | Mot-clé de section attendu absent du texte extrait (recherche par **frontière de mot** : « information » ne déclenche pas « formation ») |
| 9 | `PARSE_ERROR` | HIGH | PDF chiffré, PDF/DOCX corrompu → `error="PARSE_ERROR"` + `parse_errors[]` |

### Score et label

* `risk_score = min(100, Σ poids)` avec `LOW=5`, `MEDIUM=20`, `HIGH=50`.
* `risk_label` : `HIGH` si score ≥ 60 **ou** présence d'un constat `HIGH` ;
  `MEDIUM` si score ≥ 25 **ou** présence d'un constat `MEDIUM` ; sinon `LOW`.

---

## 5. Exemples de détection (fixtures synthétiques)

Toutes les fixtures ci-dessous sont générées par les tests
(`tests/test_cv_quality_ats.py`) : PDF via **reportlab**, DOCX via **python-docx**,
image PNG construite à la main (zlib + struct, sans Pillow).

### 5.1 PDF une colonne propre → aucun risque

```
run_ats_check_bytes(_clean_pdf(), "pdf")
→ score=0, label=LOW, pages=1, interpretation="Faible risque"
```

### 5.2 PDF deux colonnes → `MULTIPLE_COLUMNS` (MEDIUM)

```
MULTIPLE_COLUMNS  MEDIUM  page=1
  message : Mise en page multi-colonnes détectée (2 colonnes étroites) — ordre de lecture à vérifier
  evidence: colonnes à x≈60, 330
score=20 → "Risque modéré — relecture conseillée"
```

### 5.3 PDF avec tableau → `READING_ORDER` + `NESTED_TABLE` (MEDIUM)

```
READING_ORDER  MEDIUM  page=1
  message : Ordre de lecture potentiellement non linéaire (8 saut(s) latéral/latéraux entre colonnes)
  evidence: Cell 01 / Cell 02 / Cell 11
NESTED_TABLE   MEDIUM  page=1  bbox=(60.0, 640.0, 360.0, 700.0)
  message : Structure tabulaire détectée — les tableaux peuvent casser l'extraction ATS
  evidence: 4 lignes alignées sur 3 colonnes
```

Le tableau est lu ligne par ligne par l'extracteur : c'est exactement le motif qui
fait perdre au CV son ordre de lecture.

### 5.4 PDF image seule → `TEXT_IN_IMAGES` (HIGH)

```
TEXT_IN_IMAGES  HIGH  page=1  bbox=(0.0, 0.0, 595.28, 841.89)
  message : Contenu majoritairement sous forme d'image — le texte risque de ne pas être extrait par l'ATS
  evidence: 1 image(s), 0 caractère(s) extractibles, texte sur 0% de la page
score=50 → "Risque élevé — restructuration recommandée"
```

### 5.5 PDF chiffré → `PARSE_ERROR` (HIGH)

```
PARSE_ERROR  HIGH  page=0  error="PARSE_ERROR"
  message : Fichier protégé par mot de passe — le contenu ne peut pas être analysé par l'ATS
  evidence: PARSE_ERROR: PDF chiffré/protégé par mot de passe — extraction impossible
pages_analyzed=0, parse_errors=["PARSE_ERROR: PDF chiffré/protégé par mot de passe — extraction impossible"]
```

Un PDF corrompu et un DOCX corrompu produisent le même constat (`PARSE_ERROR`, HIGH).

### 5.6 PDF avec en-tête et pied de page répétés → `HEADER_FOOTER` (LOW)

```
HEADER_FOOTER  LOW  page=1
  message : En-tête répété sur les pages 1 et 2 — pollution de l'extraction
  evidence: cv - jean dupont
HEADER_FOOTER  LOW  page=1
  message : Pied de page répété sur les pages 1 et 2 — pollution de l'extraction
  evidence: document confidentiel
```

### 5.7 DOCX propre → aucun risque

```
run_ats_check_bytes(_clean_docx(), "docx")
→ score=0, label=LOW, pages=1
```

### 5.8 DOCX sur 2 colonnes → `MULTIPLE_COLUMNS` (MEDIUM)

```
MULTIPLE_COLUMNS  MEDIUM  page=1
  message : Mise en page sur 2 colonnes — l'ordre de lecture peut être altéré
  evidence: 2 colonnes déclarées dans la mise en page
```

### 5.9 DOCX avec tableau imbriqué → `NESTED_TABLE` (MEDIUM)

```
NESTED_TABLE  MEDIUM  page=1
  message : Tableau imbriqué détecté — structure tabulaire à risque pour l'extraction ATS
  evidence: 2 ligne(s) — tableau imbriqué
```

### 5.10 DOCX avec caractères décoratifs → `DECORATIVE_CHARS` (LOW)

```
DECORATIVE_CHARS  LOW  page=1
  message : Caractères décoratifs ou ligatures détectés (●, fi) — ils peuvent être mal interprétés
  evidence: ● ﬁ
```

### 5.11 DOCX avec URL brute → `UNREADABLE_LINKS` (LOW)

```
UNREADABLE_LINKS  LOW  page=1
  message : 1 URL(s) brute(s) visible(s) dans le texte — un libellé lisible serait préférable
  evidence: https://github.com/jeandupont/projet
```

### 5.12 DOCX sans section Formation → `MISSING_SECTION` (HIGH)

```
MISSING_SECTION  HIGH  page=1
  message : Section attendue introuvable dans le texte extrait : « Formation » — la structure reste invisible pour l'ATS
  evidence: aucun mot-clé parmi : formation, formations, education, etudes, diplomes
```

---

## 6. Tests

```bash
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q tests/test_cv_quality_ats.py
→ 42 passed

/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q
→ 1399 passed      (aucune régression)

/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m ruff check .
→ All checks passed!

git diff --check
→ propre
```

### Répartition des 42 tests

| Famille | Tests |
|---|---|
| PDF 1 colonne propre | 4 |
| PDF 2 colonnes | 2 |
| PDF tableau | 2 |
| PDF image seule | 2 |
| PDF chiffré / corrompu | 2 |
| PDF en-tête / pied de page | 3 |
| DOCX propre | 2 |
| DOCX 2 colonnes | 1 |
| DOCX tableau imbriqué | 1 |
| DOCX corrompu | 1 |
| DOCX décoratif / URL | 4 |
| Sections attendues (défaut, personnalisées, faux positif `information`/`formation`) | 3 |
| Score, label, interprétation | 4 |
| Contrat d'API, déterminisme, hors-ligne, performance | 6 |
| Détecteurs unitaires sur `PageContent` synthétique | 5 |

**Performance mesurée** : PDF de 5 pages analysé en < 3 s (budget de la mission) — le
test `test_performance_under_three_seconds` le vérifie à chaque exécution.

**Hors-ligne vérifié** : `test_analysis_is_local_only` remplace `socket.socket` par une
fonction qui lève une exception pendant l'analyse — le test passe, donc aucun appel
réseau n'est effectué.

---

## 7. Décisions d'implémentation

1. **Positionnement réel du texte (PDF)** — pypdf expose la matrice de texte via le
   hook `visitor_text` : la translation donne la position de chaque fragment. C'est ce
   qui rend possibles les détecteurs `READING_ORDER`, `MULTIPLE_COLUMNS`,
   `NESTED_TABLE` (grille) et `HEADER_FOOTER` (bandes haute/basse) sur un vrai PDF.
2. **Pas de dépendance supplémentaire** — `pdfplumber` n'est pas ajouté (interdit par la
   mission) : la détection de grille repose sur l'alignement des fragments de texte, la
   détection de tableau imbriqué repose sur `python-docx`.
3. **Frontières de mots** — la recherche des sections utilise `(?<![a-z0-9])mot(?![a-z0-9])` ;
   sans cela « Informations » serait interprété comme la section « Formation » (faux
   positif couvert par un test dédié).
4. **Caractères décoratifs restreints** — les guillemets typographiques et tirets demi-cadratins
   (produits par Word à chaque export) ne sont **pas** signalés : ils ne présentent pas de
   risque ATS. Seuls les ligatures et symboles décoratifs le sont.
5. **Absence de section ≠ fichier illisible** — quand l'extraction a échoué (pages vides),
   le détecteur `MISSING_SECTION` n'est pas exécuté : on ne signale pas des sections
   manquantes dans un document qu'on n'a pas pu lire.
6. **Déterminisme** — les caractères décoratifs sont triés par point de code, les
   tableaux et les clusters de colonnes sont parcourus dans un ordre stable :
   `run_ats_check` renvoie deux résultats identiques pour le même fichier
   (test `test_results_are_deterministic`).

---

## 8. Points d'attention pour la relecture

* Le `bbox` n'est renseigné que pour les constats issus de la structure PDF
  (`TEXT_IN_IMAGES`, `NESTED_TABLE` sur grille). Le DOCX n'expose pas les positions
  de paragraphe via `python-docx` : le `bbox` y vaut `None`, ce qui est assumé et
  documenté.
* La position exacte d'une image dans un PDF n'est pas exposée par pypdf : la boîte
  renvoyée est celle de la page. La détection « texte sous forme d'image » s'appuie
  donc sur le ratio de surface textuelle et le nombre de caractères extractibles.
* La surface couverte par le texte est **estimée** (`longueur × taille de police × 0,5`) :
  c'est suffisant pour un ratio, pas pour une mesure exacte.
* Le document est analysé tel qu'il est exporté : le contrôle porte sur le rendu ATS du
  fichier, pas sur la qualité rédactionnelle du CV (c'est le rôle de `cv_quality.structure`).
