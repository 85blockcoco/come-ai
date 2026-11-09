# Côme IA — Analyse des Écarts Globale (Révisée)

## Objectif
Analyser les écarts à l'échelle de tous les domaines du produit, en séparant impérativement deux notions qui ont été artificiellement confondues :

- **A. Les missions professionnelles extraites des offres d'emploi**
- **B. Les missions autonomes exécutées par Côme IA**

Ces deux concepts doivent avoir des identifiants, des exigences et des modèles distincts. Ne pas relier artificiellement une fonctionnalité d'extraction d'offres à la synchronisation des missions autonomes.

---

## PRÉAMBULE : Séparation des concepts de mission

### Concept A — Missions professionnelles (offres d'emploi)
- **Source** : Extraction depuis les descriptions d'offres d'emploi
- **Contenu** : Missions, objectifs, durées, compétences associated aux postes
- **Module responsable** : Career / qualification des offres
- **Exemple** : "Développer une application web en React pour startup X, 6 mois, à Paris"
- **Identifiant** : FUNC-006 (extractor missions), FUNC-010 (champs R2 missions)
- **Provenance** : Données utilisateur, offres d'emploi, descriptions de postes
- **Stockage** : Table jobs, colonnes de qualification, champs R2
- **Tests** : Tests d'extraction d'offres, non-régression sur corpus 121 offres
- **Non-confondue avec** : Missions autonomes (Concept B)

### Concept B — Missions autonomes (exécutées par Côme IA)
- **Source** : Programmation utilisateur, déclenchements horodatés, règles d'autonomie
- **Contenu** : Tâches récurrentes, briefings, synthèses,actions programmées sans intervention directe
- **Module responsable** : Orchestration / Agents / Moteur autonome
- **Exemple** : "Chaque matin à 9h, synthèse de la journée et briefing" ou "Relancer les candidatures non répondues après 14 jours"
- **Identifiant** : Mission-level dans l'orchestration, Niveaux d'autonomie 0-3
- **Provenance** : Configuration utilisateur, règles définies par l'utilisateur
- **Stockage** : Mémoire personnelle, serveur personnel, état par mission
- **Tests** : Tests de non-régression moteur autonome, scénarios de déclenchement
- **Non-confondue avec** : Missions professionnelles (Concept A)

### Pourquoi la séparation est cruciale
Artificiellement lier l'extraction d'offres professionnelles à la synchronisation des missions autonomes crée :
1. Confusion dans les critères d'acceptation
2. Dépendances inutiles entre modules indépendants
3. Biais dans l'évaluation de l'exhaustitude (chiffres 25%/55% mélangés)
4. Complexité de maintenance accrue
5. Incapacité de déployer l'un sans l'autre

**Solution** : Modèles de données distincts, identifiants distincts, workflows Spec Kit indépendants (sauf points de confluence volontaires).

---

## ÉCART 1 : Extracteur de missions professionnelles (Concept A)

### Description
Aucun extracteur automatique complet de missions professionnelles n'existe dans le pipeline d'extraction des offres. Les données de mission (titres, objectifs, durées, compétences) sont absentes des offres qualifiées.

### Nature de l'écart
- **Fonctionnalité manquante** : Pas d'extractor missions automatique dans career/service.py
- **Données absentes** : Titres de mission, objectifs, durées, compétences non extraites et structurées
- **Contexte** : L'extraction de qualificatifs de base (dates, type contrat, durée en mois) existe (FUNC-001), mais pas l'extractor de missions structurées

### Impact sur la vision globale
- **Concept A (missions professionnelles)** : Incomplet — le suivi des missions professionnelles réduit la pertinence des résultats Carrière uniquement
- **Concept B (missions autonomes)** : Aucun impact direct — Concept B est indépendant des extractions d'offres ; les améliorations de extraction Career ne bénéficient pas automatiquement aux missions autonomes
- **Dépendance** : Doit attendre l'infrastructure qualification (FUNC-001 déjà ✅), mais indépendant des concepts B

### Priorité de correction
**Moyenne pour Concept A** — Importante pour le module Carrière, mais ne doit pas bloquer le Concept B. Les améliorations Career ne se répercutent pas automatiquement sur Concept B.

