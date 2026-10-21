# CVBOOST-21 — Matching CV ↔ offre (actions concrètes)

Statut : TERMINÉE (fonction pure, déterministe, hors ligne ; aucune donnée réelle ; aucun envoi).

Branche : `agent/cvboost-21-matching`
Base : `main` @ `3a0d1ee` (« merge: integrate reviewed Spec Kit Career cycles »)
Worktree : `/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-21-1792569485`

## 1. Ce qui a été construit

| Fichier | Statut | Rôle |
| --- | --- | --- |
| `career/cv_quality/matching.py` | **nouveau** | `match_cv_to_offer(cv_result, offer) -> MatchResult` — une action concrète par exigence, avec provenance exacte |
| `career/cv_quality/models.py` | étendu | `MatchAction`, `MatchEvidence`, `MatchResult`, `MatchActionCode` + `Provenance.source_text` |
| `career/cv_quality/__init__.py` | étendu | exporte `match_cv_to_offer`, `find_evidence_in_cv` et les nouveaux modèles |
| `career/cv_quality/structure.py` | 1 ligne | `Provenance.source_text = text` — le texte source est gardé pour la provenance exacte |
| `tests/test_cv_matching_actions.py` | **nouveau** | 42 tests unitaires (mission : ≥ 20) |
| `docs/agent-reports/CVBOOST-21-MATCHING.md` | **nouveau** | ce rapport |

Interdits respectés : `career/service.py`, `career/router.py`, `career_static/*`,
`requirements*.txt`, aucune migration, `SCHEMA_VERSION` intact.

### Écart assumé avec le squelette de la mission

Le squelette de la mission suppose deux choses qui n'existent pas dans la base
`3a0d1ee` :

1. `cv_result.provenance.full_text` — la `Provenance` de la Mission 01 ne
   contenait que `filename`, `filetype`, `text_length` et `page_count`. Sans le
   texte source, **aucune sous-chaîne exacte ni offset ne peut être calculé** :
   `Provenance.source_text` a donc été ajouté (optionnel, `None` par défaut,
   aucun changement de comportement pour les consommateurs existants) et
   `structure.analyze_cv` le renseigne.
2. `cv_result.education_max_level` — ce champ n'existe pas et l'ajouter
   imposerait de modifier `structure.py` bien au-delà d'une ligne. Le niveau
   d'études du CV est donc **déduit** par `matching.py` de la section
   « Formation » du CV (échelle « Bac+X »), et celui de l'offre de
   `offer["education_level"]` ou des exigences de catégorie `education`.

Autre adaptation : la Mission 02 décrit les exigences avec une `modality`
(`required` / `preferred` / `contextual` / `unknown`), pas avec un booléen
`mandatory`. Les deux sont lus : le booléen explicite gagne, sinon
`modality == "required"` ⇒ obligatoire, et une modalité `unknown` n'est
jamais devinée obligatoire.

## 2. Contrat livré

```python
match_cv_to_offer(cv_result: CVAnalysisResult, offer: dict) -> MatchResult
```

- **Une action par exigence**, dans l'ordre des exigences, jamais moins, jamais plus.
- **Pure** : aucun réseau, aucun LLM, aucune horloge, aucun aléa. Même CV + même
  offre ⇒ même résultat (testé).
- **Entrée** : `CVAnalysisResult` (Mission 01) + dict d'offre. Accepte la sortie
  de `analyze_offer` (Mission 02) telle quelle, ou une offre brute — les
  exigences sont alors extraites avec le même contrat.

### `MatchResult`

| Champ | Sens |
| --- | --- |
| `overall_score` | `matched_requirements / total_requirements` (0.0 si aucune exigence) |
| `matched_requirements` | nombre d'exigences pour lesquelles le CV apporte une preuve |
| `total_requirements` | nombre d'exigences prises en compte |
| `actions` | une `MatchAction` par exigence |
| `missing_critical` | exigences obligatoires sans preuve |
| `warnings` | transversal : contrat, niveau d'études, langues, résumé des trous |

### `MatchAction`

