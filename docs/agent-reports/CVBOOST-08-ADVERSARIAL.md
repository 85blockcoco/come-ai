# CVBOOST-08 — Banc adversarial de matching CV/offre (130 cas)

Mission **CVBOOST-08** : fiabiliser le matching CV/offre contre les faux
positifs lexicaux, avec un banc de cas synthétiques reproductible et un
moteur de décision qui ne cite **jamais** une preuve absente du CV.

| | |
|---|---|
| Branche | `agent/cvboost-08-adversarial` (base `main` — `a054c97`) |
| Livrable 1 — moteur de référence | `career/cv_quality/matching.py` + `tests/test_cv_matching_adversarial.py` (130 couples, 1 181 tests) + ce rapport |
| Livrable 2 — banc produit | `career/matching_bench/` (118 couples qui appellent le code applicatif réel) + son rapport [`CVBOOST-08.md`](CVBOOST-08.md) |
| Validation | 1 181 tests du banc adversarial verts · suite complète verte · ruff clean · `git diff --check` propre |

> Les deux livrables se complètent : le **moteur** ci-dessous est *juste* (il
> refuse les faux positifs lexicaux), le **banc produit** est *honnête* (il
> mesure l'écart entre le comportement applicatif réel et la vérité terrain
> des 118 couples). Le livrable a été **rebasé sur `main` courant** (`a054c97`)
> : la branche contient exactement `main` + les fichiers de la mission, sans
> aucun retour en arrière sur les révisions UX récentes.

---

## 1. Ce qui est livré

```python
from career.cv_quality import DocumentInput, analyze_cv, match_cv_to_offer

analysis = analyze_cv(DocumentInput(text=cv_text, filename="cv.txt", filetype="txt"))
result = match_cv_to_offer(analysis, offer)   # -> MatchResult
```

`match_cv_to_offer(cv_result, offer)` est **pure, déterministe et hors ligne** :

* pas de réseau, pas de modèle, pas d'horloge, pas d'aléatoire, pas d'accès
  disque ;
* les exigences sont lues par le **contrat CVBOOST-02**
  (`career.offer_requirements.extract.analyze_offer`), jamais par un
  découpage maison ;
* chaque action cite une **sous-chaîne exacte** du CV, avec son offset ;
* une exigence sans preuve rend `DO_NOT_ADD` — ce qui est absent du CV n'est
  jamais ajouté ;
* une exigence **niée** dans l'offre n'est pas une exigence : elle sort du
  dénominateur et produit un avertissement ;
* une exigence que le contrat n'a **pas extraite** est signalée : elle ne peut
  pas être couverte, et le moteur le dit au lieu de laisser croire que tout
  est traité.

### Codes d'action

| Code | Signification |
|---|---|
| `HIGHLIGHT` | Preuve verbatim trouvée : la compétence est dans le CV. |
| `REPHRASE` | Preuve partielle ou de la même famille : reformuler avec la **preuve du CV**, pas avec le vocabulaire de l'offre. |
| `DO_NOT_ADD` | Aucune preuve : *« Aucune preuve dans le CV, ne pas ajouter sans preuve »*. |
| `QUANTIFY` | La preuve doit être chiffrée, ou contient déjà un chiffre à expliciter. |
| `CONFIRM_LANGUAGE` | La langue est présente, le niveau exigé ne l'est pas : à confirmer. |

### Contrat de sortie

```python
MatchAction(code, requirement_text, cv_evidence_text, cv_evidence_offset, reason, confidence, evidence)
MatchResult(overall_score, matched_requirements, total_requirements,
            actions, missing_critical, warnings)
```

* `requirement_text` : extrait **exact** de l'offre ;
* `cv_evidence_text` / `cv_evidence_offset` : extrait **exact** du CV
  (`cv_text[offset:offset+len(evidence)] == evidence`, invariant testé) ;
* `missing_critical` : exigences obligatoires (`modality == "required"`) sans
  preuve ;
* `overall_score` : couverture documentaire pondérée par modalité
  (obligatoire 1.0, souhaitable 0.5, contextuel 0.3) — **pas** une probabilité
  d'embauche ;
* `reason` : toute action `DO_NOT_ADD` porte la phrase canonique
  « Aucune preuve dans le CV, ne pas ajouter sans preuve », suivie de la
  cause précise (« … : type de contrat incompatible (CV « cdi », offre
  « cdd ») »). La cause s'ajoute, elle ne remplace jamais la règle.

