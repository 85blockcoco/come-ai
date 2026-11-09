# Côme IA — Feuille de Route Produit Global (Révisée)

## Objectif
Définir la séquence prioritisée du développement produit Côme IA dans sa globalité, avec une roadmap spécialisée Career conservée séparément. Chaque domaine aura sa propre fenêtre de temps et ses propres priorités, indépendamment de Career.

---

## HIÉRARCHIE DES ROADMAPS

### Roadmap 1 : Côme IA Global (Vue d'ensemble)
**Portée** : Tous les domaines fonctionnels du produit, transverses  
**Objectif** : Consolidation de l'existant, stabilisation, mémoire, intelligence, proactivité, synchronisation, académique, connecteurs, production documentaire, qualité  
**Dépendances** : Aucune dépendance forte entre domaines — chacun a sa fenêtre de temps

### Roadmap 2 : Carrière — Module Spécialisé (CONSERVÉ)
**Portée** : Module Career exclusivement  
**Objectif** : Améliorations Career, extracteurs, exhaustivité carrière  
**Statut** : Conservée telle quelle, réclassée comme domaine spécialisé  
**Dépendances** : Peut évoluer indépendamment des autres domaines

---

## ROADMAP 1 — COME-IA GLOBAL

### Phase 1 : Consolidation de l'existant (Sprint 1-2)
**Objectif** : Vérifier que toutes les fonctionnalités présentes fonctionnent correctement, sont testées et documentées.

| Domaine | Action | Statut ciblé | Dépendances |
|---------|--------|--------------|-------------|
| Interface Mac | Vérification complète, tests de non-régression | ⚠️ À valider — besoins tests ciblés | Aucun |
| Interface iPhone | Vérification interface, tests utilisateur | ⏳ Sprint 1 | Aucun |
| Interface Web | Vérification navigateur, compatibilité | ⏳ Sprint 1 | Aucun |
| Career (qualification) | Validation exhaustivité, tests ciblés | ⏳ Sprint 1-2 | Dépend de base seulement |
| Mémoire personnelle | Inventaire statut, combles identifiés | ⏳ Sprint 2 | Aucun |
| Orchestration/Agents | Vérification niveaux autonomie, état persistant | ⏳ Sprint 2 | Aucun |
| DevKit/Connecteurs | Inventaire connecteurs existants | ⏳ Sprint 2 | Aucun |

**Livrable** : Rapport de consolidation — "Tout ce qui existe fonctionne et est documenté"

### Phase 2 : Stabilisation des interfaces (Sprint 3-4)
**Objectif** : Expérience utilisateur cohérente entre Mac, iPhone et web ; adaptation de l'interface au contexte.

| Action | Domaine ciblé | Dépendances |
|--------|--------------|-------------|
| Harmonisation disposition éléments clés (menu, barre de recherche, profil) | Toutes interfaces | Aucun |
| Adaptation dynamique selon appareil (mobile/desktop) | Toutes interfaces | Aucun |
| Synthèse de conversation identique sur toutes interfaces | Mémoire transvervale | Aucun |
| Notifications adaptées au contexte appareil | Alertes, briefings | Aucun |

**Livrable** : Guide d'harmonisation d'interface — "L'expérience est cohérente, adaptée à chaque appareil"

### Phase 3 : Mémoire Personnelle Avancée (Sprint 5-6)
**Objectif** : Structure transversale mémoire, gestion confiance, accès par catégorie, synchronisation.

| Action | Spécification | Dépendances |
|--------|--------------|-------------|
| Schéma mémoire structuré (10 catégories transversales) | Data-model.md | Aucun |
| Niveau de confiance par information | Quality rules | Aucun |
| Accès sélectif par interface (Mac/iPhone/web) | Interface rules | Aucun |
| Synchronisation mémoire serveur personnel | Sync rules | Aucun |
| Outil consultation/ correction utilisateur | UI patterns | Aucun |

**Livrable** : Memory data-model complet + outils consultation utilisateur

### Phase 4 : Intelligence et Orchestration (Sprint 7-8)
**Objectif** : Moteur autonome, prise de décision, niveaux d'autonomie configurables, logique de déclenchement.

| Action | Spécification | Dépendances |
|--------|--------------|-------------|
| Modèle décisionnel multi-critères | Decision-model.md | Mémoire Phase 3 |
| Niveaux autonomie 0-3 par catégorie | Autonomy-rules.md | Aucun |
| Logique déclenchement missions (horodatées, événements) | Trigger-rules.md | Mémoire Phase 3 |
| Gestion erreurs, interruptions, mode dégradé | Error-rules.md | Aucun |
| Intégration mémoire dans décisions | Integration-rules.md | Mémoire Phase 3 |

**Livrable** : Orchestration complète + règles autonomie documentées

### Phase 5 : Proactivité et Missions Persistantes (Sprint 9-10)
**Objectif** : Détection événements,briefings, missions avec état persistants, annulation/reprise.

