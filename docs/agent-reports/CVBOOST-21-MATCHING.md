# CVBOOST-21 — Matching CV ↔ offre : des actions concrètes, prouvées

Statut : TERMINÉE (testé sur fixtures synthétiques ; aucune donnée réelle ; aucun réseau ; aucun LLM).

Base : `main` @ `a054c97` — branche `worker/cvboost-21-1792594985`.

---

## 1. Ce qui a été construit

| Fichier | Rôle |
| --- | --- |
| `career/cv_quality/matching.py` | **Nouveau** — `match_cv_to_offer(cv_result, offer) -> MatchResult`, moteur déterministe de matching |
| `career/cv_quality/models.py` | Étendu — `MatchActionCode`, `MatchEvidence`, `MatchAction`, `MatchResult` + `Provenance.source_text` |
| `career/cv_quality/structure.py` | 1 ligne — `analyze_cv` conserve le texte source exact dans `provenance.source_text` |
| `career/cv_quality/__init__.py` | API publique — export de `match_cv_to_offer` et `find_evidence_in_cv` |
| `tests/test_cv_matching_actions.py` | **Nouveau** — 42 tests unitaires (≥ 20 demandés) |
| `docs/agent-reports/CVBOOST-21-MATCHING.md` | Ce rapport |

Fichiers interdits **intacts** : `career/service.py`, `career/router.py`, `career_static/*`, `requirements*.txt`, migrations, `SCHEMA_VERSION`.

---

## 2. La question à laquelle le module répond

Une seule question par exigence de l'offre :

> **« Quelle modification concrète dois-je faire dans mon CV pour cette exigence ? »**

Chaque réponse est **prouvée** par un extrait *verbatim* du CV (sous-chaîne exacte + offset exact + section) ou **explicitement négative** (« aucune preuve dans le CV, ne pas ajouter sans preuve »). Rien n'est inventé, jamais.

### Les 5 codes d'action (exhaustifs)

| Code | Quand | Ce que l'utilisateur fait |
| --- | --- | --- |
| `HIGHLIGHT` | Le fait existe, écrit comme l'offre le demande | Le rendre plus visible (mot-clé, haut de section, gras) |
| `REPHRASE` | Le fait existe, mais avec un autre vocabulaire | Reformuler avec le vocabulaire exact de l'offre |
| `DO_NOT_ADD` | Aucune preuve dans le CV | **Ne rien ajouter** sans preuve |
| `QUANTIFY` | Le fait existe, sans chiffre | Ajouter un chiffre **prouvable** |
| `CONFIRM_LANGUAGE` | La langue est citée, son niveau n'est pas prouvé | Confirmer le niveau avant de l'affirmer |

### Le contrat de sortie

```python
MatchResult(
    overall_score: float,           # matched_requirements / total_requirements
    matched_requirements: int,      # exigences avec preuve
    total_requirements: int,        # exigences considérées (= len(actions))
    actions: list[MatchAction],     # UNE action par exigence, dans l'ordre de l'offre
    missing_critical: list[str],    # exigences obligatoires sans preuve
    warnings: list[str],            # alternance, niveau d'études, langue non prouvée
)

MatchAction(
    code: MatchActionCode,
    requirement_text: str,          # texte EXACT de l'exigence (offre)
    cv_evidence_text: str | None,   # extrait EXACT du CV (sous-chaîne de la source)
    cv_evidence_offset: int | None, # position de l'extrait dans la source CV
    cv_evidence_field: str | None,  # skills | experience | education | languages | projects | certifications | document
    reason: str,                    # phrase claire, en français
    confidence: float,              # 0.0-1.0, déterministe
)
```

`MatchEvidence` (`text`, `offset`, `field`, `confidence`, `coverage`) est le retour de `find_evidence_in_cv(cv_result, requirement)`.

---

## 3. Les garanties (le cœur de la mission)

1. **Zéro invention.** `cv_evidence_text` est une **sous-chaîne exacte** de la source du CV et `cv_evidence_offset` est sa position exacte — vérifié par construction (`source[offset:offset+len(text)] == text`) et par test. Sans le texte source, **aucune** preuve ne peut être citée : toutes les exigences passent en `DO_NOT_ADD` et un avertissement le dit explicitement. On ne devine pas.
2. **Une action par exigence.** `len(actions) == total_requirements`, l'ordre de l'offre est conservé, et le texte de l'exigence est recopié mot pour mot.
3. **Déterminisme.** Aucun réseau, aucun modèle, aucune horloge, aucun aléa. Deux appels sur le même CV et la même offre rendent un résultat *égal* (`test_matching_is_deterministic`).
4. **Pureté.** Le `CVAnalysisResult` n'est jamais modifié (`test_matching_does_not_mutate_the_cv_result`).
5. **Une exigence niée n'est pas une exigence.** Une ligne marquée `negated` par Mission 02 (« l'anglais n'est pas exigé ») ne produit aucune action et n'entre pas dans le score.