### Actions recommandées
1. Créer `_extract_missions()` dans `career/service.py` — extraction structurée missions professionnelles
2. Définir schéma de données missions professionnelles (title, objectives, duration, skills, company, level)
3. Mettre à jour `import_job()` pour appliquer l'extraction de missions
4. Créer tests d'extraction missions (tests/test_mission_extraction_professional.py)
5. **Ne pas** relier automatiquement aux missions autonomes (Concept B) — garder modèles distincts. Toute réutilisation transversale doit démontrer des composants et contrats réels.

---

## ÉCART 2 : Extracteur d'éducation (hors Career)

### Description
Le système ne dispose d'aucun mécanisme d'extraction formelle des informations éducatives (diplômes, établissements, dates) depuis les profils utilisateurs ou autres sources que Career.

### Nature de l'écart
- **Fonctionnalité manquante** : Pas d'extractor éducation implémenté hors module Career
- **Données absentes** : Diplômes, établissements, dates formation non extraits automatiquement
- **Contexte** : Les données éducatives existent dans les profils utilisateurs mais ne sont pas extraites de manière systématique

### Impact sur la vision globale
- **Concept A** : Non applicable (hors Career)
- **Concept B** : Important — les données éducatives nourrissent le conseiller personnel, le suivi de progression académique, les recommandations de formation continue
- **Dépendance** : Structure mémoire personnelle (FUNC-007), patterns dans données profil

### Priorité de correction
**Moyenne pour Concept B** — Importante pour les domaines académique et conseiller personnel, indépendante de Career.

### Actions recommandées
1. Créer `_extract_education()` — extraction éducation depuis profils et documents
2. Définir schéma données éducatives (degree, institution, graduation_date, field_of_study, level)
3. Étendre la mémoire personnelle pour catégoriser les informations éducatives
4. Intégrer dans le conseiller personnel (recommandations formation continue)
5. **Reste indépendant** des deux concepts Career/Auto — schéma propre

---

## ÉCART 3 : Normalisation de localisation (global, pas seulement Career)

### Description
Les champs de localisation dans les données existants présentent un format mixte : certaines contiennent ville/pays, d'autres seulement ville ou seulement pays, certaines mentionnent multi-sites. Il n'y a pas de séparation normalisée ville/pays à l'échelle du produit.

### Nature de l'écart
- **Format incohérent** : Champs localisation non normalisés sur l'ensemble du produit
- **Données partielles** : Ville extraite pour certaines offres/profil, pays pour d'autres, aucune pour certaines
- **Portée** : Non seulement Career — aussi mobilité, conseiller personnel, production documentaire

### Impact sur la vision globale
- **Concept A** : Impact sur suivi des missions professionnelles en localisation
- **Concept B** : Impact sur recommandations mobilité, briefings quotidiens, suggestions conseiller personnel
- **Dépendance** : Structure commune, pas spécifique à une source

### Priorité de correction
**Moyenne global** — Importante pour mobilité et conseil, mais les données existantes restent exploitables dans l'état. Peut être traité par étapes indépendamment des concepts Career/Auto.

### Actions recommandées
1. Analyser tous les jeux de données (offres, profils, mémoires) pour classifier formats actuels
2. Définir schéma normalisé (city, country, multi_site_flag, source_origin)
3. Implémenter `_normalize_location()` applicable à toutes les sources
4. Mettre à jour imports et affichage sur toutes interfaces
5. **Indépendant** — pas de liaison forcée vers Concept A ou B

---

## ÉCART 4 : Regex Durée incomplète (global, usages multiples)

### Description
L'expression rationnelle `_DURATION` actuelle ne capture que les durées en mois. Elle manque des patterns semaines/semestres pour de nombreux usages dans le produit (offres Career, mais aussi durées de abonnements, durées de garanties, durées de projets, etc.).

### Nature de l'écart
- **Pattern regex incomplet** : `_DURATION` manque de patterns `week(s)`, `semester(s)`
- **Usages multiples** : Non seulement Career (offres), mais aussi abonnements, garanties, durées projets, calendrier académique
- **Mesurable** : Gain variable selon usage ; pour les 121 offres Career : +6 captures ≈ +5% exhaustivité

### Impact sur la vision globale
- **Concept A** : Impact sur exhaustivité Career (offres de 121)
- **Concept B** : Impact sur durées de abonnements, calendriers académiques, durées projets
- **Dépendance** : Regex commune, correction unique pour tous usages