| Champ | Sens |
| --- | --- |
| `code` | `HIGHLIGHT` / `REPHRASE` / `DO_NOT_ADD` / `QUANTIFY` / `CONFIRM_LANGUAGE` |
| `requirement_text` | texte **exact** de l'exigence d'offre |
| `cv_evidence_text` | extrait **exact** du CV (sous-chaîne du texte source) ou `None` |
| `cv_evidence_offset` | position de cet extrait dans le texte source du CV |
| `cv_evidence_field` | `skills` / `experience` / `education` / `languages` / `projects` / `certifications` / `document` |
| `reason` | phrase claire expliquant l'action |
| `confidence` | 0.0–1.0 déterministe |

`MatchEvidence` (interne/public) porte `text`, `offset`, `field`, `confidence`
et `coverage` (part de l'exigence réellement prouvée).

### Règles non négociables et où elles sont vérifiées

| Règle | Test |
| --- | --- |
| Une action par exigence | `test_one_action_per_requirement` |
| Preuve = sous-chaîne **exacte** du CV + offset correct | `test_evidence_provenance_exact`, `test_no_invention`, `test_find_evidence_returns_verbatim_excerpt` |
| `DO_NOT_ADD` strict dès qu'aucune preuve | `test_do_not_add_absent` (raison exacte : « Aucune preuve dans le CV, ne pas ajouter sans preuve. ») |
| `HIGHLIGHT`/`REPHRASE`/`QUANTIFY` toujours pourvus d'une preuve | `test_highlight_exact_match`, `test_rephrase_synonym`, `test_quantify_missing_number` |
| Confiance : exact ≥ 0.9, approximatif 0.6–0.8, `DO_NOT_ADD` = 1.0 | `test_confidence_scoring`, `test_confidence_do_not_add` |
| Avertissement alternance | `test_warning_alternance`, `test_warning_alternance_detected_in_the_description` |
| Avertissement niveau d'études | `test_warning_education_gap`, `test_no_education_warning_when_the_degree_matches` |
| Avertissement langue | `test_language_warning`, `test_language_level_of_another_language_is_not_borrowed` |
| Exigence obligatoire sans preuve ⇒ `missing_critical` | `test_missing_critical`, `test_critical_vs_optional`, `test_modality_preferred_is_never_critical` |
| Fonction pure et déterministe | `test_is_deterministic`, `test_does_not_mutate_its_inputs`, `test_uses_no_network` |

## 3. Comment la décision est prise (déterministe, sans LLM)

1. **Mots-clés** : `extract_keywords()` retire les mots-outils (« de », « the »),
   les mots de capacité (« maîtrise », « expérience », « niveau ») et le
   bruit d'exigence (« obligatoire », « mandatory », « requis »). Un mot-clé
   restant est un terme qui *identifie* une compétence.
2. **Recherche de preuve** : chaque mot-clé est cherché dans le texte source du
   CV, en borders de mots. Un titre de section (« Projets ») ne prouve rien :
   les lignes d'en-tête sont exclues de la recherche.
3. **Synonymes** : groupes déterministes (`gestion` ≡ `management` ≡ `pilotage`,
   `vba` ≡ `macro`, `anglais` ≡ `english`, …). Un match par synonyme existe,
   mais c'est un match plus faible (vocabulaire différent de celui de l'offre).
4. **Décision** :
   - aucune preuve ⇒ `DO_NOT_ADD` (+ `missing_critical` si obligatoire) ;
   - langue sans niveau démontré ⇒ `CONFIRM_LANGUAGE` ;
   - l'exigence demande un volume (`10+`, `5 ans`, `30%`) et l'extrait n'a aucun
     chiffre ⇒ `QUANTIFY` ;
   - preuve complète mais vocabulaire différent, ou preuve partielle ⇒ `REPHRASE` ;
   - preuve complète, même vocabulaire ⇒ `HIGHLIGHT`.
