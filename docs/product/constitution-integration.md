# Côme AI Constitution Integration — Product Documentation

## Mapping Product Decisions to Constitution Principles

This document maps all product documentation decisions to the 7 core principles of the Côme AI Constitution v1.0.0. Every assertion, statistic, and claim in product documents must trace back to a source or apply these principles.

### Principle I: Career-First Priority (adapté)
**Règle** : Le Career Explorer est un module majeur du produit, mais pas la finalité unique.

Chaque développement doit démontrer qu'il sert l'un des domaines transverses de Côme IA, ou justifier pourquoi il est spécifique à un domaine particulier sans imposer qu'il serve Career Explorer en priorité.

Les principes de qualité, de preuves et de confidentialité s'appliquent à tout le produit, pas uniquement aux fonctionnalités Career.

| Product Doc Area | Constitution Alignment |
|------------------|------------------------|
| Product overview | Vision globale répartie sur tous les domaines ; Career est un module spécialisé parmi d'autres |
| Offer qualification | Features serve career-first job analysis, mais pas exclusivement — aussi académique, mobilité, communications |
| Mission orchestration (Concept B) | Supports career milestone tracking, plus autonome missions orchestrées |
| Application dossier | Enables career transition workflows, plus production documentaire variée |
| Autres domaines (académique, finance, etc.) | S'appliquent également, indépendamment de Career |

### Principle II: Max Quality, Zero API Spend (adapté)
**Règle** : Exigence de qualité maximale avec maîtrise des coûts.

Le code doit être déterministe et local dans la mesure du possible.

L'utilisation de services externes (API payantes) est autorisée lorsqu'elle est nécessaire pour une fonctionnalité critique, avec ces conditions :
1. L'utilisateur en est informé et a donné son autorisation explicite
2. Le coût est traçable et maîtrisable (quotas, plafonds configurables)
3. Les données sensibles ne sont jamais transmises sans chiffrement de bout en bout et consentement
4. Une version locale déterministe existe en alternative (même si plus lente ou limitée)
5. La dépendance externe est documentée avec provenance (source, quota, coût unitaire)

| Product Doc Area | Constitution Alignment |
|------------------|------------------------|
| Documentation generation | Pure functions, no external API calls en priorité ; API autorisées avec conditions |
| Data modeling | Deterministic schema, no random state ; API locales privilégiées |
| Citation extraction | Local text processing only ; API externes autorisées si nécessaire avec conditions |
| Exhaustivity metrics | Offline computation on local corpus en priorité ; données externes avec autorisation utilisateur |

### Principle III: Privacy by Design (clarifié, pas changé)
**Règle** : Rester strict : aucune donnée sensible ne quitte le Mac sans consentement signé et explicite.

Les données non sensibles (requêtes de recherche, statistiques d'usage agrégées, configurations d'interface) peuvent être transmises entre le Mac, le serveur personnel, l'iPhone et le web lorsque :
1. L'utilisateur a configuré la synchronisation pour cette catégorie de données (MP-004)
2. Le transfert est chiffré de bout en bout
3. L'utilisateur peut révoquer l'autorisation à tout moment
4. Chaque catégorie de données fait l'objet d'une politique de conservation configurable

| Product Doc Area | Constitution Alignment |
|------------------|------------------------|
| User data handling | Données sensibles : consentement signé requis ; données non sensibles : autorisation configurables par catégorie |
| Citation provenance | Source must be local or signed pour données sensibles ; pour données non sensibles, traceabilité partielle acceptée avec autorisation |
| Exhaustivity measurement | Computed on-device, no corpus export pour données sensibles ; données agrégées externes avec autorisation |
| Mission data | Never transmitted without authorization pour données sensibles ; données non sensibles : transmission autorisée avec chiffrement bout en bout |

### Principle IV: Mandatory Evidence & Provenance
**Rule**: Every fact has citation (source, quote, offset)

| Product Doc Area | Constitution Alignment |
|------------------|------------------------|
| Exhaustivity percentages | Must cite source corpus, quote, offset range |
| Success criteria | Must reference test results provenance |
| Feature capabilities | Must cite implementing code or spec |
| Integration points | Must reference Spec Kit cycle artifact |