### Priorité de correction
**Faible pour usages Career, Moyenne global** — C'est une amélioration incrémentale pour Career, mais corrige un pattern incomplet qui affecte plusieurs domaines du produit.

### Actions recommandées
1. Étendre `_DURATION` avec alternance `(months|weeks|semesters?)` et unités de conversion
2. Tester sur l'ensemble des usages connus (offres, abonnements, académique, projets)
3. Valider +6 captures sur corpus 121 offres + gain sur autres domaines
4. **Correction unique** — un regex amélioré profite à tout le produit, pas besoin de séparer Concept A/B

---

## ÉCART 5 : R2 champs étendus (global)

### Description
Les champs étendus R2 (salary, education, conditions, missions) manquent totalement dans les offres qualifiées comme dans d'autres données du produit. Sans ces champs, l'exhaustivité globale ne peut pas dépasser ~25-30%, alors que l'objectif est ≥ 70% sur tous les domaines.

### Nature de l'écart
- **Champs manquants** : salary, education, conditions, missions non extraits et stockés
- **Portée** : Global — pas uniquement Career
- **Dépendance** : Extraction de base (FUNC-001), normalisation (FUNC-004), extracteur missions (FUNC-006), extracteur éducation (FUNC-007)

### Impact sur la vision globale
- **Concept A** : Impact sur exhaustivité Career (25% → 70% cible)
- **Concept B** : Impact sur exhaustivité global (mémoire, conseiller, production documentaire)
- **Dépendance** : Tous les extracteurs partiels doivent être en place d'abord

### Priorité de correction
**Très élevée global** — C'est l'écart numériquement le plus important sur l'ensemble du produit. Fermer cet écart permet d'atteindre l'objectif principal d'exhaustivité ≥ 70% sur tous les domaines, pas seulement Career.

### Actions recommandées
1. Identifier quels champs R2 sont critiques pour chaque domaine
2. **Salary** : Extraire fourchette salaire ou indication "non précisée" depuis descriptions (tous domaines)
3. **Education** : Utiliser extracteur Concept B (voir Écart 2) ou données profil existantes
4. **Conditions** : Extraire type de contrat, temps plein/partiel, télétravail, avantages (tous domaines)
5. **Missions** : Utiliser extracteur Concept A (voir Écart 1) pour Career, Concept B pour autres domaines
6. Implémenter nouvelles colonnes de migration dans `career/service.py` (v9 ou suivante)
7. Mettre à jour `import_job()` pour appliquer l'extraction R2 avec COALESCE preservation
8. Créer jeux de tests R2 globaux (tests/test_qualification_r2_global.py)
9. Vérifier exhaustivité globale passe de 25% → ≥ 70% sur corpus complet, tous domaines

---

## Synthèse des écarts par concept

| Écart | Concept A (missions pro) | Concept B (missions autonomes) | Indépendance |
|-------|-------------------------|-------------------------------|--------------|
| 1 Extracteur missions | ❌ Manquant | ✅ Indépendant (séparé) | Séparé par conception |
| 2 Extracteur éducation | ❌ Non applicable | ❌ Manquant (global) | Indépendant |
| 3 Normalisation localisation | ⚠️ Partiel | ⚠️ Partiel | Indépendant (patterns communs) |
| 4 Regex durée | ⚠️ Incomplet | ⚠️ Incomplet | **Correction unique** profite aux deux |
| 5 R2 champs | ❌ Manquant | ❌ Manquant | **Correction unique** profite aux deux |

---

## Recommandations de séparation des workflows Spec Kit

###Workflow Concept A (missions professionnelles)
1. Cycle 002 : Clarification key missions (ui/ux panel)
2. Cycle 003 : Extension regex durée (common pattern)
3. Cycle 004 : Normalisation localisation (common pattern)
4. Cycle 005 : R2 fields addition (inclut missions pour Career)
5. **Nouveau** : Cycle 007 — Extracteur missions professionnelles (Concept A uniquement)
6. Cycle 006 — Application dossier (Career)
7. Cycle 008 — Extracteur éducation (Concept A + B selon domaines)

