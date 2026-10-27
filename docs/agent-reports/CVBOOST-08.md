# CVBOOST-08 — Banc adversarial de matching CV/offre

- Mission : **CVBOOST-08** (banc adversarial de matching CV/offre, 100+ cas)
- Branche : `agent/cvboost-08-adversarial` (base `bc5db69`)
- Statut : **LIVRÉ** — banc en place, 118 couples synthétiques, 185 tests dédiés,
  41 défauts caractérisés et deux portes de régression versionnées.
- Périmètre : **aucune règle métier modifiée**. Ce lot ajoute uniquement un
  banc d'évaluation, ses fixtures, ses seuils, ses tests et ce rapport.

---

## 1. Ce que le banc mesure

Le banc appelle le **code applicatif réel** sur des couples CV/offre
synthétiques, puis confronte ce qui est produit à une **vérité terrain écrite
à la main** pour chaque cas.

| Couche du produit interrogée | Fonction | Rôle mesuré |
|---|---|---|
| Plan CV | `career.application_prep.prepare_application` | exigences détectées, preuves, couverture, actions |
| Provenance des exigences | `career.offer_requirements.analyze_offer` | exigence, source, locator, modality |
| Pertinence | `career.stage_search.score_brief_match` | composants et score face au brief |
| Accès académique | `career.education_access.assess_education_access` | niveau annoncé par l'offre |
| Admissibilité | `career.offer_qualification.qualify_offer` | contrat, durée, période |

### Les trois axes ne sont jamais mélangés

| Axe | Ce qu'il mesure | Ce qu'il ne dit pas |
|---|---|---|
| **Couverture documentaire** | exigences étayées / exigences détectées | rien sur l'embauche, rien sur l'admissibilité |
| **Admissibilité** | contrat, durée, période face aux critères déclarés | rien sur la pertinence, rien sur le diplôme personnel |
| **Pertinence** | correspondance lexicale avec le brief de recherche | rien sur la couverture, rien sur l'admissibilité |

L'invariant `axis_separation` vérifie que le plan CV ne revendique jamais
l'admissibilité et n'introduit aucun score dans la couverture. Le rapport
signale les **divergences entre axes** sans les arbitrer (par exemple un
contrat conforme alors que le niveau académique annoncé dépasse la
préférence : `CVB08-DIP-004`).

### Provenance des métriques

| Provenance | Cas | Statut | Signification |
|---|---|---|---|
| Simulée (fixtures synthétiques) | 118 | mesuré | couples synthétiques, exécution locale déterministe |
| Application vérifiée | 118 | mesuré | comportement produit par le code applicatif réel |
| Réseau réel | **0** | `not_measured` | aucune source officielle n'est contactée |

---

## 2. Les 118 couples synthétiques

`career/matching_bench/fixtures/cv_offer_pairs.json` (versionné, reproductible :
`python -m career.matching_bench.generate_fixtures --check`).

| Famille adversariale | Cas | Ce qu'elle casse |
|---|---|---|
| `faux_positif_lexical` | 14 | un mot partagé crée un faux lien (Excel / analyse financière, gestion / risques, Power BI / Power Query…) |
| `contrat` | 14 | CDI, CDD court, VIE, alternance exclue, période hors fenêtre, contrat ambigu, niveau senior |
| `diplome` | 12 | M1, M2, Bachelor, Licence, doctorat, niveau non précisé, cumul `et`, alternative `ou` |
| `negation` | 10 | « pas requis », « non requis », « n'est pas exigée », « pas nécessaire », préférence « un plus » |
| `competence_offre_seule` | 10 | compétence exigée par l'offre et absente du profil (SAP, VBA, Bloomberg, Python, Docker, Kubernetes, SPSS, QGIS, Figma, Power BI) |
| `profil_multilingue` | 10 | FR/EN/DE/IT/ES, langue déclarée dans une langue et demandée dans une autre |
| `acronyme` | 10 | CAGR, DA, SEO, UX, PMO, ERP, KPI, ROI, EBITDA, SLA |
| `homonyme` | 10 | audit qualité / audit financier, fournisseurs / clients, assurance / assurances, stage / poste |
| `langue_vs_enseignement` | 8 | langue du programme confondue avec langue exigée, niveau B2 contre « courant » ou C1 |
| `avantages` | 8 | ticket restaurant, mutuelle, véhicule de service, clause « prise en charge » |
| `vide_ou_inconnu` | 8 | profil vide, offre muette, durée et période inconnues |
| `contact` | 4 | coordonnées au profil, coordonnées dans l'offre, coordonnées glissées dans les exigences |

