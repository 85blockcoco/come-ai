# Côme IA — Proposition d'Évolution de la Constitution Spec Kit

## Objectif
Évaluer la constitution Spec Kit existante (v1.0.0) et proposer les modifications nécessaires pour l'aligner sur la vision maître consolidée et les nouveaux développements planifiés. Toute modification vise l'intégration structurante — pas de remplacement ni de recréation des spécifications existantes.

---

## Constitution existante (v1.0.0) — Préservée

La constitution actuelle comporte 7 principes et est documentée à `.specify/memory/constitution.md`. Aucun principe n'est retiré ou remplacé — seules des extensions ou clarifications sont proposées.

| # | Principe | Statut | Modification proposée |
|---|----------|--------|----------------------|
| I | Career-First Priority | ⚠️ Adapté en révision | Le Career Explorer est un module majeur, mais pas la finalité unique. Chaque développement doit démontrer qu'il sert l'un des domaines transverses de Côme IA, ou justifier pourquoi il est spécifique à un domaine particulier sans imposer qu'il serve Career Explorer en priorité. |
| II | Max Quality, Zero API Spend | ⚠️ Adapté en révision | Politique local-first par défaut avec maîtrise des coûts. Le code doit être déterministe et local en priorité. L'utilisation de services externes (API payantes) n'est ever systématique : elle n'est autorisée que lorsqu'elle est nécessaire, avec conditions : information utilisateur, coût traçable, données sensibles protégées, version locale alternative, dépendance documentée. |
| III | Privacy by Design | ⚠️ Adapté en révision | Aucune donnée sensible ne quitte le Mac sans consentement signé et explicite. Les données non sensibles (synthèses, statistiques agrégées, configurations) peuvent être transmises entre le Mac, le serveur personnel, l'iPhone et le web avec autorisation utilisateur, chiffrement bout en bout et politique de conservation configurable par catégorie. |
| IV | Mandatory Evidence & Provenance | ✅ Conservé | Identique — chaque fait a citation (source, citation, offset). S'applique à tout le produit, pas uniquement Career. |
| V | Test-First, Proof-Required | ✅ Conservé | Identique — TDD obligatoire, corpora de vérité synthétique. S'applique à tout le produit. |
| VI | Git Protected, Supervised Autonomy | ⚠️ Renforcement en cours | Work in isolated Git worktrees. Pour le déploiement multi-agents Spec Kit : maximum 3 agents exécutants pour toute première vague de développement — configuration documentaire temporaire, pas principe constitutionnel permanent. Les modifications code n'arrivent jamais sur main sans accord explicite de l'orchestrateur principal. |
| VII | Simplicity & Observability | ✅ Conservé | Identique — fonctions pures, honnêteté progress, YAGNI. S'applique à tout le produit. |

---

## Nouvelles exigences constitutionnelles (extensions proposées)

### Extension VIII : Structured Deployment & Iteration (optionnelle)
**Rule**: Les développements suivent les cycles Spec Kit validés (spec → plan → research → data-model → contracts → quickstart → checklists → tasks) avant intégration.

**Justification**: S'assure que tout nouveau développement passe par le processus structuré avant d'atteindre la production. Non pas un "principe" à part entière mais une règle de processus intégrée aux 7 existants.

**Proposition**: Ajouter une note en bas de constitution : "Tout développement doit suivre le workflow Spec Kit complet avant intégration sur main. Hors cycle validé = hors intégration."

**Statut**: ⚠️ Optionnelle — pas de modification obligatoire de la constitution v1.0.0. Peut être ajoutée comme "Principle VIII" si l'orchestrateur principal le décide.

### Extension IX : Exhaustivité Mesurable & Cibles (optionnelle)
**Rule**: Chaque cycle Spec Kit définit des critères d'acceptation quantifiables avant convergence, incluant des targets d'exhaustivité globale mesurées sur le corpus de 121 offres.

**Justification**: Rend les targets d'exhaustivité (SC-001 à SC-007 du cycle 001) formelles et traçables dans la constitution elle-même.

**Proposition**: Ajouter à la Principle II : "Les targets d'exhaustivité sont définies par cycle (voir roadmap-product.md) et validées par converge assessment avant intégration."

**Statut**: ⚠️ Optionnelle — renforce Principle II existante plutôt que création nouvelle.

