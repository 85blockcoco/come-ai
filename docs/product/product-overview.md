# Côme AI — Aperçu Produit (Révisé)

## Vision
Côme IA est un assistant personnel intelligent, proactif, multimodal, multiplateforme et hautement autonome, capable de centraliser et d'automatiser la majorité des activités numériques quotidiennes de son utilisateur. Career Explorer est un module important, mais pas la finalité unique du produit.

## Core Principles (Côme AI Constitution v1.0.0 amendée)
| # | Principle | Key Rule |
|---|-----------|----------|
| I | Career-First Priority (adapté) | Le Career Explorer est un module majeur, mais pas la finalité unique. Chaque développement doit démontrer qu'il sert l'un des domaines transverses de Côme IA, ou justifier pourquoi il est spécifique à un domaine particulier sans imposer qu'il serve Career Explorer en priorité. |
| II | Max Quality, Zero API Spend (adapté) | Exigence de qualité maximale avec maîtrise des coûts. Le code doit être déterministe et local dans la mesure du possible. L'utilisation de services externes (API payantes) est autorisée lorsqu'elle est nécessaire, avec conditions : information utilisateur, coût traçable, données sensibles protégées, version locale alternative, dépendance documentée. |
| III | Privacy by Design (clarifié) | Aucune donnée sensible ne quitte le Mac sans consentement signé et explicite. Les données non sensibles (synthèses, statistiques agrégées, configurations) peuvent être transmises entre le Mac, le serveur personnel, l'iPhone et le web avec autorisation utilisateur, chiffrement bout en bout et politique de conservation configurable par catégorie. |
| IV | Mandatory Evidence & Provenance | Identique — chaque fait a citation (source, citation, offset). S'applique à tout le produit, pas uniquement Career. |
| V | Test-First, Proof-Required | Identique — TDD obligatoire, corpora de vérité synthétique. S'applique à tout le produit. |
| VI | Git Protected, Supervised Autonomy (renforcé) | Work in isolated Git worktrees. Pour le déploiement multi-agents Spec Kit : maximum 3 agents exécutants pour toute première vague. Les modifications code n'arrivent jamais sur main sans accord explicite de l'orchestrateur principal. |
| VII | Simplicity & Observability | Identique — fonctions pures, honnêteté progress, YAGNI. S'applique à tout le produit. |

## Product Scope (portée globale)
- **Career Explorer** : Module spécialisé d'analyse d'offres et de parcours carrière (non exclusif)
- **Offer Intelligence** : Extraction et qualification de faits d'offres (dates, type contrat, durée, compétences)
- **Application Dossier** : Assemblage de matériaux de candidature evidence-backed
- **Mission Orchestration** (Concept B) : Coordination de missions autonomes exécutées par IA
- **Production Documentaire** : Création et analyse de documents variés (Excel, finance, présentations, CV — pas uniquement carrière)
- **Conseiller Personnel** : Aide à la décision, recommandations adaptées au profil, conversations vie quotidienne
- **Mobilité et Transports** : Recherche trajets, SNCF, TGV MAX, coordonnées de déplacement
- **Mails et Communications** : Gestion comptes, résumés intelligents, suivi d'échanges
- **Études et Apprentissage** : Soutien cours, mémoire, quiz, recherche documentaire
- **Organisation et Productivité** : Planification, tâches, calendriers, routines sur toutes interfaces

## Integration Points
### Spec Kit Cycles
The product follows a Spec Kit-driven development cycle:
- Each feature cycle produces: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/interfaces.md`, `quickstart.md`, `checklists/requirements.md`, `tasks.md`
- Cycles are independent and parallelizable per user story and per domain
- Constitution amendée ensures all agents follow same adapted principles

### OpenCode/Codex Coordination
- **OpenCode perimeter**: Product documentation, Spec Kit orchestration, product roadmap (doc-only)
- **Codex perimeter**: Backend career, performance, deduplication, sprint tasks (code)
- Interface desktop, icon, and macOS bundle remain under OpenCode control
- Les développements non-Career relèvent de la roadmap globale, pas du cycle Career

### Worktree Isolation
All product work occurs in isolated Git worktrees following principle VI:
- Separate worktree for product documentation
- No modifications to source files, specifications (active), constitution active, or mission registry
- Documents in `docs/product/` only

## Document Statut Classification
To eliminate contradictory sources of truth, each document carries a status:

- **Canonique** : Vision maître révisée (come-ai-master-vision.md) — référence unique globale
- **Spécialisé** : Roadmap Carrière (global-roadmap.md Roadmap 2), Inventaire Carrière (feature-inventory.md) — domaine spécifique
- **Historique** : Documents précédents archivés pour référence, non représentatifs de l'état actuel
- **En révision** : Documents en cours de modification (constitution-amendment.md, contradictions-table.md en cours)

## Current Status
- ✅ Spec Kit opérationnel (documentation uniquement, pas de code)
- ✅ Constitution amendée en cours de revue par orchestrateur principal
- ✅ Vision globale révisée (come-ai-master-vision.md) — portée complète
- ✅ Deux roadmaps distinctes : globale (Roadmap 1) et Carrière (Roadmap 2)
- ✅ Ségrégation Concept A (missions pro) et Concept B (missions autonomes)
- 🔄 Proposition documentaire en révision — awaiting human approval
- ⚠️ Documents en statut mixte en cours de clarification