Total : **118 couples**, **144 exigences de référence**, 118 profils portant
des coordonnées synthétiques (`exemple-fake.test`) qui ne doivent jamais être
citées.

Répartition par axe : couverture 86 · admissibilité 24 · pertinence 8.

---

## 3. Validateurs

### Invariants durs (contrat du produit)

| Validateur | Exigence | Violations constatées |
|---|---|---|
| `evidence_verbatim` | toute preuve est une sous-chaîne **exacte** du profil approuvé | 0 |
| `requirement_traceable` | toute exigence du plan est retrouvable dans l'offre (sous-chaîne ou champ sourcé) | 0 |
| `locator_resolves` | chaque exigence de la couche provenance pointe vers un passage résoluble | 0 |
| `negation_handled` | une phrase niée n'est jamais obligatoire dans la couche provenance | 0 |
| `no_contact_leak` | aucune coordonnée (e-mail, téléphone, LinkedIn) dans la surface de décision du plan | **3** |
| `absent_not_added` | ce qui est absent n'est ni ajouté ni présenté comme étayé ; la couverture est cohérente | 0 |
| `unknown_stays_unknown` | une dimension inconnue n'est jamais affirmée | 0 |
| `axis_separation` | le plan ne revendique ni l'admissibilité ni un score de pertinence | 0 |
| `determinism` | deux exécutions sur les mêmes entrées donnent les mêmes octets | 0 |

**1 062 contrôles durs exécutés, 1 059 respectés, 3 violés.**

### Contrôles sémantiques (comparaison à la vérité terrain)

| Validateur | Exigence | Écarts constatés |
|---|---|---|
| `requirement_detection` | les vraies exigences sont détectées, les autres ne le sont pas | **11** |
| `support_decision` | une exigence n'est dite étayée que si la preuve couvre sa partie décisive | **27** |
| `eligibility_verdict` | le verdict d'admissibilité suit les faits de l'offre | 0 |
| `education_verdict` | le niveau académique annoncé est restitué sans le déduire du profil | 0 |
| `relevance_components` | les composants de pertinence suivent le brief | 0 |
| `quoted_material_verbatim` | les fragments cités par le plan viennent des sources, sans invention | 0 |

**708 contrôles sémantiques exécutés, 670 respectés, 38 écarts.**

---

## 4. Résultat mesuré

- **80 / 118** couples sans aucun écart ; **38** couples portent un écart sémantique ;
  **3** portent un défaut dur.
- Déterminisme : **118 / 118** cas produisent une empreinte identique sur deux
  exécutions ; **0** cas instable.

| Famille | Cas | Défauts durs | Écarts | Accord |
|---|---|---|---|---|
| `contrat` | 14 | 0 | 0 | 100 % |
| `vide_ou_inconnu` | 8 | 0 | 0 | 100 % |
| `competence_offre_seule` | 10 | 0 | 1 | 90 % |
| `diplome` | 12 | 0 | 1 | 92 % |
| `contact` | 4 | **3** | 3 | 25 % |
| `acronyme` | 10 | 0 | 6 | 40 % |
| `avantages` | 8 | 0 | 4 | 50 % |
| `negation` | 10 | 0 | 5 | 50 % |
| `profil_multilingue` | 10 | 0 | 5 | 50 % |
| `langue_vs_enseignement` | 8 | 0 | 3 | 62 % |
| `homonyme` | 10 | 0 | 4 | 60 % |
| `faux_positif_lexical` | 14 | 0 | 6 | 57 % |

Axes mesurés séparément : admissibilité **106** admissibles / **7** non
admissibles / **5** indéterminés ; pertinence moyenne **54,5** (min 13, max
91) ; couverture documentaire moyenne **70,3 %** sur 141 exigences détectées.

---

## 5. Défauts caractérisés (41)