---

## 2. Le banc : 130 couples synthétiques, 10 familles

`tests/test_cv_matching_adversarial.py` — 130 couples (CV, offre) 100 %
synthétiques, 1 181 tests (chaque cas est passé au crible par 7 invariants).

Chaque cas est un **dictionnaire** qui porte la vérité terrain écrite à la
main, exactement dans le format du prompt de mission :

```python
{
    "id": "ADV-001",
    "name": "Excel vs analyse financière",
    "family": "faux_positif_lexical",
    "cv_text": CV_EXCEL,
    "offer_requirements": ["Excel avance", "Analyse financiere"],
    "expected_actions": [
        {"code": "HIGHLIGHT", "requirement": "Excel avance", "cv_evidence": "Excel avance"},
        {"code": "DO_NOT_ADD", "requirement": "Analyse financiere", "cv_evidence": None},
    ],
    "expected_score_range": (0.5, 0.5),
    "expected_warnings": [],
}
```

| Famille | Cas | Le piège que la famille mesure |
|---|---|---|
| `faux_positif_lexical` | 21 | Excel ≠ analyse financière, Java ≠ JavaScript, PostgreSQL ≠ MySQL, Power BI ≠ Tableau, PowerPoint ≠ Power BI, « tableaux de bord » ≠ l'outil Tableau, Node.js = JavaScript. |
| `langue` | 15 | « Anglais courant » déclaré, niveau absent, programme enseigné en anglais, niveau insuffisant, profil trilingue. |
| `contrat` | 13 | Stage ≠ CDI, CDI ≠ CDD, alternance déclarée ou exclue, VIE, freelance, contrat non déclaré. |
| `diplome` | 14 | M1 / M2 / Bachelor / doctorat / Bac+3 / Bac+5 : le niveau se compare au niveau, pas au mot. |
| `homonyme` | 12 | Audit financier ≠ audit IT, gestion de projet ≠ gestion d'équipe, data analysis ≠ data engineering. |
| `multilingue` | 13 | Profils FR/EN/ES/DE, offre EN, CV anglophone sur offre FR, langues jamais déclarées. |
| `acronyme` | 10 | M&A, Private Equity, Investment Banking, CRM, ERP, KPI. |
| `negation` | 10 | « Pas de gestion d'équipe », « aucune expérience », « sans déplacement », « not required ». |
| `absente` | 11 | Compétence 100 % absente → `DO_NOT_ADD`, jamais d'ajout ; exigence non extraite par le contrat. |
| `quantification` | 11 | Équipe de 10 personnes, budget de 500 k€, chiffres absents, « expérience management ». |

Toutes les exigences du prompt sont couvertes : Excel/analyse financière,
Java/JavaScript, langue déclarée vs programme enseigné, stage vs CDI,
alternance exclue, M1/M2/Bachelor, mot nié, compétence présente dans l'offre
seulement, acronymes (M&A, PE, IB), homonymes sectoriels (audit financier vs
audit IT), profil multilingue.

---

## 3. Matrice de confusion (mesurée)