---

## 4. L'algorithme (déterministe, sans réseau)

```
requirements = Mission 02 (records) | liste de chaînes | extraction Mission 02 à la volée
  ↓ pour chaque exigence
keywords  = mots significatifs (mots outils et mots « capacité » retirés)
  ↓
preuve    = 1) la formulation exacte de l'exigence est dans le CV   → confiance 0.95
            2) sinon les mots-clés sont dans le CV (fenêtre ±200 c) → 0.85 / 0.75 / 0.65 / 0.55
  ↓
action    = DO_NOT_ADD (pas de preuve)
          | CONFIRM_LANGUAGE (langue sans niveau prouvé)
          | QUANTIFY (l'exigence porte un chiffre, la preuve n'en porte pas)
          | REPHRASE (preuve trouvée via un synonyme, vocabulaire différent)
          | HIGHLIGHT (preuve directe)
  ↓
score     =matched / total
```

Points de conception qui méritent d'être relus :

- **Le pliage conserve la longueur.** `« maîtrise »` → `« maitrise »` sans changer le nombre de caractères : tous les offsets calculés sur le texte plié sont des offsets de la source. Pas de dérive possible.
- **La preuve est une ligne, pas un mot.** On cite la ligne qui porte le fait (`- Géré une équipe de prestataires`), pas seulement le mot-clé : c'est elle qui dit si la preuve contient un chiffre (`- Géré une équipe de 10 personnes`) — donc c'est elle qui décide `QUANTIFY` vs `HIGHLIGHT`.
- **Le champ est celui du fait, pas celui de la citation.** `cv_evidence_field` est la section du CV qui contient le mot trouvé (`skills`, `experience`, `education`, `languages`, `projects`, `certifications`, sinon `document`).
- **Les synonymes sont un vocabulaire fermé et lisible.** 17 groupes explicites (`gestion`/`management`/`pilotage`, `équipe`/`team`, `anglais`/`english`, …). Un vocabulaire ouvert par un modèle n'aurait pas été déterministe.

---

## 5. Preuves d'exécution (sortie réelle)

### 5.1 Un cas complet

CV synthétique : Python/Kubernetes/Docker/SQL/VBA, Master, « Anglais (courant) », « Géré une équipe de prestataires », « Management de projet international ».
Offre : alternance, niveau `master`, exigences Python / gestion de projet / équipe de 10 / anglais professionnel / Kafka.

```text
score: 0.8 | matched: 4 / 5
missing_critical: ['Kafka']
warnings: ["Alternance détectée — vérifie que ton brief exclut l'alternance."]

  HIGHLIGHT   | Maîtrise de Python                            | conf 0.85 | experience
      preuve: '2020-2023 | Développeur Python | TechCorp'  offset=62
  REPHRASE    | Gestion de projet                             | conf 0.75 | experience
      preuve: '- Management de projet international'       offset=226
  QUANTIFY    | Expérience d'une équipe de 10 personnes min.  | conf 0.65 | experience
      preuve: '- Géré une équipe de prestataires'          offset=192
  HIGHLIGHT   | Anglais professionnel                         | conf 0.85 | languages
      preuve: 'Français (natif), Anglais (courant)'         offset=397
  DO_NOT_ADD  | Kafka                                         | conf 1.0  | None
      conseil: Aucune preuve dans le CV, ne pas ajouter sans preuve.
```

Lecture : 3 advises utiles et prouvées (rendre visible, reformuler, chiffrer), 1 exigence obligatoire sans preuve (`Kafka` → `missing_critical`), 1 alerte de contrat (alternance).

### 5.2 Les deux modes d'entrée

```python
# (1) Contrat Mission 02 — modalité, catégorie et négations respectées
offer = {**offre_brute, "requirements": analyze_offer(offre_brute)["requirements"]}
match_cv_to_offer(cv_result, offer)

# (2) Offre brute — les exigences sont lues telles quelles, aucune n'est perdue
match_cv_to_offer(cv_result, offre_brute)
```

Dans le mode (1), `contract_type` / `education_level` restent disponibles au même niveau → les alertes alternance et niveau d'études se déclenchent. Dans le mode (2), si l'offre n'a pas de champ `requirements`, l'extraction Mission 02 est déclenchée à la volée.

### 5.3 Ce que la mission demandait, test par test