### 5.1 Défauts durs — fuites de contact (3)

| Cas | Constat |
|---|---|
| `CVB08-CN-002` | une ligne « Contact : stage@exemple-fake.test » placée sous une section exigences devient une exigence, et son adresse est reprise dans le plan |
| `CVB08-CN-003` | le champ `requirements` structuré peut contenir une coordonnée : elle devient une exigence et une action de plan |
| `CVB08-CN-004` | la coordonnée stockée dans les informations complémentaires du profil est citée comme **preuve** d'une compétence |

Ces trois défauts sont **la ligne de base enregistrée** : ils ne sont pas
corrigés dans ce lot (aucune règle métier modifiée), mais ils sont
verrouillés par les seuils.

### 5.2 Faux positifs de couverture (16)

Le plan annonce une exigence comme couverte alors que la preuve ne porte que
sur un mot partagé :

- `CVB08-FP-001` « Analyse financière avec Excel » couverte par « Excel » ;
- `CVB08-FP-005` « gestion des risques » couverte par « gestion de projet » ;
- `CVB08-FP-007` « comptabilité générale » couverte par « Excel » ;
- `CVB08-FP-008` « Power Query » couverte par « Power BI » ;
- `CVB08-FP-010` « machine learning » couverte par « Python » ;
- `CVB08-FP-013` « Utilisation de R » couverte par « analyse de données » ;
- `CVB08-LG-001` « anglais courant » couvert par un niveau B2 ;
- `CVB08-LG-003` « anglais professionnel » couvert par un niveau B2 ;
- `CVB08-LG-005` « français et anglais » couvert par le seul français ;
- `CVB08-ML-007` « espagnol et anglais » couvert par le seul anglais ;
- `CVB08-ML-009` « anglais C1 » couvert par un B2 ;
- `CVB08-DIP-012` « Master 2 / Bac+5 » couvert par un Master 1 (le chiffre du
  niveau est ignoré) ;
- `CVB08-CO-010` « Reporting sous Power BI » couvert par « reporting » ;
- `CVB08-AC-010` « Gestion de SLA » couverte par « gestion d'incidents » ;
- `CVB08-HO-003` « Audit financier » couvert par « audit qualité » ;
- `CVB08-HO-010` « comptabilité clients » couverte par « comptabilité fournisseurs ».

### 5.3 Exigences non exigentiales détectées comme exigences (11)

- `CVB08-NG-001` « Java n'est pas requis » ;
- `CVB08-NG-002` « L'expérience de SAP n'est pas exigée » ;
- `CVB08-NG-003` « Aucune expérience en gestion n'est requise » ;
- `CVB08-NG-004` « Anglais non requis » ;
- `CVB08-NG-005` « Python n'est pas nécessaire » ;
- `CVB08-NG-008` « Il n'est pas requis de connaître le SQL » ;
- `CVB08-AV-001` clause de mutuelle « une prise en charge est requise » ;
- `CVB08-AV-004` « Ticket restaurant Swile » glissé dans le champ exigences ;
- `CVB08-AV-006` « une prise en charge des repas est requise » ;
- `CVB08-CN-002` / `CVB08-CN-003` lignes de contact.

À noter : la **couche de provenance** (`analyze_offer`, lot CVBOOST-02) traite
correctement ces cas — elle marque la négation (`negated: true`,
`modality: "contextual"`) et saute les sections d'avantages. C'est la couche
**plan CV** (`prepare_application`) qui ne le fait pas. Le banc le mesure au
 lieu de le supposer.

### 5.4 Faux négatifs de couverture (9)

Exigences réellement couvertes par le profil mais non déclarées étayées :

- `CVB08-AV-005` « Fluent in English » (profil « Anglais (C2) ») ;
- `CVB08-ML-005` « Buen conocimiento de Excel » (titre de section espagnol non
  reconnu) ;
- `CVB08-ML-006` « French language required » (profil « Français ») ;
- `CVB08-ML-010` « Sprachkenntnisse in Deutsch » (profil « Allemand ») ;
- `CVB08-AC-003` « Référence SEO », `CVB08-AC-004` « Compétences UX »,
  `CVB08-AC-005` « Expérience PMO », `CVB08-AC-007` « Suivi des KPI »,
  `CVB08-AC-008` « Calcul du ROI » (acronymes de 2 ou 3 lettres hors
  liste blanche) ;
