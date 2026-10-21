# CVBOOST-08 — Banc adversarial de matching CV/offre

**Mission** : moteur de matching CV↔offre qui refuse les faux positifs lexicaux, et banc de 100+ couples synthétiques qui le mesure.

**Branche** : `worker/cvboost-08-1792586141` (branche à intégrer : `agent/cvboost-08-adversarial`)
**Base** : `main` (`a054c97`)

---

## 1. Architecture

### Fichiers livrés

| Fichier | Rôle |
|---------|------|
| `career/cv_quality/matching.py` | **Nouveau** — moteur `match_cv_to_offer(cv_result, offer) -> MatchResult` (pure, déterministe, hors ligne) |
| `career/cv_quality/models.py` | Étendu — `MatchAction`, `MatchActionCode`, `MatchEvidence`, `MatchResult` + champ `text` sur `CVAnalysisResult` |
| `career/cv_quality/__init__.py` | Export de `match_cv_to_offer` et des modèles de matching |
| `career/cv_quality/structure.py` | **1 ligne** — `analyze_cv` renseigne le texte analysé (voir §1.2) |
| `tests/test_cv_matching_adversarial.py` | **Nouveau** — 139 couples adversariaux, 11 familles, 9 assertions par cas |
| `docs/agent-reports/CVBOOST-08-ADVERSARIAL.md` | Ce rapport |

### 1.1 Le contrat produit

```python
from career.cv_quality import analyze_cv, DocumentInput, match_cv_to_offer

result = analyze_cv(DocumentInput(text=cv_text, filename="cv.pdf", filetype="pdf"))
match = match_cv_to_offer(result, offer_dict)

match.overall_score        # 0.0-1.0 — couverture pondérée de l'offre
match.matched_requirements # exigences couvertes par une preuve du CV
match.total_requirements   # exigences traitées (une négation n'en est pas une)
match.actions              # une action par exigence
match.missing_critical     # exigences obligatoires sans preuve
match.warnings             # alertes non bloquantes
```

Chaque action :

```python
@dataclass(frozen=True, slots=True)
class MatchAction:
    code: MatchActionCode      # HIGHLIGHT | REPHRASE | DO_NOT_ADD | QUANTIFY | CONFIRM_LANGUAGE
    requirement_text: str      # extrait exact de l'offre
    cv_evidence_text: str|None # sous-chaîne EXACTE du CV, ou None
    cv_evidence_offset: int|None
    reason: str                # pourquoi cette action
    confidence: float          # 0.0-1.0, déterministe
    evidence: MatchEvidence|None
```

### 1.2 Une modification hors périmètre, assumée et minimale

La preuve exigée par la mission est **une sous-chaîne exacte du CV + son offset**. Or `CVAnalysisResult` (Mission 01) ne portait que des offsets, jamais le texte analysé : impossible de garantir l'exactitude sans lui.

La modification est donc de **deux lignes au total** :

- `models.py` : `CVAnalysisResult.text: str = ""` (champ optionnel, valeur par défaut, aucun appelant cassé) ;
- `structure.py` : `text=text` dans le constructeur de `analyze_cv`.

Ce n'est pas une intrusion fonctionnelle : aucun flux produit n'est modifié, `career/service.py`, `career/router.py`, `career_static/*`, `requirements*.txt`, les migrations et `SCHEMA_VERSION` sont intacts. Le moteur accepte en outre un override explicite (`match_cv_to_offer(result, offer, cv_text=...)`) pour un CV déjà en mémoire.

---

## 2. Comment le moteur décide

### 2.1 La chaîne de décision

1. **Lecture des exigences** — via le contrat CVBOOST-02 (`career.offer_requirements.analyze_offer`). Le moteur ne réécrit pas l'extraction : il lit `text`, `modality`, `category`, `negated`.
2. **Détection de catégorie** — langue / niveau d'études / type de contrat / compétence, avec des règles dédiées qui évitent les faux positifs :
   - langue : un *programme enseigné* en anglais n'est pas un niveau d'anglais ;
   - diplôme : M1 (Bac+4) ≠ M2 (Bac+5), un « master » nu vaut Bac+5, une licence professionnelle vaut Bac+4 ;
   - contrat : `je recherche un CDI, pas d'alternance` déclare **et** exclut, les deux sont lus ;
   - compétence : table de concepts avec synonymes, acronymes, familles et homonymes.
