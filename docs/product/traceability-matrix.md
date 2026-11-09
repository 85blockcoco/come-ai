# Côme IA — Matrice de Traçabilité Vision → Modules → Spécifications → Chantiers

## Objectif
Établir la correspondance complète entre la vision maître de Côme IA, les modules code existants, les spécifications Spec Kit, et les futurs chantiers de développement. Cette matrice permet de suivre quelles parties de la vision sont déjà implantées, lesquelles font l'objet de chantiers planifiés, et lesquelles restent à définir.

---

## LÉGENDE DES STATUTS

| Symbole | Signification |
|---------|--------------|
| ✅ | Implanté et vérifié |
| ⏳ | Planifié / en cours de définition |
| ⚠️ | Partiel — nécessite consolidation |
| ❌ | Non commencé / absent |

---

## TABLE DE TRAÇABILITÉ

### Niveau 1 — Vision Globale

| Identifiant Vision | Description | Modules Concernés | Statut Actuel | Spécifications | Futurs Chantiers |
|-------------------|-------------|-------------------|---------------|----------------|------------------|
| V1 | Assistant personnel intelligent, compréhension utilisateur | Mémoire, Core, Orchestration | ⏳ En définition | Spec mémoire v1 | Chantier Mémoire Personnelle (Phase 3 globale) |
| V2 | Proactivité 24h/24, moteur autonome | Moteur autonome, Watch, Connect | ⏳ En définition | Spec autonomie v1 | Chantier Intelligence Orchestration (Phase 4 globale) |
| V3 | Multiplateforme synchronisation (Mac/iPhone/web) | Sync, Identity, Connect | ⏳ En définition | Spec synchronisation v1 | Chantier Synchronisation multiplateforme (Phase 6 globale) |
| V4 | Mémoire personnelle profonde, contrôlable | Mémoire, Identity | ⏳ En définition | Spec mémoire structure | Chantier Mémoire transversale (Phase 3) |
| V5 | Architecture hybride auto-hébergée (serveur + distant) | Core, Connect, Identity | ⚠️ Partiel (serveur maison défini, accès distant à définir) | Spec architecture hybride v1 | Affiner modèle serveur (décision architecturale en cours) |
| V6 | Quatre niveaux d'autonomie configurables | Agents, Orchestration, Connect | ⏳ En définition | Spec niveaux autonomie v1 | Implémenter Niveau 3 par catégorie (départ Sprint 7) |
| V7 | Identité commune sur toutes interfaces | Identity, Sync, Memory | ⏳ En définition | Spec identité commune v1 | Harmoniser implémentation sur 3 interfaces |
| V8 | Production documentaire variée (pas seulement carrière) | Studio, Connect, Analyse | ⚠️ Partiel (Excel, PDF existants, autres en cours) | Spec production documentaire v1 | Étendre modèles autres domaines (Phase 7 globale) |

### Niveau 2 — Domaines Fonctionnels

| Identifiant Vision | Description | Modules Concernés | Statut Actuel | Spécifications | Futurs Chantiers |
|-------------------|-------------|-------------------|---------------|----------------|------------------|
| D1 | Organisation et productivité (tous domaines) | Tâches, calendriers, routines | ⏳ En définition | Spec organisation v1 | Consolidation outils existants |
| D2 | Études et apprentissage (transversal) | Cours, mémoire, quiz, recherche | ⏳ En définition | Spec académique v1 | Regrouper outils existants |
| D3 | Carrière et candidatures (module spécialisé) | Offres, CV, lettres, suivi | ⚠️ Partiel (qualification de base OK) | Spec carrière v8 + cycles 001-008 | Cycles Spec Kit 002-008 (voir roadmap carrière) |
| D4 | Mails et communications | Comptes, tri, résumés, réponses | ⚠️ Partiel (connecteurs implantés mais fonctions limitées) | Spec mails v1 | Terminer connecteurs, ajouter fonctions Intelligence |
| D5 | Transport et mobilité | Trajets, SNCF, TGV MAX, urbain | ⚠️ Partiel (connecteurs partiels) | Spec mobilité v1 | Terminer connecteurs, ajouter alertes |
| D6 | Conseiller personnel | Conversations, recommandations, décisions | ⚠️ Partiel (mode conversationnel implanté) | Spec conseiller v1 | Rendre pleinement opérationnel avec mémoire |
| D7 | Création et analyse documentaire | Excel, données, graphiques, présentations | ✅ Partiel (Excel, graphiques OK; PDF, notes en cours) | Spec production v1 | Étendre notes intelligentes, recherche docs |
| D8 | Architecture cible hybride | Core, Memory, Watch, Agents, Connect, Identity, Sync, Studio, Apps | ⚠️ Définie niveau haut, détaillée en cours | Spec architecture hybride v1 | Affiner détaillée (définition serveur en cours) |

