# CVBOOST-08 — Banc adversarial de matching CV/offre (matching deterministe)

Mission **CVBOOST-08**. Deux livrables complémentaires :

| Livrable | Emplacement | Rôle |
|---|---|---|
| Banc de régression du **produit** | `career/matching_bench/` | Appelle le code applicatif réel sur 118 couples synthétiques et confronte le résultat à une vérité terrain. Rapport : [`CVBOOST-08.md`](CVBOOST-08.md). |
| Moteur de matching **adversarial** | `career/cv_quality/matching.py` | `match_cv_to_offer()` : fonction pure, déterministe, hors ligne, qui refuse les faux positifs lexicaux. Ce rapport. |

Base : `bc5db69` (branche `agent/cvboost-08-adversarial`).
Commandes de validation réellement exécutées :

```bash
.venv/bin/python -m pytest -q tests/test_cv_matching_adversarial.py   # 856 passed
.venv/bin/python -m pytest -q                                         # 2398 passed (1542 avant lot)
.venv/bin/python -m ruff check career/cv_quality/ tests/test_cv_matching_adversarial.py
# All checks passed!
```

---

## 1. Ce que fait le moteur

```python
from career.cv_quality import DocumentInput, analyze_cv, match_cv_to_offer

analysis = analyze_cv(DocumentInput(text=cv_text, filename="cv.txt", filetype="txt"))
result = match_cv_to_offer(analysis, offer)
```

* **Pure** : pas de réseau, pas de modèle, pas d'horloge, pas d'aléatoire.
  Deux exécutions sur les mêmes entrées rendent le même objet.
* **Traçable** : chaque action cite une **sous-chaîne exacte** du CV, avec
  son offset. Rien n'est paraphrasé, rien n'est inventé.
* **Prudent** : une exigence sans preuve rend `DO_NOT_ADD` — ce qui est
  absent du CV n'est jamais ajouté.
* **Exigeant** : les exigences sont lues par le contrat CVBOOST-02
  (`analyze_offer`), jamais par un découpage maison.

### Codes d'action

| Code | Signification |
|---|---|
| `HIGHLIGHT` | Preuve verbatim trouvée : la compétence est dans le CV. |
| `REPHRASE` | Preuve partielle ou de la même famille : reformuler avec la **preuve du CV**, pas avec le vocabulaire de l'offre. |
| `DO_NOT_ADD` | Aucune preuve : ne pas ajouter sans preuve. |
| `QUANTIFY` | La preuve existe mais doit être chiffrée (ou contient déjà un chiffre à expliciter). |
| `CONFIRM_LANGUAGE` | La langue est là, le niveau exigé ne l'est pas : à confirmer. |

---

## 2. Les 121 cas adversariaux

`tests/test_cv_matching_adversarial.py` — 121 couples synthétiques, 10
familles, 856 tests (chaque cas est vérifié par 6 invariants).

| Famille | Cas | Ce que le piège casse |
|---|---|---|
| `faux_positif_lexical` | 18 | Excel ≠ analyse financière, Java ≠ JavaScript, PostgreSQL ≠ NoSQL, AWS ≠ Azure, « tableaux de bord » ≠ l'outil Tableau. |
| `langue` | 15 | « Anglais courant » déclaré, niveau absent, programme enseigné en anglais, niveau insuffisant, profil trilingue. |
| `contrat` | 12 | Stage ≠ CDI, alternance déclarée ou exclue, CDD, VIE, freelance, contrat non déclaré. |
| `diplome` | 12 | M1 / M2 / Bachelor / doctorat : le niveau se compare au niveau, pas au mot. |
| `homonyme` | 12 | Audit financier vs audit IT, gestion de projet vs gestion d'équipe, data analysis vs data engineering. |
| `multilingue` | 12 | Profils FR/EN/ES/DE, offres EN, langues jamais déclarées. |
| `acronyme` | 10 | M&A, Private Equity, Investment Banking, CRM, ERP, KPI. |
| `negation` | 10 | « Pas de gestion d'équipe », « aucune expérience », « sans déplacement », « not required ». |
| `absente` | 10 | Compétence 100 % absente → `DO_NOT_ADD`, jamais d'ajout. |
| `quantification` | 10 | Équipe de 10 personnes, budget de 500 k€, chiffres absents. |

