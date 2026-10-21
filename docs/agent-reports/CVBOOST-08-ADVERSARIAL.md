# CVBOOST-08 — Banc adversarial de matching CV/offre (121 cas)

Mission **CVBOOST-08** : fiabiliser le matching CV/offre contre les faux
positifs lexicaux, avec un banc de cas synthétiques reproductible et une
moteur de décision qui ne cite **jamais** une preuve absente du CV.

| | |
|---|---|
| Branche de travail | `worker/cvboost-08-1792569437` |
| Base | `main` (`3a0d1ee` — « merge: integrate reviewed Spec Kit Career cycles ») |
| Livrable | `career/cv_quality/matching.py` + `tests/test_cv_matching_adversarial.py` + ce rapport |
| Validation | 856 tests dédiés verts · 2223 tests de la suite complète verts · ruff clean · `git diff --check` propre |

> **Complément hors périmètre de cette branche** : un second banc, orienté
> *produit* (118 couples qui appellent le code applicatif réel — voir
> `docs/agent-reports/CVBOOST-08.md`), a été poussé sur
> `origin/agent/cvboost-08-adversarial` (commit `31d00b2`). Cette branche ne
> contient que le périmètre du prompt (moteur de référence + banc de cas
> adversariaux), afin que la relecture reste lisible.
>
> **État final pour l'intégrateur** : les deux livrables ont été fusionnés
> sur `origin/agent/cvboost-08-adversarial` (base `main`, commit de fusion
> `a407345`) — **une seule branche à intégrer**.

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
  dénominateur et produit un avertissement.

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
  d'embauche.

---

## 2. Le banc : 121 couples synthétiques, 10 familles

`tests/test_cv_matching_adversarial.py` — 121 couples (CV, offre) 100 %
synthétiques, 856 tests (chaque cas est passé au crible par 6 invariants).

| Famille | Cas | Le piège que la famille mesure |
|---|---|---|
| `faux_positif_lexical` | 18 | Excel ≠ analyse financière, Java ≠ JavaScript, PostgreSQL ≠ NoSQL, AWS ≠ Azure, « tableaux de bord » ≠ l'outil Tableau. |
| `langue` | 15 | « Anglais courant » déclaré, niveau absent, programme enseigné en anglais, niveau insuffisant, profil trilingue. |
| `contrat` | 12 | Stage ≠ CDI, alternance déclarée ou exclue, CDD, VIE, freelance, contrat non déclaré. |
| `diplome` | 12 | M1 / M2 / Bachelor / doctorat : le niveau se compare au niveau, pas au mot. |
| `homonyme` | 12 | Audit financier ≠ audit IT, gestion de projet ≠ gestion d'équipe, data analysis ≠ data engineering. |
| `multilingue` | 12 | Profils FR/EN/ES/DE, offres EN, langues jamais déclarées. |
| `acronyme` | 10 | M&A, Private Equity, Investment Banking, CRM, ERP, KPI. |
| `negation` | 10 | « Pas de gestion d'équipe », « aucune expérience », « sans déplacement », « not required ». |
| `absente` | 10 | Compétence 100 % absente → `DO_NOT_ADD`, jamais d'ajout. |
| `quantification` | 10 | Équipe de 10 personnes, budget de 500 k€, chiffres absents. |

Toutes les exigences du prompt sont couvertes : Excel/analyse financière,
Java/JavaScript, langue déclarée vs programme enseigné, stage vs CDI,
alternance exclue, M1/M2/Bachelor, mot nié, compétence présente dans l'offre
seulement, acronymes (M&A, PE, IB), homonymes sectoriels (audit financier vs
audit IT), profil multilingue.

---

## 3. Matrice de confusion (mesurée)