### Niveau 3 — Spécifications Techniques

| Identifiant Vision | Description | Composant | Statut Actuel | Spécification | Futur Chantier |
|-------------------|-------------|-----------|---------------|---------------|----------------|
| T1 | Schéma mémoire structuré (10 catégories) | Memory data-model | ⏳ En définition | Spec mémoire structure | Implémenter schéma + outils consultation |
| T2 | Niveaux autonomie 0-3 par catégorie | Autonomy-rules.md | ⏳ En définition | Spécification niveaux autonomie | Implémenter dans orchestration |
| T3 | Règles déclenchement missions | Trigger-rules.md | ⏳ En définition | Spécification règles déclenchement | Intégrer avec mémoire + événements |
| T4 | Politique conservation données par catégorie | Policy-rules.md | ⏳ En définition | Spécification politique conservation | Harmoniser sur toutes interfaces |
| T5 | Schéma identité commune (MP-001 à MP-005) | Identity-sync.md | ⏳ En définition | Spécification identité commune | Implémenter sur Mac/iPhone/web |
| T6 | Architecture serveur personnel + distant | Architecture-hybride.md | ⚠️ Définie haut niveau | Spécification architecture détaillée | Décision technologie serveur en cours |
| T7 | Extractor missions professionnelles | _extract_missions() career/service.py | ❌ Non commencé | Spec extracteur missions | Nouveau cycle Spec Kit 007 |
| T8 | Extractor éducation globale | _extract_education() (hors Career) | ❌ Non commencé | Spec extracteur éducation | Nouveau cycle selon besoins académiques |
| T9 | Regex durée étendue (_DURATION) | career/service.py regex | ⚠️ Incomplet (mois seulement) | Spec regex extension | Correction commune (profitabel aux 2 concepts) |
| T10 | Normalisation localisation | _normalize_location() | ⚠️ Formats mixtes existants | Spec normalisation localisation | Appliquer à toutes sources données |

### Niveau 4 — Chantiers Spéc Kit par Cycle

| Cycle | Intitulé | Vision reliée | Modules | Statut | Dépôts |
|-------|----------|--------------|---------|--------|---------|
| 001 | Persist qualification facts | Vision carrière D3/D1 | Career/service.py | ✅ Terminé | specs/001- |
| 002 | Missions key clarification | Interface Carrière UI | Interface Mac/iPhone | ⏳ Planifié | specs/002- |
| 003 | Expand _DURATION regex | Amélioration commune (Concept A + B) | Regex _DURATION | ⏳ Planifié | specs/003- (commun) |
| 004 | Normalize location | Normalisation globale (tous domaines) | Locales données | ⏳ Planifié | specs/004- (global) |
| 005 | Add R2 fields | Exhaustibilité globale | Career + autres domaines | ⏳ Planifié | specs/005- (après 002-004) |
| 006 | Application dossier | Vision carrière D3 | Career | ⏳ Planifié | specs/006- |
| 007 | Missions extracteur | Concept A (missions professionnelles) | Carrière extracteur | ⏳ Planifié | **Nouveau** specs/007- (Concept A uniquement) |
| 008 | Education extractor | Concept B (académer/conseiller) | Mémoire + académique | ⏳ Planifié | **Nouveau** specs/008- (Concept B domaine) |

### Niveau 5 — Dépendances Inter-domaines

| Dépendance | Source | Cible | Nature | Statut |
|------------|--------|-------|--------|--------|
| Regex durée → Normalisation localisation | Écart 4 (commun) | Écart 3 | Pattern commun profite aux deux | ✅ Déjà commun |
| Regex durée → Extracteur missions Concept A | Écart 4 (commun) | Nouveau cycle 007 | Regex améliorée profitabilise extracteur | ⏳ Dépend Phase 2 globale |
| Extracteur éducation Concept B → R2 champs éducation | Nouvel extracteur | Écart 5 R2 | Dépend d'avoir extracteur éducation | ⏳ Après Phase 3 mémoire |
| R2 champs Career → R2 champs global | Career spécialisé | Roadmap 2 | Dépend si besoin global | ⏳ À évaluer |
| Architecture hybride serveur → Mémoire persistante | Vision V5 | Mémoire structure | Dépendance infrastructure → données | ⏳ Décision serveur en cours |
| Identité commune MP-001 à MP-005 → Synchronisation toutes interfaces | Vision V3 | Sync + Identity | Dépendance traverse tous les domaines | ⏳ Début Phase 6 |

