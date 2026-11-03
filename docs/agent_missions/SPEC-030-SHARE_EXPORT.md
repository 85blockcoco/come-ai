# MISSION SPEC-030 — Export & partage lecture CV

> **Priorité : P2** — Lot nocturne 2 (post-SPEC-024). Worktree dédié, push sur branche `agent/spec-030-share-export`.

## Contexte
App Career / CVBoost : le dossier (SK-01..SK-11, SPEC-004..024) fournit la pipeline offre→CV→lettre→suivi.
Envoyer un dossier propre à un contact/école exige un export standardisé et contrôlé.

## Mission
Générateur de bundle de candidature (ZIP + manifest.json) et vue 'lecture' partagée omettant les champs privés ; chaque export tracé.

## Modules (nouveaux, sans conflit avec les autres specs)
```
career/share_export.py           # build_bundle(), ShareView, redact()
tests/test_share_export.py
tests/fixtures/share_synthetic.json
```

## Contrats Python (must-have)
```python
@dataclass
class ShareBundle:
    files: dict[str, bytes]        # path -> contenu
    manifest: dict                 # version, offer_id, generated_at, checksums

@dataclass
class ShareView:
    fields: dict[str, object]      # champs autorisés uniquement
    redacted: list[str]            # champs omis volontairement
```

## Règles
- Données : **fixtures synthétiques uniquement** (`tests/fixtures/*synthetic*.json`). Aucune donnée réelle.
- Tests : `.venv/bin/python -m pytest` → suite complète verte + `ruff check .` propre.
- Jamais de clé/secrets en dur ; tout via `os.environ`.
- API : routes REST via le pattern `create_app()` de `career/router.py`, sans casser `schema_version=7`.
- Redaction en liste blanche stricte : les champs privés ne sortent jamais, même dans le manifest.

## Livrables
1. Code modules + tests (cas limites + au moins 1 test adversarial).
2. Endpoints REST servis via `create_app()` (smoke test obligatoire).
3. Rapport `docs/agent-reports/SPEC-030-share_export.md` (livré, décisions, limites).
4. Push UNIQUEMENT sur la branche `agent/spec-030-share-export` (jamais main).