### Matrice de confusion (actions attendues, 125 actions au total)

| Famille | HIGHLIGHT | REPHRASE | DO_NOT_ADD | QUANTIFY | CONFIRM_LANGUAGE | exigence niée |
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

Lecture : 68 exigences sur 125 ne sont **pas** prouvées par le CV. C'est le
cœur du lot — un banc qui ne trouve que des positives ne mesure rien.

### Les six invariants vérifiés sur *chaque* cas

1. `preuve_toujours_verbatim` — toute preuve est une sous-chaîne exacte du CV,
   et l'offset announced=redonne exactement cette sous-chaîne ;
2. `absent_jamais_ajoute` — `DO_NOT_ADD` ⟹ aucune preuve, et inversement ;
3. `determinisme` — deux exécutions rendent le même `MatchResult` ;
4. `aucune_donnee_de_contact` — ni e-mail, ni téléphone, ni LinkedIn dans la
   surface de décision ;
5. `score_determine_et_borne` — score borné, cohérent avec les actions ;
6. `exigence_obligatoire_manquante_signalee` — `missing_critical` ne contient
   que des exigences réellement traitées.

---

## 3. Comment les pièges sont traités

| Piège | Traitement | Cas |
|---|---|---|
| Excel ≠ analyse financière | Concepts distincts : « excel » n'est pas dans la famille « finance ». | ADV-001, ADV-004 |
| Modélisation ≠ analyse financière | Même famille ⇒ `REPHRASE` (reformuler avec la preuve), jamais `HIGHLIGHT`. | ADV-003 |
| Java ≠ JavaScript | Correspondance par **mot entier** : « java » ne prouve jamais « javascript ». | ADV-005, ADV-006 |
| Un programme enseigné en anglais ≠ un niveau d'anglais | Contexte d'enseignement détecté (même ligne) ⇒ aucune preuve de niveau. | ADV-032, ADV-038 |
| Stage ≠ CDI | Le contrat déclaré par le CV est comparé à celui de l'offre. | ADV-043, ADV-047 |
| Alternance exclue | Le CV déclare « CDI » **et** exclut « alternance » : les deux sont tenus séparés. | ADV-045 |
| M1 ≠ M2 ≠ Bachelor | Niveaux ordonnés, comparaison par rang ; le niveau générique « master » n'écrase pas « master 1 ». | ADV-055, ADV-056 |
| Mot nié | Une exigence niée **n'est pas une exigence** : elle sort du dénominateur et produit un avertissement. | ADV-067 à ADV-076 |
| Compétence absente | `DO_NOT_ADD` avec la raison canonique. | ADV-077 à ADV-086 |
| Acronymes | M&A ↔ fusions-acquisitions, PE ↔ private equity, en majuscules stricts pour les acronymes courts (`PE`, `IB`, `R`). | ADV-019 à ADV-022 |
| Homonymes | Groupes d'homonymes : audit financier ≠ audit IT, data analysis ≠ data engineering. | ADV-087 à ADV-090 |
| Multilingue | La preuve est cherchée par langue et par niveau, sur la ligne qui déclare la langue. | ADV-109 à ADV-112 |
| Quantification | Preuve chiffrée ⇒ `QUANTIFY` ; exigence d'échelle sans chiffre ⇒ `QUANTIFY`. | ADV-099 à ADV-108 |

Trois pièges supplémentaires que le lot a ajoutés :