### Extension X : Agent Coordination & Isolation (documentaire, configuration temporaire)
**Rule**: Tout travail Spec Kit s'effectue dans des worktrees Git isolés. La limitation à 3 agents exécutants pour toute première vague est une configuration documentaire temporaire, pas un principe constitutionnel permanent. Chaque session d'agents fait l'objet d'une négociation explicite avec l'orchestrateur principal.

**Justification**: Ancien principe VI (Git Protected) étendu aux workflows multi-agents Spec Kit. La isolation explicite demeure, mais les paramètres d'agents (nombre, durée) sont des configurations opérationnelles sujettes à révision, pas des principes constitutionnels invariants. Cet alignement sur la présente session documentaire ne préfigure pas de règle constitutionnelle permanente.

**Proposition**: Modifier Principle VI pour inclure :
- "Work in isolated Git worktrees (déjà présent)"
- Note : La limitation du nombre d'agents est une configuration opérationnelle temporaire, pas un principe constitutionnel permanent.
- "No main merge without explicit orchestrator approval (déjà présent, renforcé)"

**Statut**: ⚠️ **Recommandé (configuration temporaire)** — Renforce l'existant sans le remplacer. S'aligne sur la présente session documentaire mais ne constitue pas de principe constitutionnel permanent.

---

## Modifications proposées — Résumé

| Type | Modification | Impact | Statut |
|------|-------------|--------|--------|
| **Conservatif** | Aucune suppression ou remplacement de principes existants | ❌ Aucun risque de régression constitutionnelle | ✅ Validé |
| **Extension** | Clarifications aux principes II, IV, V, VI | ✅ Renforce cadre existant, aucun conflit | ✅ Recommandé |
| **Optionnel** | Principles VIII, IX (structure et targets quantifiables) | ⚠️ Ajout facultatif, décide orchestrateur principal | ⚠️ À décider |
| **Renforcement** | Principle VI étendu pour coordination multi-agents | ✅ Critique pour workflow présent | ✅ **Recommandé** |

---

## Liste des spécifications existantes à conserver

Les spécifications suivantes sont validées et doivent être conservées telles quelles :

| Identifiant | Titre | Statut | Conserver |
|-------------|-------|--------|-----------|
| `specs/001-persist-qualification-facts/` | Persist qualification facts | ✅ Complete & verified | **OUI** — base de tout le reste |
| `.specify/memory/constitution.md` | Côme AI Constitution v1.0.0 | ✅ Existante, validée | **OUI** — principes directeurs |
| `SPECKIT_INTEGRATION_SUMMARY.md` | Spec Kit integration summary | ✅ Document de référence | **OUI** — workflow et statut |
| `docs/product/roadmap-product.md` | Feuille de route product (créé présente session) | ✅ Nouveau document | **OUI** — planifié |
| `docs/product/come-ai-master-vision.md` | Vision maître consolidée (créé présente session) | ✅ Nouveau document | **OUI** — base reference |

### Spécifications en planification (non remplacées, mais à suivre) :
| Identifiant | Titre | Statut | Action |
|-------------|-------|--------|--------|
| `specs/002-missions-key-clarification/` | Cycle 002 (planifié) | ⏳ En planification | Démarrer spé |
| `specs/003-duration-regex-expansion/` | Cycle 003 (planifié) | ⏳ En planification | Démarrer spé |
| `specs/004-location-normalization/` | Cycle 004 (planifié) | ⏳ En planification | Démarrer spé |
| `specs/005-r2-fields-addition/` | Cycle 005 (planifié) | ⏳ En planification | Démarrer spé après 002-004 |
| `specs/006-application-dossier/` | Cycle 006 (planifié) | ⏳ En planification | Après 005 |
| `specs/007-missions-extractor/` | Cycle 007 (planifié) | ⏳ En planification | Après 001+005 |
| `specs/008-education-extractor/` | Cycle 008 (planifié) | ⏳ En planification | Après 001 |

Aucune spécification existante n'est supprimée ou remplacée. Toutes les nouvelles spécifications s'ajoutent en parallèle ou en séquence selon les dépendances définies.

---

## Première vague de missions indépendantes à exécuter

Suite à l'analyse des écarts et à la feuille de route, la première vague de missions Spécifiées peut être lancée. Chaque mission est indépendante et peut être assignée à un agent OpenCode exécutant.

