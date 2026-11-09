# Côme IA — Analyse des Écarts par rapport à la Vision Maître

## Objectif
Identifier et quantifier les écarts entre l'état actuel du système Côme IA et la vision maître consolidée. Chaque écart est caractérisé par sa nature, son impact sur la vision, sa priorité de correction, et les actions recommandées pour le combler.

---

## ÉCART 1 : Extracteur de missions (FUNC-006)

### Description
Le système ne dispose d'aucun mécanisme d'extraction automatique des informations de mission depuis les offres d'emploi. Les données de mission (titres, objectifs, durées, compétences associées) sont absentes des offres qualifiées.

### Nature de l'écart
- **Fonctionnalité manquante** : Aucune implémentation d'extractor de missions
- **Données absentes** : Titres de mission, objectifs, durées, compétences associées non extraites
- **Dépendance infrastructure** : S'appuie sur l'infrastructure d'extraction qualification existante (FUNC-001)

### Impact sur la vision maître
- **Objectif Carrière et candidatures (15)** : Incomplet — le suivi des candidatures sans données de mission réduit la pertinence des résultats
- **Objectif Conseiller personnel (18)** : Impacts les recommandations de carrière qui nécessitent contexte de mission en cours
- **Objectif Continuité multiplateforme (MP-003)** : Les missions en cours ne sont pas visibles cross-appareil sans données structurées
- **Objectif Moteur autonome (AUT-001/AUT-002)** : Les missions programmées ne peuvent pas se déclencher ou être signalées en échec sans données de mission structurées

### Priorité de correction
**Élevée** — C'est une brique fondamentale pour plusieurs objectifs du produit. Sans données de mission, les cycles ultérieurs (R2 champs, application dossier) ne peuvent pas s'appuyer sur des données de mission complètes.

### Actions recommandées pour combler l'écart
1. **Cycle Spec Kit 007** : Démarrer spécification de l'extractor de missions
   - Identifier les patterns de mission dans les descriptions d'offres existantes
   - Définir le schéma de données de mission (title, objectives, duration, skills)
   - Implémenter `_extract_missions()` dans `career/service.py`
   - Mettre à jour `import_job()` pour appliquer l'extraction de missions
   - Créer tests de non-régression (tests/test_mission_extraction.py)
2. **Dépendance** : Ce cycle doit attendre le Cycle 001 (déjà complet) mais peut parallèle avec Cycle 003 (regex durée)
3. **Prochaine action** : Créer `specs/007-missions-extractor/` et démarrer `spec.md`

---

## ÉCART 2 : Extracteur d'éducation (FUNC-007)

### Description
Le système ne dispose d'aucun mécanisme d'extraction formelle des informations éducatives (diplômes, établissements, dates) depuis les profils utilisateurs ou les offres d'emploi.

### Nature de l'écart
- **Fonctionnalité manquante** : Pas d'extractor éducation implémenté
- **Données absentes** : Diplômes, établissements, dates formation non extraits et mémorisés
- **Contexte** : Les données éducatives existent peut-être dans le profil utilisateur mais ne sont pas extraites automatiquement des offres

### Impact sur la vision maître
- **Objectif Études et apprentissage (14)** : Incomplet — l'accompagnement méthodologique et la rédaction du mémoire nécessitent données éducatives structurées
- **Objectif Conseiller personnel (18)** : Les recommandations de formation continue manquent de base de données
- **Objectif Mémoire personnelle (11/12)** : Catégorie "mémoire académique" incomplète sans extraction automatisée
- **Objectif Production documentaire (19)** : Limité pour génération de documents éducatifs ou de CV mis en valeur

### Priorité de correction
**Moyenne** — Important pour catégories spécifiques mais pas critique pour le fonctionnement de base du produit. Peut être planifié après les priorités élevées.

### Actions recommandées pour combler l'écart
1. **Cycle Spec Kit 008** : Démarrer spécification de l'extractor d'éducation
   - Identifier les patterns éducatifs dans les données existantes (profil, offres)
   - Définir le schéma de données éducatives (degree, institution, graduation_date, field_of_study)
   - Implémenter `_extract_education()` dans `career/service.py`
   - Étendre `summarize_offer()` ou créer `summarize_profile()` pour exposer les données éducatives
   - Créer tests de validation des données éducatives
2. **Dépendance** : Peu dépendant des autres cycles ; peut démarrer indépendamment
3. **Prochaine action** : Créer `specs/008-education-extractor/` et démarrer `spec.md`

---

## ÉCART 3 : Normalisation de localisation (FUNC-008)

### Description
Les champs de localisation dans les offres existants présentent un format mixte : certainescontiennent ville/pays, d'autres seulement ville ou seulement pays, certaines mentionnent multi-sites. Il n'y a pas de séparation normalisée ville/pays.