###Workflow Concept B (missions autonomes)
1. Architecture hybride serveur maison + distant (déjà en spécification)
2. Niveaux d'autonomie 0-3 configurables par catégorie (déjà en spécification)
3. Mémoire personnelle transversale (déjà en spécification)
4. **Nouveau** : Modèle de missions autonomes avec identifiants distincts
5. Règles de déclenchement, état persistant, annulation (déjà en spécification)
6. Intégration sur interfaces (Mac, iPhone, web)

**Aucune dépendance transitive** : Le Concept B n'attend pas le Concept A complet, et inversement. Seules les corrections regex (Écart 4) profitent aux deux.

---

## Vérification des incohérences de chiffres

### Exhaustivité 25 % / 55 % / 70 %
| Source | Domaine | Pourcentage | Contexte |
|--------|---------|-------------|----------|
| `SPECKIT_INTEGRATION_SUMMARY.md` | Global (tous modules confondus) | 25.0% (baseline 11.7%) | Avant cycles Spec Kit complets |
| Écart analysis précédente | Career seulement | 25% → 55% → 70% | Mélange concepts A et B |
| **Analyse globale révisée** | **Tous modules** | **Variable par domaine** | **Chaque domaine a son propre baseline** |

**Correction** : Chaque domaine fonctionnel a sa propre baseline d'exhaustivité et sa propre cible d'amélioration. L'objectif 70% est une cible globale sommaire, pas un chiffre unique pour tout le produit. Chaque domaine aura sa propre mesure de succès dans la roadmap globale.

### Statuts d'implémentation des extracteurs
| Extracteur | Statut ancien | Statut révisé | Motif |
|-----------|--------------|---------------|--------|
| Extracteur missions | "Absent" | "Manquant (Concept A)" | Séparation Concept A/B justifie reformulation |
| Extracteur éducation | "Non implanté" | "Manquant (global, Concept B domaine)" | Hors Career, domaine académique/conseiller |
| Regex durée | "Incomplet" | "Incomplet (amélioration commune)" | Correction unique profite aux deux concepts |
| Normalisation localisation | "Partiel" | "Partiel (global, pas Career-only)" | Pattern commun, pas spécifique |

---

## Prochaines actions immédiates

### Séparation des concepts (immédiat)
1. **Documenter** la distinction Concept A vs Concept B dans tous les documents (déjà commencé dans cet analyse)
2. **Mettre à jour** les roadmaps pour refléter les workflows séparés
3. **Créer** la matrice de traçabilité entre vision, modules, écarts et futurs chantiers

### Corrections techniques (ordre recommandé)
1. **Écart 4 (Regex durée)** — Correction unique, profite aux deux concepts, gain rapide
2. **Écart 1 (Extracteur missions Concept A)** — Après regex, puis cycles UI/UX
3. **Écart 3 (Normalisation localisation)** — Indépendant, parallèle avec regex
4. **Écart 2 (Extracteur éducation Concept B)** — Indépendant, peut démarrer en parallèle
5. **Écart 5 (R2 champs global)** — Attendre les écarts 1-4, plus grand effort, cible 70% global

### Organisation Spec Kit
1. Créer deux sous-sections dans la roadmap : "Concept A — Missions professionnelles" et "Concept B — Missions autonomes"
2. Documenter les dépendances réelles (pas de dépendances transposes)
3. Prévoir des agents d'exécution distincts ou séquentiels selon les cycles

---

## Provenance de cette analyse globale

| Claim | Source | Quote | Offset |
|-------|--------|-------|--------|
| Séparation Concept A/B | présente document | "Ces deux concepts doivent avoir des identifiants, des exigences et des modèles distincts" | Section préambule |
| Pas de liaison artificielle | présente document | "Ne pas relier artificiellement une fonctionnalité d'extraction d'offres à la synchronisation des missions autonomes" | Section préambule |
| Chiffres 25/55/70 révisés | présente document | "Chaque domaine a sa propre baseline d'exhaustivité" | Vérification chiffres section |
| Regex correction unique | présente document | "Correction unique — un regex amélioré profite à tout le produit" | Écart 4 section |
| R2 champs global | présente document | "C'est l'écart numériquement le plus important sur l'ensemble du produit" | Écart 5 section |
| Workflows séparés | présente document | "Aucune dépendance transitive : le Concept B n'attend pas le Concept A complet" | Recommandations workflows Spec Kit |