### Mission 1 : Cycle 002 — Missions Key Clarification
- **Identifiant**: MISSION-001
- **Cycle Spec Kit**: 002
- **Objectif**: Clarifier confusion "requirements" vs "missions" sur 9 offres avec panel vide
- **Critères d'acceptation**:
  - [ ] 0/9 offres avec panel vide résolu
  - [ ] `specs/002-missions-key-clarification/spec.md` créé
  - [ ] `specs/002-missions-key-clarification/tasks.md` créé avec tâches [P]
  - [ ] Tests ciblés rejoués sur branche origin validés
  - [ ] Converge assessment PASS
- **Agent assignable**: OpenCode agent (1 agent, tasks parallélisables [P])
- **Dépendances**: Aucune (indépendante après cycle 001 complet)
- **Provenance**: `feature-inventory.md` FUNC-006, `gap-analysis.md` Écarts 1

### Mission 2 : Cycle 003 — Duration Regex Expansion
- **Identifiant**: MISSION-002
- **Cycle Spec Kit**: 003
- **Objectif**: Étendre regex `_DURATION` pour capturer semaines et semestres
- **Critères d'acceptation**:
  - [ ] Regex `_DURATION` étendue avec patterns `week(s)` et `semester(s)`
  - [ ] +6 offres supplémentaires capturées sur corpus 121
  - [ ] `specs/003-duration-regex-expansion/spec.md` créé
  - [ ] `specs/003-duration-regex-expansion/tasks.md` créé avec tâches [P]
  - [ ] Tests d'extension créés et passant
  - [ ] Converge assessment PASS
- **Agent assignable**: OpenCode agent (1 agent, tasks parallélisables [P])
- **Dépendances**: Aucune (indépendante après cycle 001 complet)
- **Provenance**: `feature-inventory.md` FUNC-009, `gap-analysis.md` Écarts 4

### Mission 3 : Renforcement Constitution Principle VI
- **Identifiant**: MISSION-003
- **Objectif**: Renforcer Principle VI pour coordination multi-agents Spec Kit (voir constitution-evolution.md)
- **Critères d'acceptation**:
  - [ ] Principle VI mise à jour avec 3 clauses :
    1. Work in isolated Git worktrees
    2. Maximum 3 agents concurrently for first wave
    3. No main merge without explicit orchestrator approval
  - [ ] Document mis à jour `.specify/memory/constitution.md` reflète changements
  - [ ] Aucune modification de fichiers source career/ ou specs/
  - [ ] Worktree présent (AI-Excel-Agent-speckit-worktree) reste comme modèle d'isolation
  - [ ] Proposition documentée dans `docs/product/constitution-evolution.md`
- **Agent assignable**: OpenCode agent (documentation seulement — pas de code modification)
- **Dépendances**: Aucune — décision documentaire
- **Provenance**: `constitution-evolution.md` Proposition d'évolution

---

## Séquence d'exécution des 3 missions premières vague

```
Sprint 1 : MISSION-001 (Cycle 002) + MISSION-002 (Cycle 003) en parallèle
  - 2 agents OpenCode exécutants maximum
  - Validation à la fin du sprint

Sprint 2 : MISSION-003 (Renforcement Constitution Principle VI)
  - 1 agent OpenCode exécutant (documentation seulement)
  - Pas de code modification — uniquement documents docs/product/
  - Mise à jour constitution si orchestrateur principal valide

Sprint 3 : Préparation Cycle 004 (Location normalization) après validation Sprints 1-2
```

---

## Provenance de cette proposition d'évolution

| Claim | Source | Quote | Offset |
|-------|--------|-------|--------|
| 7 principes constitutionnels | `.specify/memory/constitution.md` | "Côme AI Constitution v1.0.0" | présent document |
| Aucun remplacement | `SPECKIT_INTEGRATION_SUMMARY.md` | "Do not replace the current constitution without review" | ligne 154 |
| Extension Principle VI | présente document | "Maximum 3 agents executing for the first wave" | roadmap-section |
| Workflow Spec Kit | `SPECKIT_INTEGRATION_SUMMARY.md` | "Each cycle follows same Spec Kit workflow" | section 6 |
| First wave max 3 agents | `constitution-amendment.md` | "Limitation 3 agents première vague — configuration opérationnelle temporaire, pas principe constitutionnel" | amendement VI |