### Nature de l'écart
- **Format incohérent** : Champs localisation non normalisés
- **Données partielles** : Ville extraite pour certaines offres, pays pour d'autres, aucune pour certaines
- **Technical debt** : Format existant pas conçu pour les requêtes géographiques ultérieures

### Impact sur la vision maître
- **Objectif Mobilité (17)** : Recommandations de trajets et itinéraires incomplètes sans localisation normalisée ville/pays
- **Objectif Conseiller personnel (18)** : Suggestions de localisation basées sur le profil incomplètes
- **Objectif Continuité multiplateforme (MP-005)** : Device-specific capabilities fragmented si localisation non normalisée
- **Objectif Mémoire relationnelle (11)** : Catégorie "engagements futurs" avec localisation floue

### Priorité de correction
**Moyenne** — Importante pour les fonctionnalités mobilité et conseil, mais les données existantes restent exploitable dans l'état actuel. Peut être traité par étapes.

### Actions recommandées pour combler l'écart
1. **Cycle Spec Kit 004** : Démarrer spécification de la normalisation de localisation
   - Analyser les 121 offres existantes pour classifier les formats de localisation actuels
   - Définir le schéma de données normalisé (city, country, multi_site_flag)
   - Implémenter `_normalize_location()` dans `career/service.py`
   - Mettre à jour `import_job()` pour appliquer la normalisation
   - Créer tests de normalisation (tests/test_location_normalization.py)
   - Vérifier exhaustivité avant/après (≥ 95/121 offers pays populated)
2. **Dépendance** : Peut démarrer après Cycle 001 ; indépendant de Cycles 002/003 mais dépend de l'infrastructure qualification (FUNC-001)
3. **Prochaine action** : Créer `specs/004-location-normalization/` et démarrer `spec.md`

---

## ÉCART 4 : Regex Durée incomplète (FUNC-009)

### Description
L'expression rationnelle `_DURATION` actuelle ne capture que les durées en mois. Elle manque 6 offres supplémentaires qui expriment la durée en semaines ou en semestres, ce qui crée un gap d'exhaustivité.

### Nature de l'écart
- **Pattern regex incomplet** : `_DURATION` manque de patterns `week`, `weeks`, `semester`, `semesters`
- **Données manquantes** : 6 offres sur 121 non capturées pour la durée (≈ 5% gap)
- **Mesurable** : Baseline exhaustivité 11.7% → 25.0% avec FUNC-001 ; +1-2% avec cette extension

### Impact sur la vision maître
- **Objectif Durée (13)** : Non respecté dans sa totalité — le principe de suivi de durée de contrat n'est pas pleinement réalisé
- **Objectif Exhaustivité globale (SC-005 du cycle 001)** : Empêche d'atteindre ≥ 70% global fiche_pct sans les 6 offres supplémentaires
- **Objectif R2 champs (FUNC-010)** : Les champs R2 durée ne sont pas peuplés à 100%

### Priorité de correction
**Faible** — C'est une amélioration incrémentale qui augmente légèrement l'exhaustivité sans casser ni rien. Peut être planifié après les priorités critiques.

### Actions recommandées pour combler l'écart
1. **Cycle Spec Kit 003** : Démarrer spécification de l'extension regex Durée
   - Analyser les 6 offres manquantes pour identifier les patterns de durée en semaines/semestres
   - Étendre le regex `_DURATION` avec alternance `(months|weeks|semesters?)` et unités de conversion
   - Tester sur l'ensemble des 121 offres pour valider +6 captures
   - Mettre à jour `qualify_offer()` pour utiliser la nouvelle regex
   - Créer tests d'extension (tests/test_duration_regex_extension.py)
   - Vérifier que l'exhaustivité globale passe de 25% → ~26-27%
2. **Dépendance** : Indépendant ; peut démarrer immédiatement, peut parallèle avec Cycle 002
3. **Prochaine action** : Créer `specs/003-duration-regex-expansion/` et démarrer `spec.md`

---

## ÉCART 5 : R2 champs absents (FUNC-010)

### Description
Les champs étendus R2 (salary, education, conditions, missions) manquent totalement dans les offres qualifiées. Sans ces champs, l'exhaustivité globale ne peut pas dépasser ~25-30%, alors que l'objectif est ≥ 70%.

### Nature de l'écart
- **Champs manquants** : salary, education, conditions, missions non extraits et stockés
- **Dépendance infrastructure** : Dépend de l'extraction de base (FUNC-001), de la normalisation localisation (FUNC-004), et de l'extractor missions (FUNC-006)
- **Tâche importante** : Représente le plus grand gap simple à combler vers l'objectif d'exhaustivité