| Action | Spécification | Dépendances |
|--------|--------------|-------------|
| Moteur détection événements | Event-engine.md | Intelligence Phase 4 |
| Briefings quotidiens/hebdos automatisés | Briefing-rules.md | Mémoire Phase 3, Orchestration Phase 4 |
| État de mission persistante (serveur maison) | Mission-state.md | Orchestration Phase 4 |
| Annulation/reprise missions | Cancel-rules.md | Orchestration Phase 4 |
| Notifications contextualisées | Notification-rules.md | Intelligence Phase 4 |

**Livrable** : Moteur proactif complet +briefings testés

### Phase 6 : Synchronisation Multiplateforme (Sprint 11-12)
**Objectif** : Identité commune, synchronisation données, gestion conflits, policy conservation par catégorie.

| Action | Spécification | Dépendances |
|--------|--------------|-------------|
| Identité utilisateur commune (MP-001 à MP-005) | Identity-sync.md | Aucun |
| Politique conservation par catégorie | Policy-rules.md | Mémoire Phase 3 |
| Gestion conflits synchronisation | Conflict-rules.md | Orchestration Phase 4 |
| Politique déconnexion/reconnexion | Reconnect-rules.md | Aucun |
| Vue unifiée statut synchronisation | UI-status.md | Aucun |

**Livrable** : Moteur synchronisation complet + politique utilisatrice

### Phase 7 : Académique et Productivité (Sprint 13-14)
**Objectif** : Domaines non-Career consolidés : études, finance, documents, notes.

| Action | Domaines ciblés | Dépendances |
|--------|-----------------|-------------|
| Consolidation outils académiques | Cours, mémoire, quiz, recherche | Mémoire Phase 3 |
| Outils finance et Excel | Analyse, modèles, graphiques | Production doc Phase 7 |
| Notes intelligentes et recherche docs | Mots-clés, provenance | Mémoire Phase 3 |
| Export formats variés | PDF, DOCX, ODT, selon besoin | Production doc |

**Livrable** : Ensemble d'outils académique/productivité consolidé

### Phase 8 : Connecteurs, Transports et Communications (Sprint 15-16)
**Objectif** : Intégrations externes : mails, transports, conseiller personnel, production documentaire externe.

| Action | Intégrations ciblées | Dépendances |
|--------|-------------------|-------------|
| Connecteurs mails (IMAP/Exchange) | Mails, résumés, réponses | Intelligence Phase 4 |
| Recherche trajets (SNCF, TGV MAX, urbain) | Itinéraires, horaires, perturbations | Intelligence Phase 4 |
| Conseiller personnel conversations | Vie quotidienne, décisions, recommandations | Intelligence Phase 4, Mémoire Phase 3 |
| Production documentaire externe | Export, formats, modèles | Production doc Phase 7 |

**Livrable** : Connecteurs externes complets + autorisations explicites

### Phase 9 : Sécurité, Performance et Qualité (Sprint 17-18)
**Objectif** : Surveillance, coût, non-régression, stabilisation finale.

| Action | Domaines | Dépendances |
|--------|----------|-------------|
| Surveillance coûts quotas IA | Services externes, locaux | Connecteurs Phase 8 |
| Mesures performance opérations courantes | Temps réponse, ressources | Toutes phases |
| Tests de non-régression complets | Tous modules | Consolidation Phase 1 |
| Stabilisation finale, "production ready" | Tout le produit | Toutes phases |

**Livrable** : Produit stable, documenté, avec seuils de performance validés.

---

## Ordre d'exécution recommandé (Phase 1 → Phase 9)

```
Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7 → Phase 8 → Phase 9
Sprint 1-2   Sprint 3-4   Sprint 5-6   Sprint 7-8   Sprint 9-10  Sprint 11-12 Sprint 13-14 Sprint 15-16 Sprint 17-18
```

**Note importante** : Les phases peuvent se chevaucher si les équipes sont séparées, mais l'ordre garantit que les fondationsSupportent ce qui suit. Aucune phase ne dépend strictement d'une précédente hormis Phase 1 → Phase 2 (besoin de vérifier l'existant avant de l'harmoniser).

---

## ROADMAP 2 — CARRIÈRE (CONSERVÉE)

### Spécialisation Career — Reclassée

La roadmap Career existante est conservée mais explicitement reclassée comme domaine spécialisé, avec ses propres priorités et fenêtre de temps, indépendante des autres domaines.

| Domaine Career | Priorité | Fenêtre temporelle | Dépendances inter-domaines |
|---------------|----------|-------------------|---------------------------|
| Qualification offres (FUNC-001) | Élevée | Phase 1 (déjà ✅) | Aucune (base) |
| Extracteur missions (FUNC-006) | Moyenne | Phase 4 (après regex + normalisation) | Dépend de regex (Ecart 4) + normalisation (Ecart 3) |
| R2 champs Career (FUNC-010) | Très élevée | Phase 5 (après 002-004) | Dépend cycles Career préliminaires |
| Normalisation localisation Career (FUNC-008) | Moyenne | Phase 3 (après base) | Indépendant |
| Regex durée Career (FUNC-009) | Faible | Phase 2 (commune à tout le produit) | **Correction unique** profite à tout |
| Extracteur éducation Career | Faible | Phase 6 (optionnelle) | Indépendant |

