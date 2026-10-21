# CVBOOST-21 — Matching CV ↔ offre (actions concrètes)

Statut : TERMINÉE (fonction pure, déterministe, hors ligne ; aucune donnée réelle ; aucun envoi).

Branche : `agent/cvboost-21-matching` (branche de mission, désignée par le registre)
Branche de travail : `worker/cvboost-21-1792594831` (worktree de l'orchestrateur)
Base : `main` @ `a054c97` (« test(career): normalize UX guard formatting »)
Worktree : `/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-21-1792594831`

## 1. Ce qui a été construit

| Fichier | Statut | Rôle |
| --- | --- | --- |
| `career/cv_quality/matching.py` | **nouveau** | `match_cv_to_offer(cv_result, offer) -> MatchResult` — une action concrète par exigence, avec provenance exacte |
| `career/cv_quality/models.py` | étendu | `MatchAction`, `MatchEvidence`, `MatchResult`, `MatchActionCode` + `Provenance.source_text` |
| `career/cv_quality/__init__.py` | étendu | exporte `match_cv_to_offer`, `find_evidence_in_cv` et les nouveaux modèles |
| `career/cv_quality/structure.py` | 1 ligne | `Provenance.source_text = text` — le texte source est gardé pour la provenance exacte |
| `tests/test_cv_matching_actions.py` | **nouveau** | 51 tests unitaires (mission : ≥ 20) |
| `docs/agent-reports/CVBOOST-21-MATCHING.md` | **nouveau** | ce rapport |

Interdits respectés : `career/service.py`, `career/router.py`, `career_static/*`,
`requirements*.txt`, aucune migration, `SCHEMA_VERSION` intact.

### Écart assumé avec le squelette de la mission

Le squelette de la mission suppose deux choses qui n'existent pas dans la base :

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
| Avertissement niveau d'études | `test_warning_education_gap`, `test_no_education_warning_when_the_degree_matches`, `test_education_level_takes_the_highest_degree`, `test_education_level_reads_the_specific_diploma` |
| Avertissement langue | `test_language_warning`, `test_language_level_of_another_language_is_not_borrowed`, `test_several_languages_are_never_sold_as_covered`, `test_language_warning_whatever_the_offer_category` |
| Exigence obligatoire sans preuve ⇒ `missing_critical` | `test_missing_critical`, `test_critical_vs_optional`, `test_modality_preferred_is_never_critical` |
| Fonction pure et déterministe | `test_is_deterministic`, `test_does_not_mutate_its_inputs`, `test_uses_no_network` |

## 3. Comment la décision est prise (déterministe, sans LLM)

1. **Mots-clés** : `extract_keywords()` retire les mots-outils (« de », « the »),
   les mots de capacité (« maîtrise », « expérience », « niveau ») et le
   bruit d'exigence (« obligatoire », « mandatory », « requis », «
   Technologies : », « Outils : »). Un mot-clé restant est un terme qui
   *identifie* une compétence.
2. **Recherche de preuve** : chaque mot-clé est cherché dans le texte source du
   CV, en bords de mots. Un titre de section (« Projets ») ne prouve rien :
   les **étiquettes** d'en-tête sont exclues de la recherche — mais seulement
   l'étiquette, pas la ligne (voir §4).
3. **Synonymes** : groupes déterministes (`gestion` ≡ `management` ≡ `pilotage`,
   `vba` ≡ `macro`, `anglais` ≡ `english`, …). Un match par synonyme existe,
   mais c'est un match plus faible (vocabulaire différent de celui de l'offre).
4. **Décision** :
   - aucune preuve ⇒ `DO_NOT_ADD` (+ `missing_critical` si obligatoire) ;
   - langue unique sans niveau démontré ⇒ `CONFIRM_LANGUAGE` ;
   - l'exigence demande un volume (`10+`, `5 ans`, `30%`) et l'extrait n'a aucun
     chiffre prouvable ⇒ `QUANTIFY` ;
   - preuve complète mais vocabulaire différent, ou preuve partielle ⇒ `REPHRASE` ;
   - preuve complète, même vocabulaire ⇒ `HIGHLIGHT`.
