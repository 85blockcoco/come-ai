# SPEC-030 — Export & partage lecture CV

## Livré

- Module `career/share_export.py` avec `ShareBundle`, `ShareView`, `build_bundle`, `redact`, `is_private_field`.
- Bundle en mémoire (`files: dict[str, bytes]`, `manifest`) avec manifest version, offer_id, generated_at, export_id, checksums.
- Redaction par liste blanche stricte avec champs privés connus supprimés par défaut.
- Endpoints REST `/api/career/share/redact`, `/api/career/share/bundle`.
- Tests `tests/test_share_export.py`, fixture `tests/fixtures/share_synthetic.json`.

## Décisions

- Aucune I/O réseau ; le bundle reste en mémoire jusqu'à décision de l'appelant.
- `ShareView` hérite de `dict` pour compatibilité avec les tests mapping et dataclass.
- Trace via liste(s) fournie(s), callback ou champs de données.

## Limites

- Pas de persistance automatique ni d'envoi ; l'export est tracé en mémoire/manifest.
- Redaction par défaut supprime les champs privés connus ; une liste blanche explicite reste recommandée.