**Evidence Requirement**: Every table, statistic, or claim includes (source, quote, offset) tuple. See `specs/001-persist-qualification-facts/` for pattern.

### Principle V: Test-First, Proof-Required
**Rule**: TDD mandatory, synthetic truth corpora

| Product Doc Area | Constitution Alignment |
|------------------|------------------------|
| Documentation quality | Quickstart validation scenarios |
| Exhaustivity targets | Measured against test corpus |
| Success criteria | Must pass before document finalization |
| Integration completeness | Converge assessment required |

**Evidence Requirement**: Document must reference corresponding test file or quickstart scenario. Pattern: `tests/test_*.py` or `quickstart.md` validation.

### Principle VI: Git Protected, Supervised Autonomy (renforcé documentationnellement)
**Rule** : Work in isolated branches/worktrees.

**Renforcement issu de la session documentaire** :
- Pour le déploiement multi-agents Spec Kit : maximum 3 agents exécutants pour toute première vague de développement.
- Les modifications code n'arrivent jamais sur main sans accord explicite de l'orchestrateur principal.

| Product Doc Area | Constitution Alignment |
|------------------|------------------------|
| This worktree | `AI-Excel-Agent-speckit-worktree` on `product-docs` isolation |
| Document creation | `docs/product/` only, no source modifications |
| Review process | Main orchestrator gate before integration |
| Branch management | Separate from `main` and `speckit-init` |
| Configuration agente | Maximum 3 agents vague première — opérationnelle, pas principe constitutionnel permanent |

**Evidence Requirement**: Document must reference worktree path and isolation methodology. This worktree: `/Users/comedelavenne/AI-Excel-Agent-speckit-worktree` at commit `d6e2985`.

**Non applicable** : Transformer la limite d'agents dans un principe constitutionnel permanent. C'est une configuration opérationnelle de la présente session documentaire.

### Principle VII: Simplicity & Observability
**Rule**: Pure functions, honest progress, YAGNI

| Product Doc Area | Constitution Alignment |
|------------------|------------------------|
| Documentation structure | Minimal, necessary content only |
| Feature claims | No over-engineering, YAGNI compliance |
| Progress reporting | Honest status (✅/❌, in progress, pending) |
| Integration complexity | Only documented integration points |

**Evidence Requirement**: Documents must avoid speculative features not in current scope. YAGNI check before adding new sections.

## Provenance Tracking for Product Documents

### Citation Format
All factual claims follow this format:
```
(source, quote, offset)
```

### Examples
- **Exhaustivity claim**: `(missions_registry.json, "56/73 livrées", line 34)`
- **Test result**: `(tests/test_qualification_persistence.py, "11/11 PASS", line 60)`
- **Constitution principle**: `(.specify/memory/constitution.md, "Principle II", line 18)`
- **Worktree isolation**: `(COORDINATION.md, "Git Protected principle", line 22)`

### Provenance Table (Template)
| Claim | Source | Quote | Offset |
|-------|--------|-------|--------|
| Product vision statement | `come-ai-master-vision.md` (révisé) | "Assistant personnel global, tous domaines" | h1 |
| Constitution amendée | `constitution-amendment.md` | "Principes adaptés, pas supprimés" | h2 |
| Vision globale | `come-ai-master-vision.md` | "Portée: Côme IA dans sa globalité" | h1 |
| Principes adaptés | `constitution-amendment.md` | "I: Career majeur pas finalité unique" | amendement I |
| Principe II adapté | `constitution-amendment.md` | "API autorisées avec conditions" | amendement II |
| Principe III clarifié | `constitution-amendment.md` | "Données sensibles vs non sensibles" | amendement III |
| Renforcement VI | `constitution-amendment.md` | "Max 3 agents vague première" | amendement VI |
| Inventaire global | `global-feature-inventory.md` | "Portée transversale, pas Career-only" | règle #4 |
| Roadmap globale | `global-roadmap.md` | "Roadmap 1 + Roadmap 2 distinctes" | h2 |
| Analyse écarts | `global-gap-analysis.md` | "Concept A / Concept B séparés" | Écart 1 |
| Tableau contradictions | `contradictions-table.md` | "10R + 3V + 3NC sur 16" | synthèse |