* **« EXPERIENCE », « LANGUES »… ne prouvent rien** : les en-têtes de section
  du CV sont exclus du corpus de preuve (ADV-076).
* **« tableaux de bord » ≠ l'outil Tableau** : une preuve peut être annulée
  par la phrase qui la suit (ADV-014, ADV-098).
* **Deux occurrences ne se prouvent pas l'une l'autre** : la preuve est
  locale (une ligne, une clause) — « commercial » dans un intitulé de poste
  et « reporting » dans une ligne de mission ne prouvent pas « reporting
  commercial » (ADV-107).

---

## 4. Modifications apportées au code existant

Le lot **n'ajoute** que ce qui lui est nécessaire, et le signale :

| Fichier | Modification | Pourquoi |
|---|---|---|
| `career/cv_quality/models.py` | Ajout de `MatchAction`, `MatchResult`, `MatchEvidence`, `MatchActionCode` et d'un champ `text: str = ""` sur `CVAnalysisResult` (défaut vide, compatible). | Sans le texte analysé, aucune sous-chaîne exacte ne peut être citée ; le champ est donc indispensable à la preuve verbatim. |
| `career/cv_quality/structure.py` | `analyze_cv()` renseigne `text=document.text`. | Idem, une seule ligne. |
| `career/cv_quality/__init__.py` | Export de `match_cv_to_offer` et des modèles de matching. | API publique. |

**Aucune règle métier existante n'est modifiée** : `career/service.py`,
`career/router.py`, `career_static/*`, les migrations et `SCHEMA_VERSION` ne
sont pas touchés. Le moteur est additif et n'est appelé par aucun flux
produit : c'est une surface de décision testée, pas un changement de
comportement.

---

## 5. Limites connues (à traiter par l'intégrateur)

* **Vocabulaire fermé** : les concepts sont une table curée
  (`CONCEPTS`). Une compétence hors table passe par le chemin générique
  (comparaison de mots), qui est plus prudent mais moins fin. La table est
  le point d'extension naturel.
* **Pluriels** : la tolérance singulier/pluriel est volontairement simple
  (un « s » final, mots de 4 lettres et plus).
* **Niveaux de langue** : `natif`, `courant`, `professionnel`,
  `intermédiaire`, `débutant`, `lu`. Un niveau inconnu reste inconnu : le
  moteur produit `CONFIRM_LANGUAGE` plutôt que de deviner.
* **Contrat** : la détection porte sur la déclaration du CV
  (« je recherche un CDI »). Un CV qui n'énonce aucun contrat ne prouve
  rien sur le contrat : le moteur le dit.
* **Score** : pondéré par modalité (obligatoire 1.0, souhaitable 0.5,
  contextuel 0.3). Il mesure la **couverture documentaire**, pas une
  probabilité d'embauche.

---

## 6. Ce que le banc de produit (`career/matching_bench/`) ajoute

Le moteur ci-dessus est *juste*. Le banc de produit est *honnête* : il
appelle le code applicatif réel (`prepare_application`, `analyze_offer`,
`score_brief_match`, `assess_education_access`, `qualify_offer`) et mesure
l'écart entre le comportement réel et la vérité terrain des 118 couples.

Résultat de la dernière exécution (reproductible) :

```
118 cas — défauts durs : 3 (max 3) — écarts sémantiques : 38 (max 38)
Seuils respectés.
```

Les 38 écarts sémantiques mesurés sont les faux positifs que ce moteur de
référence sait éviter ; c'est la mesure qui permet de les réduire ensuite
dans le produit, sans masquer ce qui reste ouvert.

---

## 7. Provenance

* 100 % synthétique : entreprises, offres et profils fictifs, aucun e-mail
  réel, aucun appel réseau, aucun secret lu.
* Les profils de test sont des « Candidat Exemple » ; les domaines
  réservés restent `exemple-fake.test`.
* Aucune donnée personnelle, aucun CV réel, aucune base Career lue.