Mesure faite sur les **133 exigences** dont la vérité terrain est écrite à la
main dans le banc (couverture : l'exigence est-elle prouvée par le CV ?).
La mesure est **rejouée par un test** (`test_matrice_de_confusion_sans_faux_positif`),
pas seulement par un script hors dépôt.

| | CV prouve | CV ne prouve pas |
|---|---|---|
| **Vérité : l'exigence est prouvable** | 61 (TP) | 0 (FN) |
| **Vérité : l'exigence n'est pas prouvable** | 0 (FP) | 72 (TN) |

* **Précision = 1.0000**, **rappel = 1.0000**
* **Faux positifs = 0** — aucun cas où le moteur invente une preuve ;
* **Faux négatifs = 0** — aucun cas où une preuve présente est refusée ;
* 11 exigences niées sont hors dénominateur (une exigence niée n'est pas une
  exigence).

Matrice par code d'action (133 exigences évaluées) :

| Famille | HIGHLIGHT | REPHRASE | DO_NOT_ADD | QUANTIFY | CONFIRM_LANGUAGE | Total |
|---|---|---|---|---|---|---|
| faux_positif_lexical | 10 | 0 | 11 | 1 | 0 | 22 |
| acronyme | 5 | 0 | 5 | 0 | 0 | 10 |
| langue | 8 | 0 | 7 | 0 | 1 | 16 |
| contrat | 3 | 0 | 10 | 0 | 0 | 13 |
| diplome | 8 | 0 | 6 | 0 | 0 | 14 |
| negation | 3 | 0 | 1 | 0 | 0 | 4 |
| absente | 1 | 0 | 11 | 0 | 0 | 12 |
| homonyme | 4 | 0 | 8 | 0 | 0 | 12 |
| quantification | 4 | 1 | 3 | 3 | 0 | 11 |
| multilingue | 9 | 0 | 10 | 0 | 0 | 19 |
| **Total** | **55** | **1** | **72** | **4** | **1** | **133** |

Lecture : **72 exigences sur 133 ne sont pas prouvées** par le CV. C'est le
cœur du lot — un banc qui ne trouve que des positives ne mesure rien.

### Les sept invariants vérifiés sur *chaque* cas

1. `cas_adversarial` — le code d'action et la preuve attendue sont exactement
   ceux de la vérité terrain ;
2. `score_dans_la_plage_attendue` — le score tombe dans la plage déduite de la
   vérité terrain du cas ;
3. `avertissements_attendus` — les avertissements attendus sont émis, **et un
   cas propre n'en émet aucun** (pas d'avertissement fantôme) ;
4. `preuve_toujours_verbatim` — toute preuve est une sous-chaîne exacte du CV
   et l'offset annoncé redonne exactement cette sous-chaîne ;
5. `absent_jamais_ajoute` — `DO_NOT_ADD` ⟹ aucune preuve, et inversement ;
6. `determinisme` — deux exécutions rendent le même `MatchResult` ;
7. `aucune_donnee_de_contact` — ni e-mail, ni téléphone, ni LinkedIn dans la
   surface de décision.

S'y ajoutent deux invariants de banc : `banc_comporte_plus_de_100_cas`,
`chaque_cas_suit_le_format_du_prompt`, `familles_couvertes` et
`matrice_de_confusion_sans_faux_positif` (0 faux positif, 0 faux négatif).

---

## 4. Comment chaque piège est traité

| Piège | Traitement | Cas |
|---|---|---|
| Excel ≠ analyse financière | Concepts distincts : `excel` n'est pas dans la famille `finance`. | ADV-001, ADV-004 |
| Modélisation ≠ analyse financière | Même famille ⇒ `REPHRASE` (reformuler avec la preuve), jamais `HIGHLIGHT`. | ADV-003 |
| Java ≠ JavaScript | Correspondance par **mot entier** : `java` ne prouve jamais `javascript`. | ADV-005, ADV-006 |
| PostgreSQL ≠ MySQL | Idem : les deux sont des mots entiers distincts. | ADV-121 |
| Node.js = JavaScript | La forme écrite est reconnue comme la même surface. | ADV-122 |
| PowerPoint ≠ Power BI | `powerpoint` n'est pas `power` + `bi`. | ADV-123 |
| Un programme enseigné en anglais ≠ un niveau d'anglais | Contexte d'enseignement détecté (même ligne) ⇒ aucune preuve de niveau. | ADV-032, ADV-038 |
| Stage ≠ CDI | Le contrat déclaré par le CV est comparé à celui de l'offre. | ADV-043, ADV-047 |
| CDI ≠ CDD | Même règle, deux contrats fixes distincts. | ADV-124 |
| Alternance exclue | Le CV déclare « CDI » **et** exclut « alternance » : les deux sont tenus séparés. | ADV-045 |
| M1 ≠ M2 ≠ Bachelor ≠ Bac+3 ≠ Bac+5 | Niveaux ordonnés, comparaison par rang ; le niveau générique « master » n'écrase pas « master 1 ». | ADV-055 à ADV-066, ADV-125, ADV-126 |
| Mot nié | Une exigence niée **n'est pas une exigence** : elle sort du dénominateur et produit un avertissement. | ADV-067 à ADV-076 |
| Compétence absente | `DO_NOT_ADD` avec la raison canonique. | ADV-077 à ADV-086 |
| Exigence non extraite par le contrat | Avertissement explicite : une exigence que le contrat a ignorée ne peut pas être couverte. | ADV-128 |
| Acronymes | M&A ↔ fusions-acquisitions, PE ↔ private equity, majuscules strictes pour les acronymes courts (`PE`, `IB`, `R`). | ADV-019 à ADV-022 |
| Homonymes sectoriels | Groupes d'homonymes : audit financier ≠ audit IT, data analysis ≠ data engineering, gestion de projet ≠ gestion d'équipe. | ADV-087 à ADV-098 |
| Multilingue | La preuve est cherchée par langue **et** par niveau, sur la ligne qui déclare la langue ; un CV anglophone prouve une offre française. | ADV-109 à ADV-115, ADV-129 |
| Quantification | Preuve chiffrée ⇒ `QUANTIFY` ; exigence d'échelle sans chiffre ⇒ `QUANTIFY`. | ADV-099 à ADV-108, ADV-127 |

