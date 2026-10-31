# SPEC-033 — Variantes traduites du dossier (EN/DE/ES)

## Livré
- `career/translation_variants.py` : `detect_offer_lang()`, `build_variant()`, `LexiconGL`, `VariantReport`.
- Lexiques statiques : `career/lexicons/en.json`, `de.json`, `es.json` (synthétiques).
- Tests : `tests/test_translation_variants.py`.
- Endpoints REST via `create_app()` : `/api/career/translation/detect-language`, `/api/career/translation/variant`, `/api/career/translation/lexicons/{lang}` + alias.

## Décisions
- Détection de langue par heuristique locale (stopwords) pour fr/en/de/es ; repli `en` si indéterminé.
- Mode `arena` uniquement si un générateur est explicitement fourni ; sinon `lexicon` ; `passthrough` si la langue cible est le français.
- Aucun appel réseau : l'arena n'est jamais instanciée dans ce module.
- Terme sans équivalent conservé en français et reporté dans `untranslated`.

## Limites
- Traduction lexicale par remplacement de termes (pas de traduction syntaxique complète).
- Lexiques synthétiques, couverture limitée aux termes CV/dossier courants.
- Arena (SPEC-017) non disponible dans ce worktree : chemin arena testé en best-effort.