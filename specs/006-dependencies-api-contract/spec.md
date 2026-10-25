# Feature Specification: Dependency Graph API Contract

## Requirements

- Node detail returns incoming and outgoing neighbors.
- Unknown nodes and edges return explicit 400/404 responses.
- Non-replacing builds merge with the current graph.
- Career refresh builds profile, offer, requirement, evidence and application nodes.
- Snapshot rollback accepts a documented identifier/version and restores exactly one snapshot.
- Domain exceptions never escape through FastAPI.

## Acceptance

All dependency domain, API and UI contract tests pass.
