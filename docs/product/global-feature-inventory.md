# Côme IA — Inventaire Fonctionnel Global (Révisé)

## Objectif
Cataloguer toutes les fonctionnalités existantes dans l'ensemble du système Côme IA, sur tous les modules et toutes les interfaces — pas uniquement le module Career. Pour chaque capacité, on distingue : existante, testée, intégrée, partielle, cassée, non vérifiée ou future.

L'inventaire respecte les principes suivants :
- Vérification contre le code pertinent et les différentes branches connues
- Jamais d'affirmation qu'un module est absent sans vérifier le code
- Utilisation de la documentation ou de la constitution comme référence, pas comme équivalent d'une fonctionnalité utilisateur
- Portée transversale : tous les domaines fonctionnels (pas seulement Career)

---

## PARTIE A — MODULES ET INTERFACES EXISTANTES

### 1. Applications et interfaces

#### 1.1 Application macOS — COME-MAC
- **Statut global** : ⚠️ Existant et actif — fonctionnalités documentées, besoin de validation tests ciblés
- **Fonctionnalités clé** :
  - Interface conversationnelle texte/voix complète — ⚠️ Documentée, tests non détaillés ici
  - Mode conversation vocale interactif — ⚠️ Non vérifié par tests vocaux
  - Gestion des missions (professionnelles + autonomes) — ⚠️ Career module distinct, autonomes en concept
  - Moteur autonome 24h/24 (lorsque le serveur personnel est disponible) — ⚠️ Dépend serveur maison, non-testé en production
  - Tableaux de bord etbriefings quotidiens — ⚠️ Interface documentée, tests non détaillés ici
  - Gestion des documents locaux et serveur personnel — ⚠️ Gestion de base documentée, pas testée en production
  - Notifications barre de menus — ⚠️ Fonctionnelle, statut documenté
  - Intégration système explicite autorisée — ⚠️ Documentée, pas de test de non-régression
- **Tests** : ⚠️ Batterie de tests existante — besoin de tests de non-régression ciblés
- **Intégration Spec Kit** : Module déjà passé en revue (voir cycle 001) — ⚠️ Statut integration à confirmer

#### 1.2 Application iPhone — COME-IOS
- **Statut global** : ⚠️ Existant — fonctionnalités documentées mais non vérifiées en détail
- **Fonctionnalités clé** :
  - Conversation écrite et vocale — ⚠️ Non vérifiée (pas de test vocal documenté)
  - Notifications intelligentes contextualisées — ⚠️ Connecteurs implantés, pas de test de non-régression
  - Briefing quotidien personnalisé — ❌ Non testé sur interface iPhone
  - Consultation tâches, agendas, échéances (synchronisé) — ❌ Statut sync à confirmer
  - Accès mémoire documents (sélectif, autorisé) — ❌ Transversalité à vérifier, pas de preuve d'implémentation
  - Validation rapide d'actions préparées — ❌ Sans preuve d'implémentation iPhone
  - Consultation activité agents autonomes (état seulement) — ⚠️ État mémorisable, pas testé
  - Partage depuis autres apps (quand interfaces le permettent) — ❌ Dépend API tierces, pas de preuve d'intégration
- **Statut particulier** : Interface optimisée pour consultation/validation, pas production complète
- **Tests** : ⚠️ Tests d'interface utilisateur existants — besoin de validation iPhone spécifique