3. **Recherche de preuve** — tokenisation avec table de correspondance 1:1 vers les caractères d'origine (accents, `&`, ponctuation), puis recherche de la phrase la plus serrée qui prouve l'exigence. La preuve est **toujours** `source[debut:fin]`, donc toujours verbatim.
4. **Choix de l'action** — voir §2.2.
5. **Score et alertes** — voir §2.3.

### 2.2 Les cinq actions

| Action | Quand | Couverture |
|--------|-------|------------|
| `HIGHLIGHT` | La preuve verbatim prouve l'exigence | 1.0 |
| `QUANTIFY` | L'exigence porte sur un volume (équipe, budget, CA) : le chiffre du CV doit être explicite — ou le résultat doit être chiffré | 0.9 |
| `CONFIRM_LANGUAGE` | La langue est là, le niveau exigé n'est pas déclaré | 0.8 |
| `REPHRASE` | Une compétence voisine existe, ou le niveau exigé n'est pas attesté : il faut reformuler fidèlement, pas annoncer plus | 0.6 |
| `DO_NOT_ADD` | Aucune preuve dans le CV | 0.0 |

`DO_NOT_ADD` porte toujours la raison fixée par la mission — « Aucune preuve dans le CV, ne pas ajouter sans preuve » — suivie, entre parenthèses, du diagnostic précis (« niveau d'études bac+4 inférieur au niveau exigé bac+5 »). La règle d'or est tenue : **une action `DO_NOT_ADD` ne porte jamais de preuve**, et une action étayée en porte toujours une.

### 2.3 Le score

`overall_score` = moyenne pondérée de la couverture des exigences :

```
score = Σ (poids_modalité × couverture_action) / Σ poids_modalité
poids_modalité : obligatoire 1.0 | souhaité 0.5 | contextuel/inconnu 0.3
couverture_action : HIGHLIGHT 1.0 | QUANTIFY 0.9 | CONFIRM_LANGUAGE 0.8 | REPHRASE 0.6 | DO_NOT_ADD 0.0
```

Une exigence **niée** (« pas de gestion d'équipe ») n'est pas une exigence : elle ne produit pas d'action, ne pèse pas sur le score, et déclenche un avertissement. Elle est exclue du dénominateur, jamais comptée comme couverte.

`matched_requirements` ne compte que les exigences **couvertes** (HIGHLIGHT, QUANTIFY, CONFIRM_LANGUAGE) : un `REPHRASE` montre une compétence voisine, pas l'exigence demandée.

---

## 3. Les pièges traités

| Famille | Piège | Traitement |
|---------|-------|------------|
| Compétences proches | Excel ≠ Analyse financière ; Java ≠ JavaScript ; PostgreSQL ≠ NoSQL ; AWS ≠ Azure ; Power BI ≠ Tableau | Concepts distincts, homonymes explicites, pluriels `-aux` (`tableau`↔`tableaux`) |
| Tableaux de bord | « tableaux de bord » (reporting) ≠ « Tableau » (l'outil) | Mot d'exclusion appliqué **des deux côtés** : côté CV et côté exigence |
| Acronymes | M&A ↔ Fusions-acquisitions ; PE ↔ Private Equity ; IB ↔ Investment Banking | Surfaces synchronisées, acronymes courts en majuscules uniquement |
| Langues | « Programme en anglais » ≠ « Anglais courant » ; « lu » ≠ « courant » | Contexte d'enseignement exclu ; échelle de niveaux comparée |
| Contrats | Stage ≠ CDI ; alternance exclue ; CDD ≠ CDI ; VIE, freelance | Déclaration **et** exclusion lues dans le CV ; incompatibilité signalée |
| Niveaux d'études | M1 ≠ M2 ; Bachelor ≠ Master ; Doctorat | Échelle de rangs, niveau du CV atteint ou non |
| Négation | « pas de gestion d'équipe », « sans Python », « No Python required » | Négation détectée (FR/EN), sortie du dénominateur, **conflit signalé** si le CV porte la compétence exclue |
| Compétence absente | Exigence 100 % absente | `DO_NOT_ADD`, jamais d'ajout |
| Homonymes sectoriels | Audit financier ≠ audit IT ; gestion de projet ≠ gestion d'équipe ; risk management ≠ risque IT | Groupes d'homonymes : le conflit est une alerte, pas une preuve |
| Quantification | « Gestion d'équipe » vs « Pilotage de projets » ; budget ; CA | `QUANTIFY` quand l'exigence porte sur un volume, avec le chiffre du CV |
| Niveaux de compétence | « Excel avancé » vs un CV qui écrit « Excel » | Échelle de maîtrise : exigence non attestée → `REPHRASE` + alerte |
| Multilingue | Offre EN, CV FR ; compétences transposables FR→EN | Langue de l'offre détectée, niveau de langue contrôlé, compétences transposables |

---

## 4. Le banc : 139 couples, 11 familles

`tests/test_cv_matching_adversarial.py` — 139 couples synthétiques (aucune donnée réelle, aucun appel réseau).

| Famille | Cas | | Famille | Cas |
|---------|-----|-|---------|-----|
| faux_positif_lexical | 18 | | absente | 10 |
| langue | 15 | | homonyme | 11 |
| multilingue | 16 | | quantification | 11 |
| diplome | 13 | | acronyme | 11 |
| negation | 13 | | contrat | 11 |
| niveau_competence | 10 | | **total** | **139** |

Chaque cas est un `dict` conforme à la structure proposée par la mission :

```python
{
    "id": "ADV-001",
    "name": "Excel ≠ analyse financière",
    "family": "faux_positif_lexical",
    "cv_text": "...",
    "offer_requirements": ["Excel avance", "Analyse financiere"],
    "expected_actions": [
        {"code": "HIGHLIGHT", "requirement": "Excel avance", "cv_evidence": "Excel avance"},
        {"code": "DO_NOT_ADD", "requirement": "Analyse financiere", "cv_evidence": None},
    ],
    "expected_score_range": (0.5, 0.5),
    "expected_warnings": [],
}
```

`expected_score_range` est la couverture déduite de la vérité terrain écrite à la main : le score du moteur doit y tomber. C'est un croisement indépendant, pas une tautologie — une disagreement entre la vérité et le moteur fait échouer le banc.

### 4.1 Matrice de confusion (attendu → obtenu)

| Attendu \ Obtenu | HIGHLIGHT | QUANTIFY | CONFIRM_LANGUAGE | REPHRASE | DO_NOT_ADD |
|---|---|---|---|---|---|
| **HIGHLIGHT** | **58** | 0 | 0 | 0 | 0 |
| **QUANTIFY** | 0 | **5** | 0 | 0 | 0 |
| **CONFIRM_LANGUAGE** | 0 | 0 | **1** | 0 | 0 |
| **REPHRASE** | 0 | 0 | 0 | **5** | 0 |
| **DO_NOT_ADD** | 0 | 0 | 0 | 0 | **73** |

142 exigences évaluées, **aucune confusion**.

Sur la décision binaire « l'exigence est-elle couverte par le CV ? » (couverte =
HIGHLIGHT, QUANTIFY ou CONFIRM_LANGUAGE ; un `REPHRASE` montre une compétence
voisine, pas l'exigence) :

| | Couvert attendu | Non couvert attendu |
|---|---|---|
| **Couvert obtenu** | 64 (VP) | 0 (FP) |
| **Non couvert obtenu** | 0 (FN) | 78 (VN) |

**Précision 1.0000 · Rappel 1.0000 · F1 1.0000** — sur la vérité connue du banc.

Répartition par famille :

| Famille | HIGHLIGHT | QUANTIFY | CONFIRM_LANGUAGE | REPHRASE | DO_NOT_ADD |
|---|---|---|---|---|---|
| faux_positif_lexical | 10 | 0 | 0 | 0 | 9 |
| multilingue | 10 | 0 | 0 | 0 | 13 |
| langue | 8 | 0 | 1 | 0 | 7 |
| diplome | 7 | 0 | 0 | 0 | 6 |
| acronyme | 6 | 0 | 0 | 0 | 5 |
| niveau_competence | 6 | 0 | 0 | 4 | 1 |
| quantification | 2 | 5 | 0 | 1 | 3 |
| homonyme | 3 | 0 | 0 | 0 | 8 |
| contrat | 2 | 0 | 0 | 0 | 9 |
| negation | 3 | 0 | 0 | 0 | 1 |
| absente | 1 | 0 | 0 | 0 | 11 |
| **Total** | **58** | **5** | **1** | **5** | **73** |

### 4.2 Les neuf assertions vérifiées sur chaque cas

1. les actions produites sont celles attendues (code + preuve exacte) ;
2. le score global tombe dans la plage attendue ;
3. les avertissements annoncés sont présents ;
4. toute preuve citée est une **sous-chaîne exacte** du CV, à l'offset exact ;
5. `DO_NOT_ADD` ⇒ **aucune** preuve **et** raison canonique ; action étayée ⇒ **toujours** une preuve ;
6. deux exécutions ⇒ résultat identique (déterminisme) ;
7. le score est borné, `matched_requirements` ne compte que les exigences couvertes ;
8. toute exigence obligatoire non couverte figure dans `missing_critical` ;
9. aucune donnée de contact (e-mail, téléphone, LinkedIn) ne fuit dans la décision.

---

## 5. Limites connues

- **Vocabulaire fermé** : la table de concepts couvre les skills du périmètre (finance, data, dev, cloud, management). Une compétence hors table retombe sur la comparaison de tokens, qui est plus permissive : « Reporting commercial » face à « reporting » rend `REPHRASE` (preuve partielle), pas `DO_NOT_ADD`. C'est un choix : mieux vaut une rephrase signalée qu'un faux négatif.
- **Extraction CVBOOST-02** : l'extracteur ignore les statements de moins de 4 caractères (« M&A » seul est écarté, « Experience en M&A » est conservé). Le banc formule donc les exigences abrégées en phrase pleine. Le moteur ne peut pas matcher ce que l'extraction n'a pas produit.
- **Niveau de compétence** : l'échelle couvre basique / intermédiaire / avancé / expert (FR et EN). Un niveau non nommé (« maîtrise ») est traité comme « non attesté », donc `REPHRASE`.
- **Langue de l'offre** : détection par marqueurs lexicaux (au moins 3 marqueurs discriminants). Une offre bilingue ou très courte reste indéterminée — elle ne déclenche alors aucune alerte.
- **Un seul CV, une seule offre** : le moteur ne compare pas deux CV entre eux et ne connaît pas l'historique du candidat.
- **Hors périmètre du moteur** : aucun enchaînement de produit n'est branché. Le matching est un moteur de référence ; son branchement dans le flux « application_prep » relève d'une mission dédiée.
- **Écart connu** : le champ `text` de `CVAnalysisResult` (mission 01) n'est pas encore propagé dans `career/cv_quality/ats.py` (mission 04). Le moteur accepte `cv_text=` en paramètre explicite pour ce cas.

---

## 6. Validation

```bash
.venv/bin/python -m pytest -q tests/test_cv_matching_adversarial.py   # 1263 passed
.venv/bin/python -m pytest -q                                         # suite complète verte
.venv/bin/python -m ruff check .                                      # All checks passed!
git diff --check                                                     # propre
VENV_PY=... .venv/bin/python ./checklist_codex.sh main                # TOUT VERT
```

Aucune régression : les tests préexistants passent inchangés, le moteur est
additif et n'est appelé par aucun flux produit.

---

## 7. Checklist de relecture

- [x] `match_cv_to_offer()` pure, déterministe, sans réseau, sans LLM, sans horloge
- [x] 139 couples adversariaux passent (précision et rappel = 1.0000 sur la vérité connue)
- [x] Faux positifs historiques éliminés (Excel≠Analyse, Java≠JS, Stage≠CDI, M1≠M2, …)
- [x] Règle `DO_NOT_ADD` respectée : aucune invention, aucune preuve sur une action non étayée
- [x] Preuve exacte (sous-chaîne CV + offset) pour chaque action `HIGHLIGHT` / `REPHRASE` / `QUANTIFY` / `CONFIRM_LANGUAGE`
- [x] Alertes pour alternance, négations, langues, homonymes, niveaux
- [x] Ruff clean, suite complète verte, `git diff --check` propre
- [x] Rapport avec matrice de confusion et limites connues