- `CVB08-HO-001` « Stage de 6 mois obligatoire » (le mot « stage » est traité
  comme générique) ;
- `CVB08-HO-004` « Expertise en assurances » (singulier contre pluriel).

### 5.5 Ce qui est conforme

- **Admissibilité** : 14/14 cas de la famille `contrat` (CDI, CDD court, VIE,
  alternance, période hors fenêtre, contrat contradictoire, niveau senior) et
  12/12 cas de la famille `diplome` rendent le verdict attendu, sans jamais
  déduire l'admissibilité personnelle du profil.
- **Inconnus** : durée, période, niveau académique, type de contrat et
  pertinence inconnus restent inconnus (invariant `unknown_stays_unknown` : 0
  violation).
- **Déterminisme** : 118/118.
- **Traçabilité et verbatim** : 0 violation.

---

## 6. Seuils de régression

`career/matching_bench/fixtures/thresholds.json` (versionné).

| Porte | Valeur | Rôle |
|---|---|---|
| `cases_min` | 100 | la suite ne peut pas rétrécir sous 100 couples |
| `hard_failures_max` | 3 | les 3 fuites de contact connues ; **tout nouveau défaut dur échoue** |
| `semantic_failures_max` | 38 | les 38 écarts connus ; **tout nouvel écart échoue** |
| `unstable_cases_max` | 0 | aucun cas non déterministe toléré |
| `oracle_unresolved_max` | 0 | aucune référence de vérité terrain ambiguë ou non résolue |

`python -m career.matching_bench run` sort avec le code 1 dès qu'une porte
est violée. `python -m career.matching_bench compare base.json candidat.json`
liste les régressions (un cas qui passait et échoue), les améliorations (un cas
qui échouait et passe) et tout changement de suite.

La ligne de base est **volontairement datée** : corriger un défaut dans un lot
ultérieur impose de réviser `thresholds.json` à la main, ce qui rend la
correction visible dans l'historique.

---

## 7. Tests

`tests/test_matching_bench_*.py` — **185 tests dédiés** :

| Fichier | Tests | Objet |
|---|---|---|
| `test_matching_bench_fixtures.py` | 17 | intégrité des fixtures : taille, familles, unicité, reproductibilité du JSON, **refus** d'un jeu tronqué, dupliqué, à contact non synthétique ou à famille inconnue |
| `test_matching_bench_validators.py` | 141 | chaque validateur casse volontairement une observation et doit la détecter ; chaque cas passe par tous les validateurs |
| `test_matching_bench_runner.py` | 15 | reproductibilité, séparation des trois provenances, séparation des axes, conformité aux seuils, ligne de base inchangée, classification des défauts connus |
| `test_matching_bench_thresholds.py` | 12 | une porte casse sur un nouveau défaut, une amélioration est signalée, un changement de suite est détecté, schéma de seuils vérifié |

---

## 8. Limites et interdits respectés

- **Aucune règle métier modifiée** : `career/application_prep.py`,
  `career/offer_requirements/*`, `career/stage_search.py`,
  `career/education_access.py`, `career/offer_qualification.py` sont
  inchangés. Le banc est un harnais, pas une correction.
- **100 % synthétique** : le loader refuse tout jeu de fixtures contenant une
  adresse hors domaine réservé ; aucune donnée personnelle, aucun secret.
- **Aucun réseau** : aucun appel sortant dans le banc ; les verdicts
  d'admissibilité sont des tests de chemin de décision sur données
  synthétiques et ne prouvent aucune couverture de source réelle.
- **`main` non modifié** : le travail vit sur la branche
  `agent/cvboost-08-adversarial`.
- Les 41 défauts ci-dessus sont **caractérisés, pas corrigés** : les corriger
  relève d'un lot dédié qui touche aux règles métier.

## 9. Reproduction

```bash
PYTHONPATH=. python -m career.matching_bench run --out .devkit/bench
PYTHONPATH=. python -m pytest -q tests/test_matching_bench_*.py
PYTHONPATH=. python -m career.matching_bench.generate_fixtures --check
```
