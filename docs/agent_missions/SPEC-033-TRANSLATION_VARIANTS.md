# MISSION SPEC-033 — Variantes traduites du dossier (EN/DE/ES)

> **Priorité : P2** — Lot nocturne 2 (post-SPEC-024). Worktree dédié, push sur branche `agent/spec-033-translation-variants`.

## Contexte
App Career / CVBoost : le dossier (SK-01..SK-11, SPEC-004..024) fournit la pipeline offre→CV→lettre→suivi.
Les connecteurs internationaux ramènent des offres EN/DE/ES ; adapter le dossier dans la langue est décisif.

## Mission
Variants de CV/lettre par langue : détecter la langue de l'offre, produire la variante traduite en s'appuyant sur l'arena multi-IA (SPEC-017) si disponible, sinon glossaire statique — jamais d'appel réseau sans arena.

## Modules (nouveaux, sans conflit avec les autres specs)
```
career/translation_variants.py   # detect_offer_lang(), build_variant(), LexiconGL
career/lexicons/en.json + de.json + es.json (synthétiques)
tests/test_translation_variants.py
```

## Contrats Python (must-have)
```python
@dataclass
class VariantReport:
    offer_lang: Literal["en","de","es","fr"]
    mode: Literal["arena","lexicon","passthrough"]
    translated_fields: dict[str, str]
    untranslated: list[str]        # terms sans équivalent

@dataclass
class LexiconGL:
    lang: str
    terms: dict[str, str]          # fr -> lang
```

## Règles
- Données : **fixtures synthétiques uniquement** (`tests/fixtures/*synthetic*.json`). Aucune donnée réelle.
- Tests : `.venv/bin/python -m pytest` → suite complète verte + `ruff check .` propre.
- Jamais de clé/secrets en dur ; tout via `os.environ`.
- API : routes REST via le pattern `create_app()` de `career/router.py`, sans casser `schema_version=7`.
- Détection langue par heuristique locale (stopwords) ; test adversarial : offre mixte FR/EN.

## Livrables
1. Code modules + tests (cas limites + au moins 1 test adversarial).
2. Endpoints REST servis via `create_app()` (smoke test obligatoire).
3. Rapport `docs/agent-reports/SPEC-033-translation_variants.md` (livré, décisions, limites).
4. Push UNIQUEMENT sur la branche `agent/spec-033-translation-variants` (jamais main).