5. **Confiance** : 0.9 (tout trouvé littéralement), 0.6–0.8 (couverture
   partielle), 0.7 (trouvé par synonyme), 1.0 (`DO_NOT_ADD` : aucune preuve,
   c'est certain).

## 4. Exemple réel (CV et offre synthétiques)

```text
score=0.7143  matched=5/7

[HIGHLIGHT] conf=0.9  « Python »
   evidence: '2021-2024 | Développeur Python | TechCorp' (offset=50, field=experience)
[REPHRASE]  conf=0.7  « Gestion de projet »
   evidence: 'Projet open source : librairie de validation (2k+ stars GitHub)' (offset=408, field=projects)
[QUANTIFY]  conf=0.73 « Géré une équipe de 10 personnes »
   evidence: '- Géré équipe de consultants' (offset=92, field=experience)
[DO_NOT_ADD] conf=1.0 « Terraform »
   reason: Aucune preuve dans le CV, ne pas ajouter sans preuve.
[CONFIRM_LANGUAGE] conf=0.9 « Anglais »
   evidence: 'Français (natif), Anglais' (offset=373, field=languages)
[DO_NOT_ADD] conf=1.0 « Espagnol »   (preferred : pas un trou critique)
[HIGHLIGHT] conf=0.9  « Docker »
   evidence: 'Python, SQL, Docker, Kubernetes, Git' (offset=327, field=skills)

missing_critical: ['Terraform']
warnings:
  - Langue mentionnée sans niveau démontré : « Anglais » — à confirmer.
  - Langue requise non prouvée dans le CV : « Espagnol ».
  - 1 exigence(s) obligatoire(s) sans preuve dans le CV.
```

Deux détails qui comptent :

- « Anglais » est bien présent dans le CV, mais **sans niveau** : le niveau
  « natif » appartient au français de la même ligne. Le module ne vole pas le
  niveau d'une autre langue ⇒ `CONFIRM_LANGUAGE`, pas `HIGHLIGHT`.
- « Espagnol » est absent : `DO_NOT_ADD`, et **pas** un trou critique puisque
  l'exigence est `preferred` (Mission 02 : une préférence n'est jamais
  obligatoire).

## 5. Preuves d'exécution

```text
$ .venv/bin/python -m pytest -q tests/test_cv_matching_actions.py
42 passed in 2.54s

$ .venv/bin/python -m pytest -q          # suite complète, base 3a0d1ee
1409 passed, 1 skipped in 225.50s (0:03:45)

$ .venv/bin/python -m ruff check .
All checks passed!

$ git diff --check
(clean)
```

La base `main` @ `3a0d1ee` comptait 1367 tests ; la mission en ajoute 42
(≥ 20 demandés). **Aucune régression.**

## 6. Limites honnêtes

- La détection de la preuve est **lexicale** : « Python » dans « Pythonien »
  n'est pas compté (bords de mots), mais une compétence écrite dans une
  section non détectée reste trouvable, avec le champ `document`.
- La couverture est celle des **mots-clés**, pas une analyse sémantique : une
  exigence formulée avec un vocabulaire entièrement différent de celui du CV
  ressort en `DO_NOT_ADD` — c'est le choix sûr (ne rien inventer), mais c'est
  un faux négatif possible.
- Les synonymes sont une liste fermée et courte ; elle ne couvre pas le jargon
  métier. C'est volontaire : la liste est lisible, testable et amendable.
- Le niveau d'études est **déduit** de la section « Formation » (échelle
  « Bac+X ») ; sans section Formation détectée, aucune comparaison n'est faite
  et aucun avertissement n'est émis.
- `Provenance.source_text` conserve le texte du CV en mémoire. Il s'agit du
  texte déjà extrait pendant l'analyse, pas d'une charge nouvelle.
- La mission ne demandait pas de raccordement UI/route : `career/service.py` et
  `career/router.py` n'ont pas été touchés, le module est prêt à être appelé.

## 7. Rollback

Modifications additives sur une branche dédiée : `git revert` du commit, ou
suppression des fichiers listés au §1. Aucune migration, aucune base, aucun
consommateur existant modifié (le seul changement de comportement existant est
`Provenance.source_text`, un champ **optionnel** qui ne change aucun
comportement existant).