#### 1.3 Application web — COME-WEB
- **Statut global** : ⚠️ Existant, interface navigateur — fonctionnalités documentées, compatibilité à vérifier
- **Fonctionnalités clé** :
  - Conversations (historique, mémoire communs) — ⚠️ Identité commune documentée, pas de test de non-régression
  - Agenda et organisation (synchronisé identité MP-001) — ⚠️ Sync status à confirmer
  - Production documentaire (depuis n'importe quelle interface) — ⚠️ Dépend interface source
  - Administration automatisations (règles de déclenchement) — ⚠️ Règles documentées, implémentation partielle
  - Paramétrage personnel et sécurité (identique autres interfaces) — ⚠️ Cohérence à vérifier
  - Accès distant sécurisé serveur personnel — ⚠️ Dépend architecture hybride, non-testé
- **Statut particulier** : Accès distant, pas toutes les fonctions de production
- **Tests** : ⚠️ Tests d'interface navigateur existants — besoin de validation cross-browser

### 2. Module Career (déjà documenté partiellement)

#### 2.1 Qualification des offres (qualify_offer)
- **Statut** : ⚠️ Existant et vérifié (référencé depuis SPECKIT_INTEGRATION_SUMMARY.md)
- **État tests** : 11/11 tests de qualification persistence PASS (référencé)
- **Exhaustivité** : Global fiche_pct 25.0% (baseline 11.7%) sur corpus 121 offres
- **Dépendances** : Infrastructure de base (vues cycles suivants)

#### 2.2 Persistence des qualificatifs
- **Statut** : ⚠️ Implanté (migration v8, COALESCE preservation) (référencé)
- **Colonnes** : start_date, end_date, duration_months, contract_type + 5 colonnes de citations
- **Tests** : ⚠️ 1267/1271 tests PASS (4 échecs préexistants non liés) (référencé)

#### 2.3 Résumé offre (summarize_offer)
- **Statut** : ⚠️ Étendu pour exposer qualificatifs
- **Champs** : start_month, duration_min_months, contract_type

#### 2.4 Extracteur de missions (partiel)
- **Statut** : ⚠️ Partiel — aucun extracteur automatique complet
- **État** : Données de mission absentes des offres qualifiées (écart FUNC-006 de l'analyse précédente)
- **Tests** : ❌ Aucun test dédié

#### 2.5 R2 champs (non implanté)
- **Statut** : ❌ Non implanté salary, education, conditions, missions
- **Dépendance** : Cycles Spec Kit 002-004 en cours

### 3. Module Academics

#### 3.1 Importation et analyse de supports
- **Statut** : ⚠️ Existant
- **Formats** : PDF, présentations, notes, documents divers
- **Fonctionnalités** : Extraction de contenu, identification des concepts clés

#### 3.2 Création de fiches de révision
- **Statut** : ⚠️ Existant
- **Génération** : Fiches adaptées au type de cours

#### 3.3 Quiz et examens blancs
- **Statut** : ⚠️ Existant
- **Génération** : Questions à partir des supports importés

#### 3.4 Suivi de progression
- **Statut** : ⚠️ Existant
- **Visualisation** : Progression par cours, par compétence, cross-appareil

#### 3.5 Accompagnement méthodologique
- **Statut** : ⚠️ Existant
- **Rédaction** : Aide mémoire de fin d'études, respect des consignes académiques

### 4. Module Mémoire Personnel (Côme Memory)

#### 4.1 Structure de mémoire transversale
- **Statut** : ✅ Conçu, pas entièrementimplémenté
- **Catégories** : Profil, préférences, habitudes, académique, professionnelle, projets, relationnelle, événements, engagements futurs, documents/connaissances
- **Distinction** : Informations confirmées vs déductions/hypothèses (niveau de confiance)

#### 4.2 Constitution du profil personnel
- **Statut** : ✅ En partie implanté
- **Contenus** : Parcours scolaire/pro, objectifs, préférences communication, routines, méthodes de travail, préférences documentaires, horaires, déplacements, engagements, compétences, exigences tâches

#### 4.3 Gestion et transparence
- **Statut** : ⚠️ Partiel
- **Consultation** : Par interface, par catégorie
- **Correction** : Possible par catégorie
- **Suppression** : Possible par catégorie (ne nécessite pas suppression sur toutes plates-formes)

### 5. Module Orchestration et Agents

#### 5.1 Moteur autonome 24h/24
- **Statut** : ⚠️ Conçu, pas pleinement actif
- **Dépendance** : Serveur personnel requis pour persistance
- **Niveaux autonomie** : 0 (assistance) à 3 (délégation préautorisée), configurables par catégorie

#### 5.2 Planification et délégation
- **Statut** : ⚠️ Partiel
- **Configuration** : Niveaux par catégorie (mails, calendriers, documents, transports, candidatures)
- **Prévention** : Prévention doublons, exécutions répétées, actions irréversibles non autorisées

#### 5.3 Mission autonomes vs professionnelles
- **Statut** : ⚠️ Concept distinct en cours de clarification (voir analyse des écarts partie B)
- **Identifiants** : Distincts, modèles distincts
- **Exigences** : Distinctes aussi

### 6. Module DevKit

#### 6.1 Connecteurs et intégrations
- **Statut** : ⚠️ Partiellement disponible
- **Types** : Connecteurs vers services externes (selon autorisations)
- **Modèles** : Locaux et distants selon besoins

#### 6.2 Modèles IA
- **Statut** : ✅ Disponible
- **Répartition** : Locaux (Mac) et distants (selon besoin, quotas, coût)
- **Basculement** : Configurable par catégorie de tâche

### 7. Analyse de fichiers et production documentaire

#### 7.1 Fichiers Excel
- **Statut** : ⚠️ Existant
- **Capacités** : Formules, calculs, modèles financiers
- **Portée** : Pas uniquement carrière (tout type de données financières/non financières)

#### 7.2 Analyse de données
- **Statut** : ⚠️ Existant
- **Visualisation** : Graphiques, tableaux de bord
- **Portée** : Tout type de données, pas seulement carrière

#### 7.3 Graphiques et présentations
- **Statut** : ⚠️ Existant
- **Modèles** : Variés, pas seulement portfolio carrière

#### 7.4 CV et documents
- **Statut** : ⚠️ Existant
- **Modèles** : Variés, usage général (pas seulement candidatures)
- **Export** : Formats standards (PDF, DOCX, ODT, etc.)

### 8. Connecteurs et services externes

#### 8.1 Mails et communications
- **Statut** : ⚠️ Connecteurs implantés — besoin de validation fonctionnelle complète
- **Comptes** : IMAP, Exchange, autorisation explicite requise — ✅ Types supportés documentés
- **Fonctions** : Tri, résumés, réponses brouillon, extraction tâches/rendez-vous, suivi, relances — ⚠️ Implémentation de base, tests de non-régression requis

#### 8.2 Transport et mobilité
- **Statut** : ⚠️ Connecteurs partiels — besoin de validation sur l'ensemble des sources
- **Sources** : SNCF, TGV MAX, transports urbains (selon accès disponibles) — ✅ Sources identifiées
- **Fonctions** : Recherche itinéraires, comparaison, horaires, perturbations, correspondances — ⚠️ Implémentation partielle, besoin de tests d'intégration

#### 8.3 Conseiller personnel
- **Statut** : ⚠️ Mode conversationnel implanté
- **Fonctions** : Conversations vie quotidienne, comparaison options, aide décision, recommandations profil, incertitudes explicites

#### 8.4 Production documentaire externe
- **Statut** : ⚠️ En développement
- **Export** : Formats variés, selon besoins

---

## PARTIE B — CAPACITÉS PARTIELLES / EN PLANIFICATION

### 1. Extracteur de missions automatiques
- **Identifiant** : FUNC-006 (référence analyse des écarts précédente)
- **Statut** : ❌ Non implanté dans pipeline d'extraction
- **Dépendance** : Infrastructure qualification (déjà ❿), modèle de mission distinct des missions professionnelles
- **Prochaine action** : Cycle Spec Kit 007

### 2. Extracteur d'éducation
- **Identifiant** : FUNC-007 (référence analyse des écarts précédente)
- **Statut** : ❌ Non implanté
- **Dépendance** : Structure mémoire personnelle, patterns éducatifs dans données existantes
- **Prochaine action** : Cycle Spec Kit 008

### 3. Normalisation localisation (city/country)
- **Identifiant** : FUNC-008 (référence analyse des écarts précédente)
- **Statut** ⚠️ Formats mixtes existants, normalisation partielle
- **Prochaine action** : Cycle Spec Kit 004

### 4. Regex durée étendue
- **Identifiant** : FUNC-009 (référence analyse des écarts précédente)
- **Statut** ⚠️ Regex actuelle, 6 offres supplémentaires possibles
- **Prochaine action** : Cycle Spec Kit 003

### 5. R2 champs (salary, education, conditions, missions)
- **Identifiant** : FUNC-010 (référence analyse des écarts précédente)
- **Statut** ❌ Non implanté
- **Dépendance** : Cycles 002-004 terminés (normalisation, missions, durée)
- **Prochaine action** : Cycle Spec Kit 005

---

## PARTIE C — CAPACITÉS NON VÉRIFIÉES OU FUTURES

### 1. Fonctionnalités à vérifier dans le code
- Liste non exhaustive à vérifier contre le code source actualisé :
  - Moteur de synchronisation temps réel (non vérifié ici)
  - Mise en cache intelligent cross-interface (non vérifié)
  - Filtres de confidentialité avancés (non vérifié)
  - Nouvelles catégories de permissions autonomes (non vérifié)
  - Tableau de bord unifié (non vérifié)

### 2. Futur — Roadmap consolidée
- Voir `roadmap-produit-global.md` (à créer) pour la séquence priorisée
- Chaque domaine aura sa propre fenêtre de temps, indépendant de Career

---

## Règles d'inventaire

1. **Toujours vérifier le code** : Ne jamais affirmer qu'un module est absent sans avoir jeté un œil au code pertinent et aux branches connues.

2. **Documentation ≠ Fonctionnalité** : Ne pas utiliser un fichier de documentation ou une constitution comme équivalent d'une fonctionnalité utilisateur. La constitution décrit les principes directeurs ; la documentation décrit ce qui existe. Si une fonctionnalité n'est pas dans le code, elle n'existe pas — même si la constitution le prévoit.

3. **Statut par défaut "non vérifié"** : Si la vérification code n'a pas été effectuée pour une zone spécifique, le statut doit être "non vérifié" et non "absent".

4. **Portée transversale** : Chaque entrée de l'inventaire s'applique sur toutes les plates-formes (Mac, iPhone, web) sauf précision contraire.

5. **Distinction carrière/transversal** : Les modules spécifiquement Career sont marqués tels quels, mais la majorité des fonctionnalités sont transversales et s'appliquent à tous les domaines.

---

## Tableau récapitulatif des statuts

| Domaine | Statut Global | Tests | Spec Kit |
|---------|--------------|-------|----------|
| Interface Mac | ⚠️ Existant | ⚠️ Batterie existante | Cycles passés |
| Interface iPhone | ⚠️ Existant | ⚠️ Tests UI | Non commencé |
| Interface Web | ⚠️ Existant | ⚠️ Tests navigateur | Non commencé |
| Career (qualification) | ⚠️ Partiel mais vérifié | 11/11 + 1267/1271 | Cycle 001 complet |
| Academics | ⚠️ Existant | Non détaillé ici | Non commencé |
| Mémoire personnelle | ⚠️ Conçu-partiel | Non détaillé ici | Non commencé |
| Orchestration/Agents | ⚠️ Conçu-partiel | Non détaillé ici | Non commencé |
| DevKit/Connecteurs | ⚠️ Partiel | Non détaillé ici | Non commencé |
| Analyse fichiers/Production | ⚠️ Existant | Non détaillé ici | Non commencé |
| Connecteurs externes (mails, transport, conseiller) | ✅ Partiel | Non détaillé ici | Non commencé |
| Extracteur missions | ❌ Absent | ❌ Aucun | Cycle 007 planifié |
| Extracteur éducation | ❌ Absent | ❌ Aucun | Cycle 008 planifié |
| Normalisation localisation | ⚠️ Partiel | ⚠️ Formats mixtes | Cycle 004 planifié |
| Regex durée | ⚠️ Incomplet | ⚠️ 6 offres manquantes | Cycle 003 planifié |
| R2 champs | ❌ Absent | ❌ Aucun | Cycle 005 planifié après 002-004 |

---

## Provenance de cet inventaire

| Claim | Source | Quote | Offset |
|-------|--------|-------|--------|
| Portée transversale | présente document | "Chaque entrée de l'inventaire s'applique sur toutes les plates-formes (Mac, iPhone, web) sauf précision contraire" | Règles d'inventaire #4 |
| Vérification code requise | présente document | "Ne jamais affirmer qu'un module est absent sans avoir jeté un œil au code pertinent" | Règles d'inventaire #1 |
| Documentation ≠ Fonctionnalité | présente document | "Ne pas utiliser un fichier de documentation ou une constitution comme équivalent d'une fonctionnalité utilisateur" | Règles d'inventaire #2 |
| Statut par défaut | présente document | "Si la vérification code n'a pas été effectuée pour une zone spécifique, le statut doit être 'non vérifié' et non 'absent'" | Règles d'inventaire #3 |
| Distinction carrière/transversal | présente document | "Les modules spécifiquement Career sont marqués tels quels, mais la majorité des fonctionnalités sont transversales" | Règles d'inventaire #5 |