### Impact sur la vision maître
- **Objectif Exhaustivité globale ≥ 70%** : Impossible sans R2 champs — current 25% vers 70% est le plus grand écart numérique
- **Objectif Carrière et candidatures (15)** : Salary et conditions manquants réduisent la pertinence des recommandations
- **Objectif Conseiller personnel (18)** : Conditions de travail non exploitable pour recommandations
- **Objectif Production documentaire (19)** : Limitations pour génération de documents complets (CV, lettres avec toutes les info)
- **Objectif Mémoire personnelle (11)** : Catégories conditions de travail non mémorisables automatiquement

### Priorité de correction
**Très élevée** — C'est l'écart numériquement le plus important. Fermer cet écart permet d'atteindre l'objectif principal d'exhaustivité ≥ 70%.

### Actions recommandées pour combler l'écart
1. **Cycle Spec Kit 005** : Démarrer spécification des R2 champs
   - Identifier quels champs R2 sont critiques pour l'exhaustivité (≥ 70% target)
   - **Salary** : Extraire fourchette salaire ou indication "non précisée" depuis descriptions
   - **Education** : Utiliser extracteur Cycle 008 (ou données profil existantes)
   - **Conditions** : Extraire type de contrat, temps plein/partiel, télétravail, avantages
   - **Missions** : Utiliser extracteur Cycle 006 (voir écart 1)
   - Implémenter nouvelles colonnes de migration dans `career/service.py` (v9 ou migration suivante)
   - Mettre à jour `import_job()` pour appliquer l'extraction R2 avec COALESCE preservation
   - Créer jeux de tests R2 (tests/test_qualification_r2.py)
   - Vérifier exhaustivité globale passe de 25% → ≥ 70%
2. **Dépendance** : Doit attendre Cycles 002, 003, 004 (normalisation, durée, missions clés)
   - Ordre recommandé : Cycle 002 + 003 en parallèle, puis 004, puis 005
3. **Prochaine action** : Créer `specs/005-r2-fields-addition/` et démarrer `spec.md` après cycles préliminaires

---

## Synthèse des écarts

| Priorité | Identifiant | Écart principal | Effort estimé | Blocage par |
|---|---|---|---|---|
| **Très élevée** | FUNC-010 | R2 champs absents (exhaustivité 25% → 70%) | Important | Cycles 002-004 |
| **Élevée** | FUNC-006 | Extractor missions manquant | Moyen | Aucun (indépendant après 001) |
| **Élevée** | FUNC-001 | Déjà complet ✅ | N/A | — |
| **Moyenne** | FUNC-007 | Extracteur éducation manquant | Moyen | Aucun |
| **Moyenne** | FUNC-008 | Normalisation localisation partielle | Moyen | Aucun |
| **Faible** | FUNC-009 | Regex durée incomplète | Faible | Aucun |

### Chemin critique vers l'objectif ≥ 70% exhaustivité
FUNC-001 (déjà ✅) → FUNC-002 (déjà ✅) → FUNC-003 (déjà ✅) → FUNC-004 (déjà ✅) → FUNC-002/003/004 (Cycles spec kit) → FUNC-010 (R2 champs, cible 70%)

### Recommandations de séquence de cycles Spec Kit
1. **Cycle 002** (missions key clarification) — indépendant, rapide à valider
2. **Cycle 003** (duration regex expansion) — parallèle avec 002, gain modeste
3. **Cycle 004** (location normalization) — moyen effort, prerequisite pour certaines R2 fields
4. **Cycle 005** (R2 fields addition) — très élevé effort, cible 70% exhaustivité, dépend de 002-004
5. **Cycles 006-008** (missions extracteur, education extracteur, miscellaneous) — postérieurs au cycle 005

---

## Prochaines actions immédiates

1. Valider cet analyse des écarts comme base deplanification Spec Kit
2. Démarrer Cycle 002 (missions key) et Cycle 003 (duration regex) en parallèle
3. Planifier Cycle 004 (location normalization) après validation des 2 premiers
4. Planifier Cycle 005 (R2 fields) après validation du Cycle 004
5. Documenter chaque écart avec provenance (source, quote, offset) selon Principle IV

## Provenance de cette analyse

| Claim | Source | Quote | Offset |
|-------|--------|-------|--------|
| État actuel exhaustivité 25% | `SPECKIT_INTEGRATION_SUMMARY.md` | "Global fiche_pct: 25.0% (baseline 11.7%)" | line 68 |
| 121 offres cible | `cahier_charges_master.md` | "Country ≥ 95/121 offers" | Partie IV, exigence |
| 6 offres durée manquantes | `SPECKIT_INTEGRATION_SUMMARY.md` | "Capture 6 more offers" | roadmap, Cycle 003 |
| Objectif 70% exhaustivité | `SPECKIT_INTEGRATION_SUMMARY.md` | "Exhaustivity ≥ 70%" | roadmap, Cycle 005 |
| Constitution 7 principes | `SPECKIT_INTEGRATION_SUMMARY.md` | Table principles | lines 15-23 |