Trois pièges supplémentaires que le lot traite :

* **« EXPERIENCE », « LANGUES »… ne prouvent rien** : les en-têtes de section
  du CV sont exclus du corpus de preuve (ADV-076).
* **« tableaux de bord » ≠ l'outil Tableau** : une preuve peut être annulée
  par la phrase qui la suit (ADV-014, ADV-098).
* **Deux occurrences ne se prouvent pas l'une l'autre** : la preuve est
  locale (une ligne, une clause) — « commercial » dans un intitulé de poste
  et « reporting » dans une ligne de mission ne prouvent pas « reporting
  commercial » (ADV-107).

---

## 5. Modifications apportées au code existant

Le lot **n'ajoute** que ce qui lui est nécessaire, et le signale :

| Fichier | Modification | Pourquoi |
|---|---|---|
| `career/cv_quality/models.py` | Ajout de `MatchAction`, `MatchResult`, `MatchEvidence`, `MatchActionCode` et d'un champ `text: str = ""` sur `CVAnalysisResult` (défaut vide ⇒ compatible). | Sans le texte analysé, aucune sous-chaîne exacte ne peut être citée : le champ est indispensable à la preuve verbatim. |
| `career/cv_quality/structure.py` | `analyze_cv()` renseigne `text=document.text`. | Idem, une seule ligne. |
| `career/cv_quality/__init__.py` | Export de `match_cv_to_offer` et des modèles de matching. | API publique. |
| `career/cv_quality/matching.py` | **Nouveau** — le moteur (1 447 lignes). | Cœur du lot. |
| `tests/test_cv_matching_adversarial.py` | **Nouveau** — 130 cas + 7 invariants + matrice de confusion. | Banc de régression. |

### Corrections apportées au moteur pendant le lot

| Correction | Pourquoi |
|---|---|
| Toute raison `DO_NOT_ADD` porte la phrase canonique « Aucune preuve dans le CV, ne pas ajouter sans preuve », la cause précise s'y ajoute. | Le prompt impose cette phrase ; elle ne doit pas disparaître sous une cause spécifique. |
| Les indices de quantification sont reconnus **mot entier** (`manager` ≠ `management`). | L'exemple du prompt (« expérience management » dans l'offre, « gère une équipe de 10 personnes » dans le CV) doit produire `QUANTIFY`, pas `HIGHLIGHT` (ADV-127). |
| Les séparateurs de clause anglais (`and`, `or`, `with`, `but`…) sont respectés comme les français. | La preuve d'un CV anglophone reste une extrait court, pas une phrase entière (ADV-129). |
| Une exigence structurée que le contrat CVBOOST-02 n'a pas extraite produit un avertissement. | Le contrat ignore toute phrase de moins de 4 caractères (`SQL`, `VBA`, `M&A`) : sans alerte, un faux négatif resterait silencieux. |

**Aucune règle métier existante n'est modifiée** : `career/service.py`,
`career/router.py`, `career_static/*`, `requirements*.txt`, les migrations et
`SCHEMA_VERSION` ne sont pas touchés. Le moteur est **additif** et n'est
appelé par **aucun flux produit** : c'est une surface de décision testée, à
brancher ensuite (mission 10 — intégration), pas un changement de
comportement en production.

> **Écart connu, à traiter par l'intégrateur** : le champ `text` de
> `CVAnalysisResult` (mission 01) n'est pas encore propagé dans
> `career/cv_quality/ats.py` (mission 04). Le moteur de matching accepte
> `cv_text=` en paramètre explicite pour ce cas.