| Test demandé | Test livré | Statut |
| --- | --- | --- |
| `test_highlight_exact_match` | `test_highlight_exact_match` | ✅ |
| `test_rephrase_synonym` | `test_rephrase_synonym` | ✅ |
| `test_quantify_missing_number` | `test_quantify_missing_number` | ✅ |
| `test_do_not_add_absent` | `test_do_not_add_absent` | ✅ |
| `test_missing_critical` | `test_missing_critical` | ✅ |
| `test_warning_alternance` | `test_warning_alternance` | ✅ |
| `test_warning_education_gap` | `test_warning_education_gap` | ✅ |
| `test_multiple_requirements` | `test_multiple_requirements` | ✅ |
| `test_evidence_provenance_exact` | `test_evidence_provenance_exact` | ✅ |
| `test_confidence_scoring` | `test_confidence_scoring` | ✅ |
| `test_no_invention` | `test_no_invention` | ✅ |
| `test_confidence_do_not_add` | `test_confidence_do_not_add` | ✅ |
| `test_critical_vs_optional` | `test_critical_vs_optional` | ✅ |
| `test_language_warning` | `test_language_warning` | ✅ |

+ 28 tests supplémentaires (offset, champ, section, formes d'offre, négation, déterminisme, pureté, codes exhaustifs, score, alerte sans source, niveau d'études, langue multi-langue, …).

---

## 6. Validation

```text
pytest -q tests/test_cv_matching_actions.py   → 42 passed
pytest -q --ignore=tests/test_cv_matching_actions.py (base)  → 1373 passed, 1 skipped
pytest -q (suite complète)                    → 1415 passed, 1 skipped
ruff check .                                   → All checks passed!
git diff --check                               → propre
```

Base de la suite complète avant mission : `1373 passed, 1 skipped`. Après : `1415 passed, 1 skipped` — **aucune régression**, les 42 tests de la mission s'ajoutent et rien ne casse.

---

## 7. Limites connues (à lire avant intégration)

1. **Le texte source doit être disponible.** `analyze_cv` le conserve désormais dans `provenance.source_text` (champ optionnel, `None` par défaut) — un `CVAnalysisResult` fabriqué à la main sans texte ne peut produire aucune preuve : le module le signale plutôt que de deviner. C'est le prix de la garantie « zéro invention ».
2. **Vocabulaire fermé.** 17 groupes de synonymes + les alias de 12 langues. Une formulation exotique (« pilotage de portefeuille ») ne sera pas reconnue comme équivalente à « gestion de projet » : le moteur la classera `DO_NOT_ADD`, ce qui est prudent (aucune preuve affirmée) mais perfectible.
3. **Le score est un ratio, pas une pondération.** `matched / total` ne dit pas qu'une exigence critique vaut dix autres. Le `missing_critical` porte cette information, la pondération reste un choix produit.
4. **Héritage de Mission 02.** Mission 02 ignore les fragments de moins de 4 caractères (« AWS », « SQL » seuls) : une exigence courte peut disparaître en amont, avant d'arriver ici. Le module ne peut pas warned sur ce qui n'est plus là — d'où l'avertissement « exigence obligatoire sans preuve » qui reste, lui, dans le périmètre de la mission.
5. **Le niveau d'études du CV est lu dans la section « Formation »** (à défaut, dans tout le document). Un CV sans section Formation explicite peut être sous-évalué : dans ce cas aucune alerte n'est émise plutôt qu'une fausse alerte.
6. **Une exigence préfixée d'un Accord technique** (« Maîtrise de Python ») est bien reconnue : les mots de capacité (`maitrise`, `experience`, `niveau`, `competence`, `langues`…) sont retirés du calcul des mots-clés.

---

## 8. Intégration proposée

`career/cv_quality` reste un package **autonome** : il n'importe rien de `career.offer_requirements` au chargement (l'appel Mission 02 est fait paresseusement, seulement si l'offre n'a pas d'exigences extraites, et l'échec est silencieux et sans conséquence).

```python
from career.cv_quality import analyze_cv, match_cv_to_offer
from career.offer_requirements import analyze_offer

cv_result = analyze_cv(document)
offer = {**offre, "requirements": analyze_offer(offre)["requirements"]}
match = match_cv_to_offer(cv_result, offer)

for action in match.actions:
    print(action.code, "|", action.requirement_text, "|", action.cv_evidence_text)
```

Aucun changement de schéma, aucune migration, aucun appel réseau : la livraison est réversible en supprimant 4 fichiers.

---

## 9. Note de relecture — livraison parallèle

La même mission a été soumise **deux fois** par le pilote (`cvboost-21-1792594831` et `cvboost-21-1792594985`, branches distinctes, même base `a054c97`). Les deux branches implémentent la même fonction : **n'en intégrer qu'une seule**, au choix du relecteur.
Cette branche est celle du worker `cvboost-21-1792594985` : elle est autonome, ses 42 tests la couvrent, et elle ne dépend d'aucun commit de l'autre livraison.
