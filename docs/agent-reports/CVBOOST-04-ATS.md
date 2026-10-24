# CVBOOST-04 : Rapport du contrôle ATS local (PDF / DOCX)

**Date** : 2026-10-21
**Branche** : `agent/cvboost-04-ats` (travail final : `agent/cvboost-04-ats-final`)
**Base** : `agent/cvboost-04-ats` (Mission 01 — `career/cv_quality/parser.py` + `models.py`)
**Périmètre** : `career/cv_quality/ats.py`, `career/cv_quality/models.py`, `career/cv_quality/parser.py`, `career/cv_quality/__init__.py`, `tests/test_cv_quality_ats.py`

---

## Résumé

Analyse **100 % locale** du fichier exporté (PDF / DOCX / TXT) qui détecte les **risques ATS**
(*Applicant Tracking System*) avant envoi. Aucun appel réseau, aucun LLM, aucune clé.

Le système ne parle **jamais** de « rejet » : il parle de **niveau de risque** et fournit une
**relecture conseillée**, jamais un verdict binaire.

### Résultats des tests
- ✅ **57 tests unitaires** dédiés (`tests/test_cv_quality_ats.py`), fixtures **synthétiques** (PDF générés par reportlab, DOCX par python-docx)
- ✅ **1478 tests** dans la suite globale (≥ 1269 requis) — aucune régression
- ✅ **9 détecteurs** implémentés + score pondéré + label + interprétation
- ✅ **Performance** : ~45 ms pour un PDF de 5 pages (seuil : 3 s)

---

## API publique

```python
from career.cv_quality import (
    run_ats_check,        # analyse un DocumentInput
    run_ats_check_bytes,  # analyse des octets bruts (pdf / docx / txt)
    run_ats_check_file,   # analyse un fichier sur disque
    describe_risk,        # label -> interprétation française
)

result = run_ats_check(document, expected_sections=["Expérience", "Formation"])
result.risk_score          # 0-100 (pondéré, plafonné)
result.risk_label          # "LOW" | "MEDIUM" | "HIGH"
result.risk_interpretation # "Faible risque" | "Risque modéré — relecture conseillée" | "Risque élevé — restructuration recommandée"
result.findings            # liste[ATSFinding]
result.pages_analyzed      # pages réellement inspectées
result.parse_errors        # erreurs d'extraction
```

### Modèles ajoutés (`career/cv_quality/models.py`)

| Modèle | Rôle |
|---|---|
| `ATSRiskLevel` | `Literal["LOW", "MEDIUM", "HIGH"]` |
| `ATSFinding` | `code`, `risk_level`, `message`, `page`, `bbox`, `evidence_excerpt`, `error` |
| `ATSCheckResult` | `findings`, `risk_score`, `risk_label`, `pages_analyzed`, `parse_errors`, `risk_interpretation` |
| `DocumentInput.raw_bytes` | Octets du fichier exporté (ajoutés par le parseur) |

`DocumentInput.raw_bytes` permet à `run_ats_check(document)` d'inspecter **la structure réelle**
du PDF/DOCX (positions des glyphes, images, tableaux, colonnes) et non le texte aplati.
Le champ est optionnel : sans octets, les détecteurs travaillent sur le texte seul.

---

## Les 9 détecteurs

| Code | Niveau | Heuristique implémentée | Source |
|---|---|---|---|
| `READING_ORDER` | MEDIUM | > 2 retours en arrière de l'axe `y` sur une page (flux non linéaire : encadrés, colonnes entrelacées). Repli texte : lignes séparées par 3+ espaces ou tabulations | positions PDF (visitor `pypdf`) |
| `TEXT_IN_IMAGES` | HIGH | Page avec `/XObject` image **et** < 50 caractères extractibles (ou 0 caractère) → contenu probablement invisible pour l'ATS. **Plus** : image dominante (≥ 25 % de la page) sans texte adjacent → contenu incorporé dans l'image (OCR requis). La position réelle des images est lue dans le flux de contenu PDF (`cm` / `Do`) | XObjects PDF / `inline_shapes` DOCX |
| `NESTED_TABLE` | MEDIUM | Tableaux DOCX (y compris **imbriqués** dans une cellule) et grilles alignées PDF (≥ 2 lignes à ≥ 3 cellules alignées) | structure DOCX / positions PDF |
| `MULTIPLE_COLUMNS` | MEDIUM | **Gouttière verticale** sans texte (≥ 40 pt) traversée par ≤ 50 % des lignes et séparant deux blocs couvrant chacun ≥ 30 % de la hauteur de texte ; colonnes déclarées `w:cols` en DOCX. Repli texte : plusieurs lignes séparant deux champs **au même offset** | positions PDF / `sectPr` DOCX |
| `HEADER_FOOTER` | LOW | Texte répété en haut (y ≥ 90 % hauteur) ou en bas (y ≤ 10 %) d'au moins **2 pages consécutives**, même contenu et même position | positions PDF / repli texte |
| `DECORATIVE_CHARS` | LOW | Ligatures (ﬁ ﬂ ﬀ ﬃ ﬄ) et glyphes décoratifs (• ● ◆ ► ▪ → …). Les accents français et les guillemets typographiques ne sont **jamais** signalés | texte extrait |
| `UNREADABLE_LINKS` | LOW | URL complète visible dans le texte (`http(s)://`, `www.`, domaine nu) au lieu d'un libellé d'ancre. Les adresses e-mail sont exclues | texte extrait |
| `MISSING_SECTION` | HIGH | Titre de section attendu absent du texte. Par défaut : Expérience / Formation / Compétences, surchargeable via `expected_sections`. Recherche sur le **début de ligne** (donc un titre), avec synonymes FR/EN | texte extrait |
| `PARSE_ERROR` | HIGH | PDF chiffré, DOCX corrompu, type non pris en charge → `error="PARSE_ERROR"`, `pages_analyzed=0`, aucun autre détecteur ne s'exécute | extraction |