5. **Confiance** : 0.9 (tout trouvé littéralement), 0.6–0.8 (couverture
   partielle), 0.7 (trouvé par synonyme), 1.0 (`DO_NOT_ADD` : aucune preuve,
   c'est certain).

Cas particuliers traités explicitement :

- **plusieurs langues dans une même exigence** (« Français et espagnol ») : la
  branche « langue » ne s'applique qu'à une exigence nommant **une** langue ;
  sinon le chemin générique s'applique et l'action dit honnêtement que le CV
  ne prouve qu'une partie (`REPHRASE`), avec un avertissement nommant la
  langue absente ;
- **niveau de langue emprunté à une autre langue** : dans « Français (natif),
  Anglais », le « natif » qualifie le français — l'anglais reste
  `CONFIRM_LANGUAGE`.

## 4. Revue adversariale de la livraison précédente : 7 défauts corrigés

Une campagne précédente de cette mission avait produit une implémentation
complète (2 commits, 43 tests) sur une base `main` plus ancienne (`3a0d1ee`).
Elle a été **rebasée sur le `main` courant** (`a054c97`, cherry-pick propre,
zéro conflit) puis relue à la main, ligne par ligne, contre des CV et des
offres réalistes. Sept défauts réels ont été trouvés et corrigés. Chacun est
couvert par un test de régression qui **échoue** sur l'implémentation
d'origine (vérifié : 7 échecs / 44 succès avant correction, 51 succès après).

| # | Défaut | Effet observé avant correction | Correction |
| --- | --- | --- | --- |
| 1 | Une ligne d'en-tête de section était bloquée **en entier** | CV `COMPETENCES : Python, SQL` ⇒ « Python » rapporté **sans preuve** (`DO_NOT_ADD` + `missing_critical`) alors qu'il est écrit noir sur blanc | `_label_span()` : seule l'**étiquette** (« COMPETENCES ») est bloquée, le contenu qui suit sur la même ligne reste prouvable |
| 2 | Le champ de la preuve suivait la région, pas la ligne | La preuve « Anglais » de `LANGUES : Français, Anglais` était attribuée au champ `skills` | `_label_scopes()` : une ligne qui ouvre sur une étiquette de section annonce son propre champ |
| 3 | Une date comptait comme un chiffre | Exigence « Gestion de projet équipe de 10+ » ⇒ `REPHRASE` au lieu de `QUANTIFY`, car la ligne de preuve (`2020-2023 \| Chef de projet`) contient des années | `_has_figure()` : une date (plage, date complète, année nue) ou un téléphone n'est **jamais** un chiffre prouvable |
| 4 | Le niveau d'études était le **premier** marqueur trouvé, pas le plus élevé | « Bac+2 puis Master » ⇒ Bac+2 ; « Master 1 et Bac+5 » ⇒ Bac+4 ⇒ faux avertissement de niveau | `_education_level()` : le niveau **maximum** Mentionné gagne, et un marqueur spécifique masque le marqueur générique qu'il contient (« licence professionnelle » = Bac+2, « Master 1 » = Bac+4) |
| 5 | Le bruit d'exigence diluait la preuve | « Technologies : Python, Docker » ⇒ `REPHRASE` « le CV ne prouve qu'une partie » alors que les deux compétences sont là | bruit d'introduction ajouté (« technologies », « outils », « environnement », « contexte », « tâches »…) |
| 6 | L'avertissement de langue dépendait de la catégorie de l'offre | Une exigence de langue classée `other` par l'offre ne déclenchait aucun avertissement | l'avertissement est déclenché par le **contenu** de l'exigence, quelle que soit la catégorie |
| 7 | `missing_critical` pouvait contenir des doublons | — | doublons supprimés (ordre conservé) |

En plus, un cas limite a été documenté plutôt que corrigé : un numéro de
téléphone écrit sans « + » (« 06 12 34 56 78 ») n'est pas reconnu comme un
numéro — le distinguer d'un vrai chiffre serait plus fragile que l'inverse.

**Contrôle de non-régression sur le corpus** : les 36 offres synthétiques de la
Mission 02 (`career.offer_requirements.load_fixtures`) ont été passées au
matching avant et après correction, sur deux CV synthétiques (172 exigences au
total) :

- CV à sections classiques (une étiquette par ligne) : **0 différence** ;
- CV à en-têtes sur une ligne (`Compétences : Python, SQL`) : **21 différences,
  toutes des corrections** — « Strong SQL skills are mandatory. »,
  « Python is mandatory. », « SQL requis. », « We require proficiency in SQL and
  Excel. »… passaient de `DO_NOT_ADD` (faux négatif : la compétence est écrite
  noir sur blanc) à `HIGHLIGHT` / `REPHRASE`, et la preuve « Anglais » passe du
  champ `skills` au champ `languages`.

Les corrections ne changent donc le comportement que sur les cas réellement
fautifs.

## 5. Exemple réel (CV et offre synthétiques)

CV : `Jean Dupont` / `Expérience 2021-2024 | Développeur Python | TechCorp` /
`Formation 2016-2018 | Master Informatique` / `Compétences Python, SQL, Docker,
Kubernetes, Git` / `Langues Français (natif), Anglais`.

```text
score=0.7143  matched=5/7

[HIGHLIGHT]      conf=0.9  « Python »
   evidence: '2021-2024 | Développeur Python | TechCorp' (offset=48, field=experience)
[REPHRASE]       conf=0.7  « Gestion de projet »
   evidence: 'Projet open source : librairie de validation (2k+ stars GitHub)' (offset=387, field=projects)
[QUANTIFY]       conf=0.73 « Géré une équipe de 10 personnes »
   evidence: '- Géré équipe de consultants' (offset=90, field=experience)
[DO_NOT_ADD]     conf=1.0 « Terraform »
   reason: Aucune preuve dans le CV, ne pas ajouter sans preuve.
[CONFIRM_LANGUAGE] conf=0.9 « Anglais »
   evidence: 'Français (natif), Anglais' (offset=352, field=languages)
[DO_NOT_ADD]     conf=1.0 « Espagnol »   (preferred : pas un trou critique)
[HIGHLIGHT]      conf=0.9  « Docker »
   evidence: 'Python, SQL, Docker, Kubernetes, Git' (offset=306, field=skills)

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

## 6. Preuves d'exécution

```text
$ .venv/bin/python -m pytest -q tests/test_cv_matching_actions.py
51 passed in 0.99s

$ .venv/bin/python -m pytest -q          # suite complète, base a054c97
1424 passed, 1 skipped in 91.31s (0:01:31)

$ .venv/bin/python -m ruff check .
All checks passed!

$ ./checklist_codex.sh all                # VENV_PY=... MAIN_ROOT=<worktree>
TOUT VERT   (étapes mémoire / study-coach ignorées : worktrees absents)

$ git diff --check
(clean)
```

La base `main` @ `a054c97` comptait 1373 tests hors mission ; la mission en
ajoute 51 (≥ 20 demandés). **Aucune régression.**

Recul supplémentaire : les 36 offres synthétiques de la Mission 02
(`career.offer_requirements.load_fixtures`) ont été passées au matching avec un
CV synthétique — 86 exigences, aucun crash, provenance exacte vérifiée sur
chaque extrait (`source[offset:offset+len(evidence)] == evidence`), résultat
identique à chaque appel.

```text
offers=36 requirements=86
codes: {'DO_NOT_ADD': 60, 'CONFIRM_LANGUAGE': 11, 'HIGHLIGHT': 7, 'REPHRASE': 8}
durée: 154 ms pour 36 offres (1.79 ms/exigence)
```

## 7. Limites honnêtes

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
- Une exigence dont le texte est vide produit une action `DO_NOT_ADD` (le
  contrat « une action par exigence » est respecté à la lettre) ; `analyze_offer`
  (Mission 02) n'émet jamais de texte vide.
- `Provenance.source_text` conserve le texte du CV en mémoire. Il s'agit du
  texte déjà extrait pendant l'analyse, pas d'une charge nouvelle. Il n'est
  **pas** exposé par l'API : `career/router.py` sérialise la provenance
  champ par champ et n'a pas été modifié.
- La mission ne demandait pas de raccordement UI/route : `career/service.py` et
  `career/router.py` n'ont pas été touchés, le module est prêt à être appelé.

## 8. Rollback

Modifications additives sur une branche dédiée : `git revert` du commit, ou
suppression des fichiers listés au §1. Aucune migration, aucune base, aucun
consommateur existant modifié (le seul changement de comportement existant est
`Provenance.source_text`, un champ **optionnel** qui ne change aucun
comportement existant).