---

## RÈGLES DE TRAÇABILITÉ

1. **Un seul source de vérité** : La vision maître révisée (come-ai-master-vision.md) est la référence unique. Tout écart entre modules et vision est documenté ici.

2. **Pas de retour en arrière** : Les statuts ne descendent jamais de ✅ à ❌ sans nouvelle implémentation. Ils peuvent passer de ⏳ à ✅ après validation.

3. **Chaque module a une ligne** : Même si un module n'a aucune liaison avec la vision actuelle, il a une ligne avec statut ❌ et "Non pertinent — pas de liaison prévue".

4. **Les chantiers sont distincts** : Un même identifiant de chantier peut apparaître dans plusieurs lignes s'il concerne plusieurs modules, mais le descriptif est unique.

5. **Les spécifications font référence** : Chaque entrée "Spécifications" fait référence au document Spec Kit complet (spec.md, plan.md, etc.) pour ce chantier particulier.

6. **Les futurs chantiers sont prévisionnels** : Les entrées "Futurs Chantiers" représentent des intentions documentées, pas des engagements fixes. Elles sont appelées à évoluer.

---

## EXEMPLE DE TRAÇABILITÉ COMPLÈTE

### Exemple : Concept A — Extracteur missions professionnelles

| Composant | Identifiant | Lien avec Vision | Statut | Action |
|-----------|-------------|------------------|--------|--------|
| Code carrière | FUNC-006 | Vision D3 (Carrière) | ❌ Non commencé | Créer `_extract_missions()` |
| Spécification | specs/007-missions-extractor | V7 (missions professionnelles) | ⏳ À créer | Documenter spec.md, plan.md, tasks.md |
| Test | tests/test_mission_extraction_professional.py | V7 + Concept A | ❌ Non créé | Créer jeux de tests sur corpus 121 offres |
| Roadmap | Phase 5 Concept A | V7 + Roadmap 1 Phase 5 | ⏳ Planifié | Planifier dans sprint 9-10 |
| Rapport gap | global-gap-analysis.md Écart 1 | V7 + Écart 1 analysis | ✅ Documenté | Vérifier action ci-dessus |

### Exemple : Concept B — Extracteur éducation globale

| Composant | Identifiant | Lien avec Vision | Statut | Action |
|-----------|-------------|------------------|--------|--------|
| Code mémoire | FUNC-007 (version globale) | Vision D6 (conseiller) + V4 (mémoire) | ❌ Non commencé | Créer `_extract_education()` global |
| Spécification | specs/008-education-extractor | V4 + D6 | ⏳ À créer | Documenter spec.md, plan.md, tasks.md |
| Test | tests/test_education_extraction_global.py | V4 + D6 + mémoire | ❌ Non créé | Créer jeux de tests sur profils utilisateurs |
| Roadmap | Phase 3 mémoire | V4 + Phase 3 globale | ⏳ Planifié | Planifier après infrastructure mémoire |
| Rapport gap | global-gap-analysis.md Écart 2 | V4 + Écart 2 analysis | ✅ Documenté | Vérifier action ci-dessus |

---

## PROVENANCE DE CETTE MATRICE

| Claim | Source | Quote | Offset |
|-------|--------|-------|--------|
| Unique source vérité | présente document | "La vision maître révisée (come-ai-master-vision.md) est la référence unique" | Règle #1 |
| Statuts descendent jamais | présente document | "Les statuts ne descendent jamais de ✅ à ❌ sans nouvelle implémentation" | Règle #2 |
| Chaque module a ligne | présente document | "Même si un module n'a aucune liaison avec la vision actuelle, il a une ligne avec statut ❌" | Règle #3 |
| Chantiers distincts | présente document | "Un même identifiant de chantier peut apparaître dans plusieurs lignes" | Règle #4 |
| Spécifications référence | présente document | "Chaque entrée 'Spécifications' fait référence au document Spec Kit complet" | Règle #5 |
| Futurs chantiers prévisionnels | présente document | "Les entrées 'Futurs Chantiers' représentent des intentions documentées" | Règle #6 |
| Exemple Concept A | présente document | "FUNC-006 + Vision D3 + Écart 1 analysis" | Tableau traçabilité Concept A |
| Exemple Concept B | présente document | "FUNC-007 (globale) + Vision D6 + Écart 2 analysis" | Tableau traçabilité Concept B |