### Score et libellé

| Niveau | Poids |
|---|---|
| LOW | 5 |
| MEDIUM | 20 |
| HIGH | 50 |

Score = somme des poids, **plafonné à 100**.

| Score | Label | Interprétation |
|---|---|---|
| 0 – 19 | `LOW` | Faible risque |
| 20 – 49 | `MEDIUM` | Risque modéré — relecture conseillée |
| 50 – 100 | `HIGH` | Risque élevé — restructuration recommandée |

---

## Exemples de détection (fixtures synthétiques)

### PDF 1 colonne propre
```
score=0 label=LOW (Faible risque) pages=1
  (aucun risque détecté)
```

### PDF 2 colonnes
```
[MEDIUM] MULTIPLE_COLUMNS p.1 bbox=None error=None
    Mise en page multi-colonnes détectée (2 colonnes de texte) — l'ordre de lecture peut être altéré à l'extraction
    evidence: 'Gouttière(s) verticale(s) à x≈262pt (largeur de page 595pt)'
[HIGH] MISSING_SECTION p.1 bbox=None error=None
    Section attendue introuvable : « Compétences » — la structure reste invisible pour un ATS
```

### PDF avec tableau
```
[MEDIUM] NESTED_TABLE p.1 bbox=None error=None
    Grille alignée détectée (structure tabulaire) — l'extraction linéaire peut être perturbée
    evidence: '3 lignes à au moins 3 cellules alignées'
```

### PDF image-only (page scannée)
```
[HIGH] TEXT_IN_IMAGES p.1 bbox=(0.0, 0.0, 595.28, 841.89) error=None
    Page sans texte extractible alors qu'elle contient des images — le contenu reste probablement invisible pour un ATS
    evidence: '1 image(s) sur la page, 0 caractère extrait'
```

### PDF protégé par mot de passe
```
[HIGH] PARSE_ERROR p.1 bbox=None error=PARSE_ERROR
    Fichier protégé par mot de passe — l'extraction ATS est impossible
    evidence: 'PDF chiffré/protégé par mot de passe — extraction impossible'
```

### DOCX avec tableau imbriqué
```
[MEDIUM] NESTED_TABLE p.1 bbox=None error=None
    Tableau imbriqué détecté — l'extraction linéaire peut perdre des cellules
    evidence: 'Tableau 2 lignes × 2 colonnes (docx)'
```

### DOCX en 2 colonnes
```
[MEDIUM] MULTIPLE_COLUMNS p.1 bbox=None error=None
    Mise en page en 2 colonnes détectée — l'ordre de lecture peut être altéré à l'extraction
    evidence: '2 colonnes déclarées dans la mise en page'
```

### DOCX corrompu
```
[HIGH] PARSE_ERROR p.1 bbox=None error=PARSE_ERROR
    Fichier corrompu ou malformé — l'extraction ATS est impossible
    evidence: 'DOCX corrompu ou malformé : File is not a zip file'
```

### PDF avec en-tête / pied de page répétés
```
[LOW] HEADER_FOOTER p.1 bbox=None error=None
    En-tête répété sur les pages 1 et 2 — pollue l'extraction du CV
    evidence: 'confidentiel - cv jean dupont'
[LOW] HEADER_FOOTER p.1 bbox=None error=None
    Pied de page répété sur les pages 1 et 2 — pollue l'extraction du CV
    evidence: 'page sur 2 - jean dupont'
```

---

## Choix de conception notables

