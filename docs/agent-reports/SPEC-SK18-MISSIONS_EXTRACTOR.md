# SPEC-SK18 — Extracteur de missions complètes (missions, responsabilités, livrables)

Date : 22 octobre 2026
Mission : CVBOOST-43 — SK-18
Branche : `agent/spec-sk18-missions-extractor` (dérivée de `worker/cvboost-43-1792687290`)
Base : `f5b22f2` (worktree dédié `AI-Excel-Agent-worker-cvboost-43-1792687290`)
Aucune dépendance ajoutée, aucun schéma de base modifié, aucune donnée réelle : le corpus de
test est 100 % synthétique.

## 1. Ce qui a été construit

### 1.1 Nouveau module `career/cv_quality/missions_extractor.py` (≈ 1 000 lignes)

Extraction **locale, déterministe, hors-ligne** des sections de missions d'une annonce :
six langues (fr, en, de, it, es, nl), six types de mission, compétences techniques
implicites, et une preuve par mission (extrait verbatim + citation + offsets).

```python
extract_missions(text: str, lang: str = "auto") -> list[MissionFact]
```

`MissionFact` reprend **les neuf champs imposés par la spécification** :
`mission_type`, `text`, `source_field`, `quote`, `start_offset`, `end_offset`, `confidence`,
`contradictions`, `implied_skills`. Un **dixième champ optionnel** `notes: list[str]`
(défaut `[]`) a été ajouté pour tracer les annotations techniques (troncature, déduplication)
sans les mélanger aux contradictions de fond, qui restent réservées aux conflits de type.

API publique du module : `extract_missions`, `classify_mission_type`, `detect_implied_skills`,
`detect_language`, `missions_as_dicts`, `MissionFact`, `MISSION_TYPES`, `SUPPORTED_LANGUAGES`.
Les six sont réexportées par `career/cv_quality/__init__.py`.

### 1.2 Les données de la spécification, reprises à la lettre

