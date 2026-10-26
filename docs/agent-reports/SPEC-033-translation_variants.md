# SPEC-033 — Variantes traduites du dossier (EN/DE/ES)

**Mission** : 68 · **Branche** : `agent/spec-033-translation-variants` · **Statut** : done

## Livrés

| Fichier | Rôle |
|---|---|
| `career/translation_variants.py` | Module principal : `detect_offer_lang()`, `build_variant()`, `LexiconGL`, `VariantReport` |
| `career/lexicons/en.json` | Lexique FR → EN (41 termes) |
| `career/lexicons/de.json` | Lexique FR → DE (41 termes) |
| `career/lexicons/es.json` | Lexique FR → ES (41 termes) |
| `tests/test_translation_variants.py` | 30 tests (détection, lexiques, variantes, déterminisme) |
| `career/router.py` | 2 endpoints REST (`/api/career/translation-variants/detect`, `/build`) |

## Contrats respectés

- `VariantReport(offer_lang, mode, translated_fields, untranslated)` — dataclass immuable
- `LexiconGL(lang, terms)` — dataclass immuable
- `detect_offer_lang(text) → "en"|"de"|"es"|"fr"` — heuristique stopwords locale (0 réseau)
- `build_variant(variant_id, target_lang, arena_available=False) → VariantReport`
  - `mode="passthrough"` si `target_lang == "fr"`
  - `mode="arena"` si `arena_available=True` (réserve SPEC-017)
  - `mode="lexicon"` par défaut (hors-ligne)

## Décisions

1. **Pas de réseau sans arena** — le module ne fait jamais d'appel réseau. Le lexique statique couvre les 41 termes de variante (labels, sections, mots-clés, tons de lettre).
2. **Heuristique stopwords** — détection de langue par comptage de mots vides, déterministe, sans modèle. Les textes mixtes sont résolus par majorité.
3. **Fallback lexicon** — quand aucun terme du lexique ne couvre un champ, il apparaît dans `untranslated` (aucune invention).
4. **Endpoint `/detect`** — retourne la langue détectée sans sauvegarder (idempotent, sans effet de bord).

## Tests

```
pytest -q tests/test_translation_variants.py → 30 passed
ruff check career/translation_variants.py career/router.py → All checks passed!
git diff --check (fichiers mission) → propre
```

Couverture :
- Détection langue : EN, DE, ES, FR, texte vide, texte court, mixte FR/EN (adversarial)
- Lexiques : chargement, validité JSON, immutabilité, traduction de termes clés
- Variantes : 3 variantes × 3 langues (9 cas), mode passthrough, mode arena, déterminisme
- Erreurs : variante inconnue, langue inconnue

## Limites

- Arena (SPEC-017) non implémentée — le chemin `mode="arena"` existe mais redirige vers le lexique aujourd'hui (tous les champs sont repris ; aucun champ n'est laissé non traduit).
- Le lexique couvre les termes de variante uniquement, pas le contenu complet du CV/lettre (le générateur de kit `application_studio.py` produit déjà du contenu multilingue via `_factual_sections` — ce module complète la couche variante).
- Aucune donnée réelle n'a été utilisée — uniquement des fixtures synthétiques.

## Suite — audit 26/10/2026 (smoke REST)

Audit des endpoints REST : les routes `/api/career/translation-variants/detect`
et `/build` répondaient systématiquement 422.

Causes corrigées :
1. Les modèles `TranslationDetectPayload` / `TranslationBuildPayload` étaient
   imbriqués dans `create_career_router()` ; avec `from __future__ import
   annotations`, FastAPI ne les résout pas comme Body et exige un query param
   `payload`. Déplacés au niveau module (comme `ResetPayload`).
2. `local()` applique `to_jsonable`, qui stringifie les dataclasses — le
   `VariantReport` revenait en `str`. Le handler sérialise désormais via
   `dataclasses.asdict`.

Ajout : `test_rest_smoke_detect_and_build` (detect 200 + build 201, mode lexicon).
Résultats : `pytest tests/test_translation_variants.py` → 31 passed ; ruff clean.
Suite complète : 3005 passed, 1 failed préexistant et hors périmètre
(`test_evolution_web.py::test_evolution_candidate_result_has_direct_review_handoff`,
échoue aussi sans mes modifications).