## Integration Checklist

### Pre-Commit Checks
- [ ] All factual claims have provenance (source, quote, offset)
- [ ] No modifications to `career/`, `specs/`, `.specify/`, `missions_registry.json` (actif)
- [ ] Worktree isolated from `main` and `speckit-init`
- [ ] Documents reside solely in `docs/product/`
- [ ] Constitution principles explicitly mapped (amendée en cours de revue)
- [ ] Success criteria marked ✅ or ❌
- [ ] Cycle 002 implémentation rapportée, revue fonctionnelle et intégration à confirmer (ne pas automatiquement "terminé sur main")

### Post-Merge Checks (after orchestrator review)
- [ ] Documents integrated into main workflow (après approbation humaine)
- [ ] Subsequent cycles (002, 003, etc.) planifiés — Cycle 002 : implantation rapportée, revue fonctionnelle en cours
- [ ] No provenance gaps introduced
- [ ] Coordination rules validated ( selon principes amendés I-VII) ;
  • Pas de mélange Concept A / Concept B sans séparation explicite
  • Pas de réutilisation automatique R2 Career → Concept B
  • Pas de chiffre d'exhaustivité unique pour tout le produit

## Violations & Remediation

### Common Violations
1. **Uncited statistic**: "75% of offers have dates populated" without (source, quote, offset)
2. **Source modification**: Changing `career/service.py` or `missions_registry.json` (actif)
3. **Worktree leakage**: Changes outside `docs/product/` in the worktree
4. **API spend claim**: Asserting external service usage without disclaimer ; API autorisées avec conditions (voir amendement II constitution)
5. **Vision Career-only** : Imposer que chaque fonctionnalité serve Career (contraire à amendement I constitution amendée) ; utiliser vision globale (come-ai-master-vision.md) comme référence
6. **Concept A/B confondus** : Lier artificiellement extraction d'offres et synchronisation missions autonomes (contraire à global-gap-analysis.md Écart 1) ; maintenir séparés avec identifiants, exigences et modèles distincts
7. **Limite 3 agents comme principe permanent** : Transformer configuration documentaire en principe constitutionnel permanent (contraire à amendement VI constitution amendée) ; rappeler que c'est configuration opérationnelle pour première vague uniquement

### Remediation
1. Add provenance citation or remove uncited claim
2. Revert source modifications; use worktree for all changes
3. Restrict changes to `docs/product/` only; request new worktree if needed
4. Add "offline-only" qualifier or remove API spend claim

## This Document's Provenance
| Claim | Source | Quote | Offset |
|-------|--------|-------|--------|
| Constitution v1.0.0 existence | `SPECKIT_INTEGRATION_SUMMARY.md` | "Created at `.specify/memory/constitution.md`" | line 14 |
| 7 principles list | `SPECKIT_INTEGRATION_SUMMARY.md` | Table of principles | lines 15-23 |
| Spec Kit cycle workflow | `SPECKIT_INTEGRATION_SUMMARY.md` | "spec.md → plan.md → research.md" | lines 32-41 |
| Amendement I (Career adaptée) | `constitution-amendment.md` | "Career majeur pas finalité unique" | h2 |
| Amendement II (Zero API Spend adaptée) | `constitution-amendment.md` | "API autorisées avec conditions" | amendement II |
| Amendement III (Privacy clarifié) | `constitution-amendment.md` | "Données sensibles vs non sensibles" | amendement III |
| Renforcement VI (3 agents) | `constitution-amendment.md` | "Max 3 agents vague première" | amendement VI |
| Vision globale révisée | `come-ai-master-vision.md` | "Portée: Côme IA dans sa globalité" | h1 |
| Ségrégation Concept A/B | `global-gap-analysis.md` | "Concept A / Concept B séparés" | Écart 1 |
| Classification document | `product-overview.md` | "Status: Canonical / Spécialisé / Historique" | Classification docs |