### 1. Un titre centré n'est pas une colonne
La détection de colonnes repose sur une **gouttière verticale** (bande sans texte) et non sur un
simple écart de `x`. Un titre centré, une photo ou une ligne très large ne créent donc **aucun
faux positif** : le CV réaliste (titre centré + photo + puces) ressort à **0 risque**.

Repli possible : lignes traversant la gouttière (≤ 50 %) et blocs de part et d'autre couvrant
chacun ≥ 30 % de la hauteur de texte.

### 2. Une photo n'est pas un risque « texte dans image »
La position réelle des images est lue dans le flux de contenu du PDF (`cm` puis `Do` : une image
peint le carré unité, sa boîte est donc la matrice courante). Le risque n'est signalé que si :

- la page contient des images **et** moins de 50 caractères extractibles (page scannée) ;
- ou si une image **dominante** (≥ 25 % de la page) ne porte **aucun texte adjacent** — le
  contenu est alors incorporé dans l'image (OCR requis).

Une photo de portrait à côté d'un vrai texte ne produit donc aucun signal, et un CV aplati en
image est bien détecté.

### 3. Les accents ne sont jamais des « caractères décoratifs »
Seules les ligatures et les glyphes décoratifs explicitement listés sont signalés : `é`, `à`,
`—`, `«`… sont parfaitement lisibles pour un ATS.

### 4. Un fichier illisible ne lève jamais d'exception
`run_ats_check_bytes` / `run_ats_check_file` capturent les erreurs du parseur et les transforment
en finding `PARSE_ERROR` (HIGH) : l'application ne casse pas sur un PDF chiffré.

### 5. Vocabulaire prudent
Les messages parlent de « risque », « relecture conseillée », « restructuration recommandée ».
Un test vérifie qu'aucun message ne contient « rejet » ni « refus ».

---

## Tests (`tests/test_cv_quality_ats.py` — 57 tests)

| Famille | Couverture |
|---|---|
| Détecteur 1 | flux non linéaire (PDF), flux linéaire (silence) |
| Détecteur 2 | PDF image-only, DOCX avec image, photo + texte (silence) |
| Détecteur 3 | grille PDF, tableau DOCX imbriqué, CV simple (silence) |
| Détecteur 4 | PDF 2 colonnes, DOCX `w:cols`, CV simple (silence) |
| Détecteur 5 | en-tête/pied répétés, page unique (silence) |
| Détecteur 6 | ligatures, texte simple (silence), accents (silence) |
| Détecteur 7 | URL brutes, e-mail (silence) |
| Détecteur 8 | sections absentes, sections présentes, `expected_sections` sur mesure |
| Détecteur 9 | PDF chiffré, DOCX corrompu, PDF corrompu, type non pris en charge |
| Score / label | pondération, plafond à 100, 7 seuils de label, interprétation fournie |
| Contrat de sortie | champs obligatoires de chaque finding, `page ≥ 1`, excerpt ≤ 120 caractères |
| Vocabulaire | aucun message n'affirme un rejet |
| API | déterminisme (2 exécutions identiques), `run_ats_check_file`, octets bruts utilisés |
| Offline | `socket` et `create_connection` neutrés pendant l'analyse → aucun appel réseau |
| Performance | PDF de 5 pages analysé en < 3 s |
| Non-régression | CV réaliste (titre centré + photo) → 0 risque |

Fixtures : **100 % synthétiques**, générées à l'exécution (reportlab / python-docx / PIL).
Aucune donnée personnelle, aucun fichier externe.

---

## Validation

```bash
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q tests/test_cv_quality_ats.py
# 57 passed

/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q
# 1478 passed

/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m ruff check .
# All checks passed!

git diff --check   # propre
```

---

## Limites assumées

- **Positions PDF** : les coordonnées proviennent de `visitor_text` (`pypdf`), elles sont
  **approximatives** (matrice texte, sans rotation ni transformation complexe). Le `bbox`
  retourné est donc indicatif — c'est le `evidence_excerpt` qui fait foi.
- **Pages DOCX** : le format DOCX n'a pas de frontière de page ; les pages sont estimées
  (~3000 caractères/page) et les tableaux/images sont rattachés à la première page.