- `_MISSION_HEADINGS` : les six listes de titres du cahier des charges, à l'identique
  (« missions », « vos missions », « responsabilités », …, « key responsibilities »,
  « what you'll do », …, « aufgaben », « mansioni », « funciones », « taken »).
- `_OTHER_SECTION_HEADINGS` : les six listes de titres qui **ferment** la section missions
  (« profil », « qualifications », « about us », …). Extensions ajoutées et documentées :
  `profil recherché`, `profil recherche`, `recherchons`, `your profile`, `candidate profile`,
  `who we are`, `il profilo`, `tu perfil`, `jouw profiel`, etc. — sans ces rubriques, une
  annonce « Missions : … / Profil recherché : Bac+5 » aurait laissé le profil ouvert.
- `_MISSION_TYPE_PATTERNS` : les six familles de motifs (kpi, deliverable, team, scope,
  responsibility, défaut `task`), réécrits en formes normalisées (minuscules, sans accents)
  pour que la détection ne dépende pas de l'orthographe exacte de l'offre.
- `_IMPLICIT_SKILL_PATTERNS` : les **14** motifs de compétences (10+ demandés) — Python,
  Excel, VBA, SQL, Power BI, Tableau, Bloomberg, Financial Modeling, Valuation, M&A, LBO,
  Due Diligence, Client Presentation, Project Management.

### 1.3 Corpus synthétique : 29 offres (`tests/fixtures/missions_extractor/synthetic_missions.json`)

Format : `id`, `language`, `title`, `description_original`, `expected[]` avec pour chaque
mission `type`, `text`, `confidence`, `implied_skills`. Les 12 lignes de la table de
validation du cahier des charges sont couvertes **une par une**, plus 17 cas supplémentaires
(puces vides, numérotation, markdown, déduplication, troncature, KPI, périmètre,
responsabilité, section profil, paragraphe entreprise, offre bilingue, deuxième rubrique
missions, offre sans rubrique missions).

## 2. Comment l'extraction fonctionne

1. **Préparation** — le texte est d'abord normalisé (`normalize_offer_text()`) : si la
   description contient du HTML, les balises de bloc deviennent des sauts de ligne, les autres
   balises sont retirées et les entités décodées ; le texte est ensuite tronqué à
   30 000 caractères (les octets nuls sont retirés). **Les offsets et la citation portent sur
   ce texte normalisé**, que `normalize_offer_text()` restitue : chaque preuve reste donc
   résolvable.
2. **Langue** — `detect_language()` compte les marqueurs lexicaux de chaque langue
   (mots outils + vocabulaire métier, 30 marqueurs par langue) ; à égalité, l'ordre
   `fr, en, de, it, es, nl` tranche. En mode `auto`, une rubrique de missions écrite dans
   une autre langue n'est retenue **que si cette autre langue laisse des traces dans
   l'annonce** : le mot isolé « Taken » dans une annonce anglaise n'ouvre donc aucune
   section. En mode explicite (`lang="fr"`), seule la langue demandée est lue.
3. **Titres** — un titre est reconnu s'il apparaît en début de ligne, avec ou sans
   décorations markdown (`## Missions`, `**Missions**`, `- Missions`), suivi ou non de « : ».
   La correspondance est faite sur la suite de mots : « Rôle et missions » et « le profil
   recherché » sont reconnus via leurs mots constituents, le titre le plus long l'emportant.
4. **État de section** — un titre de missions ouvre la lecture, un titre « autre » la ferme,
   une ligne vide la ferme si la ligne suivante ressemble à de la prose (et non à un item de
   mission : une liste d'items séparée par des lignes vides reste ouverte). Un titre inconnu
   (rubrique non cataloguée) la ferme aussi, sauf s'il porte un marqueur de mission — sinon
   « Modélisation financière » serait pris pour une rubrique.
5. **Découpe en items** — puces (`•`, `-`, `▪`), numérotations (`1.`, `b)`) et phrases
   (coupure sur `[.!?]` suivie d'une majuscule ; une phrase commençant par une minuscule
   ou un chiffre est recollée à la précédente). Une puce = une mission ; un paragraphe = une
   mission par phrase.
6. **Nettoyage** — retrait des préfixes (`1.`, `•`), des guillemets, des espaces.
7. **Filtrage** — item vide, puces vides, numéros seuls, item de moins de 4 caractères
   significatifs, item du vocabulaire vague (« selon profil », « to be discussed »,
   « TBD », « à confirmer », « divers », …).
8. **Classification** — un seul motif touché → `explicit` ; aucun motif → `task` avec
   confiance `inferred` ; plusieurs motifs → le type prioritaire est retenu, la confiance
   passe à `ambiguous` et les types concurrents sont listés dans `contradictions ».
9. **Compétences implicites** — les 14 motifs sont appliqués à l'item.
10. **Déduplication** — un item identique (texte normalisé) n'est conservé qu'une fois ; la
    première occurrence garde la trace (« mission dupliquée ») dans `notes`.
11. **Troncature** — un item de plus de 500 caractères est tronqué à 500 et marqué
    `truncated` ; la citation est plafonnée à 400 caractères.
12. **Tri** — les missions sont renvoyées par offset croissant.

## 3. Écarts assumés par rapport au squelette de la spécification

| Écart | Pourquoi |
|-------|----------|
| Seuil de longueur **4 caractères** et non 10 | Le seuil de 10 est incompatible avec la table de validation du cahier des charges elle-même : « Missions : • Modélisation • Reporting • Client » doit produire **3** missions, or « Reporting » (9 caractères) et « Client » (6) seraient supprimés. Le filtrage du « trop vague » est donc porté par une liste noire explicite (`_VAGUE_ITEMS`) plutôt que par la longueur. |
| Motifs de type légèrement étendus | Le squelette contient `presentation` dans les livrables et `clients?`/`accounts?` dans le périmètre. Avec ces motifs, « Lead client presentations » (attendu : `task`) deviendrait un livrable et « Présentation aux clients » deviendrait un périmètre, ce qui contredit la table de validation. `presentation` a donc été **exclu** des livrables et `clients?`/`accounts?` **exclus** du périmètre ; les familles « mod\* » (modèle, modelos, modello, modellering, modeling…) et « report\* » ont été généralisées pour couvrir les six langues. |
| `responsibility` passe **avant** `deliverable` dans la priorité | « Être responsable du reporting mensuel » est une responsabilité, pas un livrable. Le type le plus explicite doit l'emporter ; les deux motifs restent détectés et le conflit est exposé (`ambiguous` + `contradictions`). |
| Champ `notes` ajouté à `MissionFact` | Le contrat de la spécification impose neuf champs : ils sont tous présents, avec les types demandés. La troncature et la déduplication ne sont ni des contradictions de fond ni des compétences : elles passent par `notes` pour ne pas polluer `contradictions`. |
| `summarize_offer()` conserve sa clé `missions` historique | La clé `missions` du résumé contient **les extraits d'exigences** (héritage de `extract_requirements`). La mesure d'exhaustivité (`scripts/measure_exhaustiveness.py`, seuil de non-régression CI à 10,5 %) et le repli d'affichage de `career.js` en dépendent : la remplacer par les seules missions ferait tomber la mesure globale de 10,6 % sous le seuil CI. Les missions réellement annoncées sont donc exposées **en plus** sous `mission_details`, et la clé historique est commentée comme telle. |

## 4. Intégration (additive, sans régression)

| Fichier | Modification |
|---------|--------------|
| `career/offer_qualification.py` | `qualify_offer()` ajoute `provenance["missions"] = FactEvidence([texts…], "missions_extractor", quote)` — c'est l'intégration demandée par le cahier des charges. La valeur porte les extraits verbatim ; la citation est la ligne d'origine. |
| `career/application_prep.py` | `prepare_application()` expose `missions` (liste de dicts : type, texte, citation, offsets, confiance, compétences implicites) ; `summarize_offer()` expose `mission_details` (même structure) **sans** toucher à la clé `missions` historique. |
| `career/cv_fit.py` | Le signal `provenance_match` (choix de variante CV) ne lit plus que les valeurs **scalaires** de la provenance. Sans cette garde, une liste de missions contenant « markets » ferait basculer le score d'une variante de +0,05 pour une simple mention de mot. |
| `career/qualification_persistence.py` | `_bounded_scalar()` sérialise une liste de faits en texte lisible (`\n`) au lieu d'une représentation Python (`['a', 'b']`) dans le snapshot JSON. |

## 5. Validation

```
.venv/bin/python -m pytest -q tests/test_missions_extractor.py   → 147 passed
.venv/bin/python -m pytest -q                                     → 1571 passed, 1 skipped
.venv/bin/python -m ruff check .                                 → All checks passed!
git diff --check                                                  → propre
```

Le test `tests/test_offer_summary_exhaustiveness.py` est **skippé** dans le worktree (pas de
`career_data/career.sqlite3` local) ; la mesure a été rejouée à la main contre la base du
répertoire principal pour vérifier que la livraison n'y fait pas descendre le score
(10,6 % → 10,6 %, seuil 10,5 %).

### 5.1 Ce que couvrent les 147 tests

- **Corpus** : les 29 fixtures sont vérifiées mission par mission (type, texte, confiance,
  compétences implicites), plus la validité des **offsets** (`description[start:end] == text`)
  et le caractère **verbatim** des citations, fixture par fixture.
- **Contrat** : entrées vides/invalides, déterminisme, troncature à 500, filtrage du vague,
  section « profil » jamais lue comme mission, puces vides et numéros seuls, déduplication,
  les six types classifiables, les trois niveaux de confiance, l'exposition des conflits,
  14 compétences implicites, langue explicite restrictive, `missions_as_dicts` JSON-sûr,
  **HTML** (balises de bloc → sauts de ligne, entités décodées, `M&A` intact),
  CRLF et tabulations.
- **Garde-fous du module** : analyse AST du fichier — aucun import réseau
  (`requests`, `urllib`, `httpx`, `socket`, `subprocess`), aucun appel dynamique
  (`eval`, `exec`, `compile`, `__import__`), aucune horloge (`datetime`, `time.time`).
- **Intégration** : `qualify_offer()` cite les missions, le snapshot les persiste en texte
  lisible, `prepare_application()` et `summarize_offer()` les exposent.

### 5.2 Pièges imposés par le cahier des charges — vérification

| Piège | Règle | État |
|-------|-------|-------|
| « Selon profil » / « To be discussed » | filtré (trop vague) | ✅ testé (5 formulations) |
| Section « Profil recherché » | jamais extraite comme mission | ✅ testé (fixture MIS-005/007/008) |
| Puces vides / numéros seuls | filtrés | ✅ testé (fixture MIS-024) |
| Mission > 500 caractères | tronquée à 500, note `truncated` | ✅ testé |
| Compétence implicite détectée | ajoutée dans `implied_skills` | ✅ testé (14 motifs) |
| Doublon de mission | dédupliqué, première occurrence conservée | ✅ testé (fixture MIS-022) |
| Mission répétée dans deux rubriques | une seule mission retenue | ✅ testé (fixture MIS-029) |

## 6. Performance

Une annonce de 3 000 caractères est analysée en **≈ 12 ms**, une annonce de 30 000
caractères en **≈ 80 ms** (Python 3.12, machine de développement). Deux optimisations ont
été nécessaires après profilage : index des titres par premier mot (au lieu d'une recherche
linéaire sur ~130 titres à chaque ligne) et normalisation unique par item (au lieu de trois).

## 7. Limites connues

- L'extraction est **lexicale** : une rubrique missions sans titre reconnu (« Ce que vous
  ferez au quotidien ») n'est pas détectée — c'est le prix de l'absence de modèle.
- Un titre de missions écrit dans une **septième langue** (norvégien, polonais…) n'est pas
  reconnu ; les six langues du cahier des charges le sont.
- Le classement d'un item qui déclenche plusieurs motifs est un **arbitrage documenté**
  (priorité fixe), pas une vérité : le conflit reste visible dans `contradictions` et la
  confiance passe à `ambiguous`.
- La section missions est fermée par une ligne vide suivie de prose : une annonce qui
  enchaîne ses missions sur un paragraphe libre **sans** titre ni liste perd ces lignes
  (choix assumé : mieux vaut manquer que fabriquer des missions).
- Le HTML est **converti** avant extraction : les offsets et la citation portent donc sur le
  texte normalisé (`normalize_offer_text()`), pas sur la chaîne HTML brute. C'est le prix de
  l'indépendance du module vis-à-vis du nettoyage appliqué en amont par les connecteurs.

## 8. Fichiers

Créés :
- `career/cv_quality/missions_extractor.py`
- `tests/test_missions_extractor.py`
- `tests/fixtures/missions_extractor/synthetic_missions.json`
- `docs/agent-reports/SPEC-SK18-MISSIONS_EXTRACTOR.md`

Modifiés :
- `career/cv_quality/__init__.py` (réexport public)
- `career/offer_qualification.py` (preuve `missions`)
- `career/application_prep.py` (`missions`, `mission_details`)
- `career/cv_fit.py` (garde-fou `provenance_match`)
- `career/qualification_persistence.py` (sérialisation des listes)
