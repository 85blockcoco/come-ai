# Spec Kit Integration Plan — Product Documentation

## Objective
Prepare a documentary proposal for product integration that will be reviewed and incorporated by the main OpenCode orchestrator. This document outlines the structure, process, and artifacts for product documentation within the Spec Kit framework.

## Integration Context
- **Base**: AI-Excel-Agent-speckit worktree at SHA `d6e2985`, branch `speckit-init`
- **Orchestrator**: Main OpenCode session running independently
- **Constraint**: No modifications to source files, existing specs, constitution, or mission registry
- **Output**: Documents in `docs/product/` only

## Documentary Proposal Structure

### 1. Product Overview (`product-overview.md`)
- High-level product vision and scope
- Core principles from Côme AI Constitution
- Integration points with Spec Kit and OpenCode/Codex

### 2. Integration Plan (`speckit-integration-plan.md`) — This document
- How product documentation integrates with Spec Kit cycles
- Coordination rules with main orchestrator
- Worktree isolation requirements

### 3. Constitution Integration (`constitution-integration.md`)
- Mapping of product decisions to Constitution principles
- Evidence and provenance requirements for product artifacts
- Quality checklists specific to documentation

### 4. Product Roadmap (`roadmap-product.md`)
- Prioritized feature cycles for Spec Kit
- Dependencies between product areas
- Success criteria and exhaustivity targets

## Spec Kit Cycle Workflow for Product Docs

Each product documentation area follows the Spec Kit cycle:

```
spec.md → plan.md → research.md → data-model.md → contracts/interfaces.md → quickstart.md → checklists/requirements.md → tasks.md
```

### Phase 0: Discovery
- Identify product area needing documentation
- Map to Constitution principles
- Define exhaustivity targets

### Phase 1: Specification
- `spec.md`: 2-5 user stories, functional & non-functional requirements
- `research.md`: Technical decisions, integration points, citation sources

### Phase 2: Planning
- `plan.md`: Phases 0-6 implementation plan
- `data-model.md`: Entity definitions, validation rules, state transitions

### Phase 3: Task Generation
- `tasks.md`: Independent parallelizable tasks marked `[P]`
- `contracts/interfaces.md`: qualify_offer, import pipeline, migration contracts

### Phase 4: Implementation & Verification
- Quickstart scenarios (unit, integration, exhaustivity)
- Checklists requirements (all passing)
- Test results validation (1267/1271 pattern)

### Phase 5: Convergence
- `/speckit.converge` assessment of completeness
- Gap analysis and next cycle planning

## Coordination Rules

### With Main Orchestrator
1. **Document submission**: Product docs submitted as `docs/product/` additions only
2. **No source modifications**: Zero changes to `career/`, `specs/`, `.specify/`, `missions_registry.json`
3. **Worktree isolation**: All work in separate worktree, not on `main` or `speckit-init`
4. **Review gate**: Main orchestrator reviews and merges proposition documentaire

### With Codex
1. **Perimeter respect**: Codex handles backend, career, perf, dedup; OpenCode handles product docs
2. **Interface preservation**: Desktop bundle, icon, and `/app` routes remain under OpenCode control
3. **Mission registry**: Only main orchestrator writes to `missions_registry.json`

### Documentation Conventions
- All documents in Markdown format
- YAML front matter where appropriate
- Tables for principles, status, and coordinates
- Clear heading hierarchy (h1, h2, h3)
- Explicit success criteria with ✅/❌ markers

## Deliverables for Review

### Required Documents (in `docs/product/`):
- [`product-overview.md`](product-overview.md) — Product vision and scope
- [`speckit-integration-plan.md`](speckit-integration-plan.md) — This integration plan
- [`constitution-integration.md`](constitution-integration.md) — Principle mapping
- [`roadmap-product.md`](roadmap-product.md) — Prioritized feature cycles

### Optional Supporting Documents:
- `quickstart.md` — Validation scenarios
- `checklists/requirements.md` — Quality checklist
- `research.md` — Technical decisions

## Success Criteria (Proposition Documentation)
- ✅ All documents created in `docs/product/` only
- ✅ Zero modifications to source files, specs, constitution, or registry
- ✅ Worktree isolated from `main` and `speckit-init`
- ✅ Coordination rules clearly documented
- ✅ Spec Kit cycle workflow defined
- ✅ Integration points with OpenCode/Codex specified
- ✅ Success criteria enumerated and measurable

## Next Steps (for Main Orchestrator Review)
1. Review this proposition documentaire
2. Provide feedback on document structure and content
3. Approve or request revisions to `docs/product/` artifacts
4. Integrate approved documents into main Spec Kit workflow
5. Define subsequent product documentation cycles (002, 003, etc.)