Mesure faite sur les **125 exigences** dont la vérité terrain est écrite à la
main dans le banc (couverture : l'exigence est-elle prouvée par le CV ?).

| | CV prouve | CV ne prouve pas |
|---|---|---|
| **Vérité : l'exigence est prouvable** | 57 (TP) | 0 (FN) |
| **Vérité : l'exigence n'est pas prouvable** | 0 (FP) | 68 (TN) |

* **Précision = 1.0000**, **rappel = 1.0000**
* **Faux positifs = 0** — aucun cas où le moteur invente une preuve ;
* **Faux négatifs = 0** — aucun cas où une preuve présente est refusée.

Matrice par code d'action (125 exigences évaluées) :

| Famille | HIGHLIGHT | REPHRASE | DO_NOT_ADD | QUANTIFY | CONFIRM_LANGUAGE | niée (hors dénominateur) |
|---|---|---|---|---|---|---|
| faux_positif_lexical | 9 | 0 | 9 | 1 | 0 | 0 |
| acronyme | 5 | 0 | 5 | 0 | 0 | 0 |
| langue | 8 | 0 | 7 | 0 | 1 | 0 |
| contrat | 3 | 0 | 9 | 0 | 0 | 0 |
| diplome | 7 | 0 | 5 | 0 | 0 | 0 |
| negation | 3 | 0 | 1 | 0 | 0 | 6 |
| absente | 1 | 0 | 11 | 0 | 0 | 0 |
| homonyme | 4 | 0 | 8 | 0 | 0 | 0 |
| quantification | 4 | 1 | 3 | 2 | 0 | 0 |
| multilingue | 8 | 0 | 10 | 0 | 0 | 0 |
| **Total** | **52** | **1** | **68** | **3** | **1** | **6** |

Lecture : **68 exigences sur 125 ne sont pas prouvées** par le CV. C'est le
cœur du lot — un banc qui ne trouve que des positives ne mesure rien.

### Les six invariants vérifiés sur *chaque* cas

1. `preuve_toujours_verbatim` — toute preuve est une sous-chaîne exacte du CV
   et l'offset annoncé redonne exactement cette sous-chaîne ;
2. `absent_jamais_ajoute` — `DO_NOT_ADD` ⟹ aucune preuve, et inversement ;
3. `determinisme` — deux exécutions rendent le même `MatchResult` ;
4. `aucune_donnee_de_contact` — ni e-mail, ni téléphone, ni LinkedIn dans la
   surface de décision ;
5. `score_determine_et_borne` — score borné, cohérent avec les actions ;
6. `exigence_obligatoire_manquante_signalee` — `missing_critical` ne
   contient que des exigences réellement traitées.

---

## 4. Comment chaque piège est traité

| Piège | Traitement | Cas |
|---|---|---|
| Excel ≠ analyse financière | Concepts distincts : `excel` n'est pas dans la famille `finance`. | ADV-001, ADV-004 |
| Modélisation ≠ analyse financière | Même famille ⇒ `REPHRASE` (reformuler avec la preuve), jamais `HIGHLIGHT`. | ADV-003 |
| Java ≠ JavaScript | Correspondance par **mot entier** : `java` ne prouve jamais `javascript`. | ADV-005, ADV-006 |
| Un programme enseigné en anglais ≠ un niveau d'anglais | Contexte d'enseignement détecté (même ligne) ⇒ aucune preuve de niveau. | ADV-032, ADV-038 |
| Stage ≠ CDI | Le contrat déclaré par le CV est comparé à celui de l'offre. | ADV-043, ADV-047 |
| Alternance exclue | Le CV déclare « CDI » **et** exclut « alternance » : les deux sont tenus séparés. | ADV-045 |
| M1 ≠ M2 ≠ Bachelor | Niveaux ordonnés, comparaison par rang ; le niveau générique « master » n'écrase pas « master 1 ». | ADV-055, ADV-056 |
| Mot nié | Une exigence niée **n'est pas une exigence** : elle sort du dénominateur et produit un avertissement. | ADV-067 à ADV-076 |
| Compétence absente | `DO_NOT_ADD` avec la raison canonique. | ADV-077 à ADV-086 |
| Acronymes | M&A ↔ fusions-acquisitions, PE ↔ private equity, majuscules strictes pour les acronymes courts (`PE`, `IB`, `R`). | ADV-019 à ADV-022 |
| Homonymes sectoriels | Groupes d'homonymes : audit financier ≠ audit IT, data analysis ≠ data engineering, gestion de projet ≠ gestion d'équipe. | ADV-087 à ADV-098 |
| Multilingue | La preuve est cherchée par langue **et** par niveau, sur la ligne qui déclare la langue. | ADV-109 à ADV-112 |
| Quantification | Preuve chiffrée ⇒ `QUANTIFY` ; exigence d'échelle sans chiffre ⇒ `QUANTIFY`. | ADV-099 à ADV-108 |

Trois pièges supplémentaires que le lot treats :

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
| `career/cv_quality/matching.py` | **Nouveau** — le moteur (1 358 lignes). | Cœur du lot. |
| `tests/test_cv_matching_adversarial.py` | **Nouveau** — 121 cas + 6 invariants. | Banc de régression. |

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

## 6. Limites connues

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
  produit (`career/matching_bench/`, autre branche) qui mesure l'écart entre
  le comportement applicatif réel et la vérité terrain.

---

## 7. Commandes de validation exécutées

```bash
.venv/bin/python -m pytest -q tests/test_cv_matching_adversarial.py
# 856 passed

.venv/bin/python -m pytest -q
# 2223 passed, 1 skipped in 403.64s   (base main : aucune régression)

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
  Exemple », « Groupe Exemple »), aucun e-mail réel, aucun CV réel, aucune
  base Career lue, aucun secret.
* Aucun appel réseau : le moteur n'importe que `re`, `unicodedata`,
  `itertools`, `dataclasses`, `typing` et deux modules internes
  (`cv_quality.models`, `offer_requirements.extract`).
* Les preuves citées sont des extraits du CV, jamais des données de contact
  (invariant 4).

---

## 9. Suite proposée

1. **Brancher le moteur** sur le flux « plan CV » (mission 10) : le moteur
   produit la surface de décision, l'UI doit alors afficher la preuve et
   l'action, jamais une reformulation non sourcée.
2. **Élargir `CONCEPTS`** à partir des écarts mesurés par le banc produit
   (`career/matching_bench/`) : les 38 écarts sémantiques déjà mesurés
   sont la liste de travail.
3. **Remplacer la table de concepts** par les compétences réelles du
   référentiel `career` quand il existera, en gardant la règle : une
   compétence hors table ne vaut pas preuve.