**Ordinary Career workflow** : Cycles Spec Kit 001 → 002 → 003 (commun) → 004 → 005 → 006 → 007 → 008, sans影響er les autres domaines du produit.

**Distinction cruciale** : Les cycles Career n'ont aucune dépendance obligatoire vers les phases de la roadmap globale, et inversement. Seules les améliorations communes (regex, normalisation) profitent aux deux, mais chaque domaine peut évoluer indépendamment.

---

## MATRICE DE TRAÇABILITÉ

| Vision | Module | Écarts | Roadmap Phase | Statut |
|--------|--------|--------|---------------|--------|
| Assistant personnel complet | Interface Mac | Consolidation | Phase 1 | ⚠️ |
| Identité commune multi-plateforme | Synchronisation | Identité MP-001 à MP-005 | Phase 6 | ⏳ |
| Mémoire personnelle transversale | Mémoire Structure | Schéma 10 catégories | Phase 3 | ⏳ |
| Intelligence proactive | Moteur détection | Event-engine.md | Phase 5 | ⏳ |
| Missions autonomes (Concept B) | Orchestration | Modèle missions distinctes | Phase 4+5 | ⏳ |
| Missions professionnelles (Concept A) | Carrière | Extracteur missions | Nouveau cycle 007 | ⏳ |
| Qualité & non-régression | Tous modules | Tests NR complets | Phase 9 | ⏳ |
| Production documentaire variée | Analyse/graphiques | Formats export | Phase 7 | ⚠️ partiel |
| Connecteurs externes | Mails/Transport/Congé | Intégrations externes | Phase 8 | ⏳ |
| Sécurité coût quotas | Services IA | Surveillance, policy | Phase 9 | ⏳ |

**Légende** : ⚠️ = à valider / besoin de preuve ⏳ = en planification / à venir

---

## TABLEAU DES CONTRE-DOCTRINAIRES RÉSOLUS OU RESTANTÀ VÉRIFIER

| Contre-document | Statut | Résolu ? | Action si restant |
|----------------|--------|----------|-------------------|
| Vision Career première version | Obsolète | Oui — remplacée par vision globale révisée | Aucune — documentation historique |
| Analyse des écarts première version (Concept A/B confondus) | Obsolète | Oui — remplacée par analyse globale révisée | Aucune — documentation historique |
| Inventaire fonctionnel Career-only | Obsolète | Oui — remplacé par inventaire global | Aucune — documentation historique |
| Roadmap Carrière-only | Obsolète | Oui — reclassée dans Roadmap 2 | Aucune — conservée telle quelle |
| Constitutions précédentes | Obsolètes | Oui — amendement actuel en vigueur | Aucune — mise à jour en cours |
| Chiffres exhaustivité non sourcés | Vérifié | Oui — chacun a sa baseline | Documenter baseline par domaine |
| Regex durée unique | En cours | Oui — correction commune documentée sur branches distinctes, revue en cours | Intégrer dans Phase 2 (après validation) |
| Séparation Concept A/B | Nouveau | Non — à documenter | Terminer matrice traçabilité |

**Note** : Les contre-document "obsolètes" ne sont pas supprimés — ils sont archivés en référence historique. Le présent document remplace leur contenu décisionnel.

---

## Prochaines actions immédiates (Next 2 sprints)

### Sprint 1 : Validation structurelle
- [ ] Valider la séparation des deux roadmaps (Global + Career)
- [ ] Valider la matrice de traçabilité
- [ ] Valider le tableau des contre-documentaires
- [ ] Commencer Phase 1 Sprint 1 (consolidation existentielle) — vérifier que tout fonctionne

### Sprint 2 : Démarche technique
- [ ] Démarrer Phase 1 action concrète : vérification interface Mac
- [ ] Démarrer Phase 1 action concrète : vérification interface iPhone
- [ ] Démarrer Phase 1 action concrète : vérification interface Web
- [ ] Compiler rapport de consolidation "Tout ce qui existe fonctionne et est documenté"
- [ ] Préparer démarrage Phase 2 (harmonisation interfaces) après rapport de synthèse

---

## Provenance de cette feuille de route

| Claim | Source | Quote | Offset |
|-------|--------|-------|--------|
| Deux roadmaps distinctes | présente document | "Roadmap 1: Côme IA Global... Roadmap 2: Carrière — Module Spécialisé (CONSERVÉ)" | h2 |
| Carrière indépendante | présente document | "Les cycles Career n'ont aucune dépendance obligatoire vers les phases de la roadmap globale" | section Roadmap 2 |
| Pas de dépendance transitive | présente document | "Aucune dépendance transitive : le Concept B n'attend pas le Concept A complet" | analysis des écarts précédente |
| Chaque domaine baseline | présente document | "Chaque domaine fonctionnel a sa propre baseline d'exhaustivité et sa propre cible d'amélioration" | Vérification chiffres |
| Regex correction unique | présente document | "Correction unique — un regex amélioré profite à tout le produit, pas besoin de séparer Concept A/B" | Écart 4 section |
| Pas de nouvelles stats | présente document | "Ne fabrique pas de statistiques, de tests ou de statuts d'intégration" | Objectif final précédente mission |