---

## 6. Limites connues et écarts à traiter ailleurs

* **Le contrat d'exigences perd les exigences très courtes** : CVBOOST-02
  ignore toute phrase de moins de 4 caractères (`MIN_STATEMENT_CHARS = 4`),
  donc `SQL`, `VBA`, `M&A` seuls ne sont jamais extraits — le moteur ne peut
  pas y répondre. Le lot **le signale** (avertissement « non extraite par le
  contrat ») au lieu de le taire, mais la correction appartient à la mission
  02 (extraction) : sans elle, un profil PostgreSQL peut passer pour un
  profil MySQL sur une offre qui n'exige que « SQL ».
* **La détection de négation vit dans le moteur**, pas dans le contrat : le
  contrat ne marque que `not required`, le moteur reconnaît aussi « pas de »,
  « aucune », « sans », « ne pas ». Une exigence niée sortie du dénominateur
  par le moteur ne l'est pas par le contrat — les deux lectures doivent
  converger (mission 02 / mission 21).
* **Vocabulaire fermé** : les concepts sont une table curée (`CONCEPTS`). Une
  compétence hors table passe par le chemin générique (comparaison de mots),
  plus prudent mais moins fin. La table est le point d'extension naturel.
* **Pluriels** : la tolérance singulier/pluriel est volontairement simple
  (un « s » final, mots de 4 lettres et plus).
* **Niveaux de langue** : `natif`, `courant`, `professionnel`,
  `intermédiaire`, `débutant`, `lu`. Un niveau inconnu reste inconnu : le
  moteur produit `CONFIRM_LANGUAGE` plutôt que de deviner.
* **Contrat** : la détection porte sur la déclaration du CV (« je recherche
  un CDI »). Un CV qui n'énonce aucun contrat ne prouve rien sur le contrat :
  le moteur le dit.
* **Score** : couverture documentaire pondérée, pas probabilité d'embauche.
* **Le banc mesure le moteur, pas le produit** : c'est le complément du banc
  produit (`career/matching_bench/`, même branche) qui mesure l'écart entre
  le comportement applicatif réel et la vérité terrain.

---

## 7. Commandes de validation exécutées

```bash
.venv/bin/python -m pytest -q tests/test_cv_matching_adversarial.py
# 1181 passed

.venv/bin/python -m pytest -q tests/test_matching_bench_*.py
# 185 passed  (banc produit, même branche)

.venv/bin/python -m pytest -q
# suite complète verte (main a054c97 + moteur + les deux bancs)

.venv/bin/python -m ruff check .
# All checks passed!

git diff --check
# (vide) — aucun espace en fin de ligne, aucun conflit

VENV_PY=/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python ./checklist_codex.sh main
# TOUT VERT
```

---

## 8. Provenance et sécurité

* 100 % synthétique : entreprises, offres et profils fictifs (« Candidat
  Exemple », « Groupe Exemple », « Example Group »), aucun e-mail réel, aucun
  CV réel, aucune base Career lue, aucun secret.
* Aucun appel réseau : le moteur n'importe que `re`, `unicodedata`,
  `itertools`, `dataclasses`, `typing` et trois modules internes
  (`cv_quality.models`, `models.normalized_text`,
  `offer_requirements.extract`).
* Les preuves citées sont des extraits du CV, jamais des données de contact
  (invariant 7).

---

## 9. Suite proposée

1. **Brancher le moteur** sur le flux « plan CV » (mission 10) : le moteur
   produit la surface de décision, l'UI doit alors afficher la preuve et
   l'action, jamais une reformulation non sourcée.
2. **Corriger l'extraction courte côté contrat** (mission 02) : les exigences
   de moins de 4 caractères (`SQL`, `VBA`, `M&A`) doivent être extraites, et
   la détection de négation doit rejoindre celle du moteur.
3. **Élargir `CONCEPTS`** à partir des écarts mesurés par le banc produit
   (`career/matching_bench/`) : les 38 écarts sémantiques déjà mesurés
   sont la liste de travail.
4. **Remplacer la table de concepts** par les compétences réelles du
   référentiel `career` quand il existera, en gardant la règle : une
   compétence hors table ne vaut pas preuve.