- **Ordre de lecture** : l'heuristique compte les sauts de l'axe `y` dans l'ordre du flux de
  contenu ; un PDF dont le flux est déjà normalisé (colonnes remises dans l'ordre) ne sera pas
  signalé — c'est le comportement attendu.
- **`pdfplumber` n'est pas utilisé** (interdit par le périmètre de la mission) : la détection de
  grilles repose sur l'alignement des glyphes, ce qui suffit pour les CV.
- Le contrôle ATS n'est **pas branché** sur `career/service.py` / `career/router.py` /
  `career_static/*` (interdits par le périmètre) : l'intégration API se fera dans une mission
  dédiée.

---

## Fichiers livrés

| Fichier | Nature |
|---|---|
| `career/cv_quality/ats.py` | **nouveau** — 9 détecteurs + scoring + API |
| `career/cv_quality/models.py` | **étendu** — `ATSFinding`, `ATSCheckResult`, `ATSRiskLevel`, `DocumentInput.raw_bytes` |
| `career/cv_quality/parser.py` | **étendu** — attache les octets du fichier à `DocumentInput` |
| `career/cv_quality/__init__.py` | **étendu** — exports `run_ats_check`, `run_ats_check_bytes`, `run_ats_check_file`, `describe_risk` |
| `tests/test_cv_quality_ats.py` | **nouveau** — 57 tests synthétiques |
| `docs/agent-reports/CVBOOST-04-ATS.md` | **nouveau** — ce rapport |

---

## Note d'historique — exécution en parallèle

La Mission 04 a été lancée **trois fois en parallèle** par l'orchestrateur (trois workers sur
la même mission, worktrees distincts). Trois implémentations ont donc coexisté :

| Commit | Contenu |
|---|---|
| `0e633a1` | première version (branche `agent/cvboost-04-ats-v2`) |
| `6e0e3bb` | deuxième version (analyse positionnelle) |
| `8fd5e98` | commit de consolidation des deux versions |
| `4e328f9` | régression de la consolidation corrigée (colonnes, tableaux, photo) |
| `b9297c6` | position réelle des images PDF + seuils calibrés + repli colonnes texte |

La consolidation `8fd5e98` a **introduit des régressions** (vérifié sur 14 fixtures
synthétiques) :

| Fixture | Consolidation `8fd5e98` | Cette implémentation |
|---|---|---|
| PDF 2 colonnes | `NESTED_TABLE` (mauvais détecteur) | `MULTIPLE_COLUMNS` ✓ |
| PDF avec tableau | `READING_ORDER` + `NESTED_TABLE` | `NESTED_TABLE` seul ✓ |
| PDF réaliste (titre centré + photo) | `TEXT_IN_IMAGES` → **faux positif** | aucun risque ✓ |
| DOCX 2 colonnes | `MULTIPLE_COLUMNS` ✓ | `MULTIPLE_COLUMNS` ✓ |
| TXT avec URL brute | `UNREADABLE_LINKS` ✓ | `UNREADABLE_LINKS` ✓ |

Les gains de cette implémentation (non couverts par la consolidation) :

- **colonnes DOCX** : la lecture de `w:cols` cherchait le **premier** élément `w:cols` de la
  section — or le gabarit Word en contient déjà un par défaut. La version livrée parcourt
  **tous** les éléments (`findall`) et retient le plus grand nombre de colonnes ;
- **détection des colonnes PDF** : gouttière verticale réelle (bande sans texte) au lieu d'un
  simple écart de `x`, ce qui supprime les faux positifs sur les titres centrés et les photos ;
- **URL brutes** : une seule URL visible est déjà signalée (les adresses e-mail sont exclues) ;
- **sections manquantes** : le détecteur n'est pas exécuté quand aucune page n'a de texte
  extractible (le risque « texte dans image » couvre déjà ce cas).

Les commits des autres workers (`0e633a1`, `6e0e3bb`, `8fd5e98`) sont conservés dans
l'historique de la branche.

### Correctifs appliqués par-dessus la consolidation (`b9297c6`)

Deux faux positifs subsistaient, tous deux vérifiés sur fixtures synthétiques :

| Cas | Avant | Après |
|---|---|---|
| CV avec une simple photo + un vrai texte | `TEXT_IN_IMAGES` HIGH → **faux positif** (50/100) | aucun risque ✓ |
| CV en une colonne, bloc de coordonnées | `MULTIPLE_COLUMNS` MEDIUM → **faux positif** | aucun risque ✓ |
| CV aplati en image | non détecté | `TEXT_IN_IMAGES` HIGH ✓ |

Les causes et les correctifs :

1. **Position des images** : la position n'était pas lue, chaque image était assimilée à la
   page entière. Le flux de contenu est maintenant parcouru (`cm` / `Do`) pour obtenir la boîte
   réelle de chaque image ; le seuil « texte minimal » est ramené de 200 à 50 caractères.
2. **Repli texte des colonnes** : il reposait sur des paires de lignes courtes consécutives, ce
   qui signalait le bloc nom / e-mail / téléphone d'un CV propre. Il repose désormais sur un
   séparateur de colonnes **commun à plusieurs lignes**, signature textuelle d'un vrai
   alignement en colonnes.
3. **Règle de géométrie manquante** : une image dominante (≥ 25 % de la page) sans texte
   adjacent signale un CV aplati dont le contenu est incorporé dans l'image (OCR requis).
4. **CTM** : la matrice de transformation courante est appliquée aux positions des glyphes.
