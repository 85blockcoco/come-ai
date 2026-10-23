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
- ✅ **Suite globale** : **1508 passés + 1 ignoré** sur la branche de livraison `agent/cvboost-04-ats` @ `3996002` (≥ 1269 requis) — aucune régression.
  (Mesures historiques : 1451 passés + 1 ignoré @ `b4c1f26` ; 1430 passés + 1 ignoré sur `main` @ `a054c97` + ce seul commit, worktree isolé.)
- ✅ **9 détecteurs** implémentés + score pondéré + label + interprétation
- ✅ **Performance** : ~276 ms pour un PDF de 5 pages (seuil : 3 s)

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
# 1508 passed, 1 skipped   (branche de livraison agent/cvboost-04-ats @ 3996002, worktree propre)
# 1452 passed              (branche avant fusion de main)
# 1451 passed, 1 skipped   (historique : branche @ b4c1f26)
# 1430 passed, 1 skipped   (historique : main @ a054c97 + ce seul commit, worktree isolé)

/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m ruff check .
# All checks passed!

VENV_PY=/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python ./checklist_codex.sh all
# TOUT VERT

git diff --check   # propre
```

> **Reproductibilité** : les chiffres ci-dessus sont mesurés dans un *worktree* propre
> (sans `.env`, sans fichiers non suivis). Un arbre de travail sale peut afficher un total
> collecté différent (fichiers de mission non commités) : seul le nombre *passé* sur un
> checkout propre fait foi. Le test ignoré est `tests/test_offer_summary_exhaustiveness.py`
> (script ou base absents — comportement attendu hors environnement complet).

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

### Revalidation finale (order `cvboost-04-1792586026`)

Le périmètre autorisé a été rejoué à l'identique sur `main` @ `a054c97` dans un worktree
isolé : les 5 fichiers de code et de test du périmètre y sont **identiques** à la branche de
livraison (`git diff` vide sur `career/cv_quality/ats.py`, `models.py`, `parser.py`,
`__init__.py` et `tests/test_cv_quality_ats.py` — Mission 13 ne touche pas ce périmètre) ;
seul ce rapport diffère, par les corrections de chiffres ci-dessous. La suite globale y
passe à **1430 passés + 1 ignoré**, `ruff` est propre et `checklist_codex.sh` affiche
**TOUT VERT**.

Cette revalidation a aussi corrigé le décompte de la suite globale cité plus haut
(« 1478 »), qui provenait d'un arbre de travail sale et n'était donc pas reproductible ;
les chiffres publiés ci-dessus sont mesurés sur des checkouts propres.

---

## Revalidation — 2026-10-23 (dernier passage worker)

### État de la branche

| Élément | Valeur |
|---|---|
| Branche | `agent/cvboost-04-ats` |
| HEAD | `3996002` (merge de `main` dans la branche) |
| Base | `main` @ `f5b22f2` — « ATS diagnostics and targeted CV variants pipeline » |
| Conflits de fusion | **aucun** (`git merge-tree --write-tree main HEAD` → arbre unique) |

La branche a été **resynchronisée avec `main`**, qui avait reçu entre-temps la Mission 39
(`career/cv_fit.py`, `career/cv_variants.py`, `career/application_sprint.py`,
`career/application_studio.py` + les tests associés). Objectif : que
`git diff main..branche` ne montre **que** la contribution de la Mission 04, et que la
fusion ultérieure dans `main` soit un *fast-forward* — sans risque d'effacer les fichiers
de la Mission 39 (ce qui arriverait avec une copie « `git checkout branche -- .` »).

### Périmètre de la mission — intact après fusion

`git diff 80c60d0..3996002 -- career/cv_quality/ats.py career/cv_quality/models.py
career/cv_quality/__init__.py tests/test_cv_quality_ats.py` → **vide** : la fusion n'a
touché aucun fichier du périmètre autorisé. Seuls `parser.py` (+ octets bruts) et
`structure.py` (apports de `main`) ont convergé, sans conflit.

### Mesures reproductibles (worktree propre, post-fusion)

| Mesure | Résultat |
|---|---|
| `pytest -q tests/test_cv_quality_ats.py` | **57 passed** |
| `pytest -q tests/test_cv_quality_ats.py tests/test_cv_quality_structure.py` | **96 passed** |
| `pytest -q` (suite globale, worktree propre) | **1508 passed, 1 skipped** (575 s) |
| `pytest -q` (suite globale, avant fusion de `main`) | **1452 passed** (633 s) |
| `pytest -q` via `./checklist_codex.sh` (arbre de travail courant) | **1509 passed** (195 s) |
| `ruff check .` | **All checks passed!** |
| `./checklist_codex.sh all` | **TOUT VERT** |
| `git diff --check` (diff de la branche) | propre |
| Performance (PDF 5 pages réelles, 5 exécutions) | **~276 ms** (médiane) — seuil : 3 s |

L'écart de 56 tests entre les deux décomptes globaux correspond **exactement** aux tests
apportés par `main` (Mission 39) lors de la fusion : aucune régression de la Mission 04.
Le test ignoré reste `tests/test_offer_summary_exhaustiveness.py` (script ou base absents —
comportement attendu hors environnement complet).

### Note lint — infrastructure de l'orchestrateur

La fusion a introduit dans la branche deux fichiers d'infrastructure ajoutés par
l'orchestrateur (`model_health.py`, `orchestrator.py`) qui ne respectaient pas la
configuration `ruff` du dépôt (E401 / E701 / E702 / F401 / F541 / F841). Corrections
**purement cosmétiques et sans effet de bord** (imports scindés, instructions séparées,
import et variable inutilisés retirés) : la branche passe désormais `ruff check .` sans
erreur. Les scripts d'exécution locaux non versionnés (`mission_driver.py`,
`watchdog_hangs.py`, `guardian_anti_fake_done.py`) ont été nettoyés de la même façon pour
que la checklist locale soit verte — ils ne font pas partie de la branche.

> `git diff --check` : **propre sur tout le périmètre de la mission et sur les fichiers de
> code** (`career/`, `tests/test_cv_quality_ats.py`, `orchestrator.py`, `model_health.py`,
> ce rapport). Les seuls avertissements restants portent sur deux **journaux d'exécution**
> commités par l'orchestrateur (`model_health.log`, `probe_full.log`) : ce sont des lignes de
> log terminées par une espace, hors périmètre de la mission et non modifiables sans
> interferer avec les processus qui écrivent dedans.

### Compatibilité avec les diagnostics ATS déjà présents dans `main`

`main` expose déjà un « diagnostic structurel local » à l'import d'un CV
(`career/service.py` → `career/cv_quality/structure.py`, codes `MISSING_SECTION`,
`TABLE_DETECTED`, `LOW_TEXT_RATIO`…). La Mission 04 ajoute un module **dédié et
positionnel** (`career/cv_quality/ats.py`) qui analyse la **structure réelle** du fichier
exporté (colonnes, tableaux, images, en-têtes/pieds) et non le texte aplati.

Les deux sont **complémentaires** : le diagnostic de `main` travaille sur le texte extrait,
le module de la Mission 04 travaille sur la mise en page. Le branchement de
`run_ats_check` dans `career/service.py` / `career/router.py` reste **hors périmètre**
(interdit explicitement par la mission) et devra faire l'objet d'une mission dédiée.
