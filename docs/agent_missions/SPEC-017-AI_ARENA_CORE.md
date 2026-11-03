# MISSION SPEC-017 — AI Arena Core (moteur multi-IA concurrent)

> **Priorité : P0** — Dépendance critiques de toutes les missions de reformulation. Worktree dédié.

## Contexte
Pipeline Career existante (SK-01 à SK-11 + SPEC-004 à 010). Objectif du lot suivant : adapter
fortement CV + lettre à chaque offre de stage. Il faut un moteur qui **interroge plusieurs IA
en concurrence et sélectionne les meilleures idées**.

## Providers (concurrence, tolérance de panne)
| Provider | Accès | Fallback si indisponible |
|----------|-------|--------------------------|
| **opencode** | runtime navigateur local (lié à l'environnement worker) | OK prioritaire |
| **ollama** | `http://127.0.0.1:11434/api/generate` (temps réel, timeout 5s) | skip si non démarré |
| **gemini** | si `GEMINI_API_KEY` dans l'environnement | skip si manquant |
| *futura: openai/mistral* | désactivé tant que la clave manquante | n / a |

## Modules
```
career/ai/
  __init__.py
  providers.py       # IAProvider protocol + OpenCodeAI, OllamaAI, GeminiAI
  arena.py           # run_arena(): exécution en concurrence + fois timeout
  jury.py            # scoring/blind-judge + best-of / consensus
  cache.py           # memoization (hash prompt+model), invalidation par version
  config.py          # modèle settings, CLÉs via os.environ uniquement
tests/test_ai_arena.py + adversarial + fixtures
docs/agent-reports/SPEC-017-AI_ARENA_CORE.md
```

## Contrats
```python
@dataclass
class IARequest:
    task_type: Literal["keywords", "reformulate", "letter", "score", "research"]
    input_payload: dict
    model_hint: str | None = None

@dataclass
class IAResponse:
    provider: str
    model: str
    content: dict
    latency_ms: float
    cached: bool = False

@dataclass
class ArenaVerdict:
    winner: str
    merged_bullets: list[str]      # meilleures idées, fuse à partir des répondants
    responses: list[IAResponse]
    jury_scores: dict[str, float]
    disagreement: float
```

## Règles
- TOUJOURS demandé en **concurrence async** (asyncio), timeout par IA 30s, global 45s.
- Un provider indisponible → ignoré silencieusement (jamais 500 sur le route).
- **Jamais de clé secrète en dehors de env**. Aucun log de prompts sensibles complets.
- Règles dispute: > 0.5 → ré-évaluation avec 1 provider supplémentaire (best effort).
- Anti-hallucination: provider doit citer les ids de preuves/profil si textes libres.

## API
```
POST /ai/arena/run            # side-by-side, retourne ArenaVerdict
GET  /ai/arena/status         # santé providers, cache stats
POST /ai/arena/config         # ajuster timeout / scoréing style (non-secret)
```

## Args de validation
```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_ai_arena.py
.venv/bin/python -m pytest -q
git diff --check
```

## Critères de réussite
- [ ] 3 providers opérationnels & détection automatique de leur disponibilité
- [ ] Arena run avec 2+ providers en concurrence, résultats fusionnés "best-of" tracés
- [ ] Jury avec scoring déterministe + fuse multi-IA_visible dans UI partielle (utilisé tôt)
- [ ] Test adversarial: provider KO, timeout, réponse vide, réponse hors-format
- [ ] cache 100% off testable
- [ ] Ruff clean, suite complète verte, git diff --check propre + rapport SPEC-017

**Tu as tout. Lance-toi.** Branche `agent/spec-017-ai-arena-core`, worktree dédié, code, tests, rapport, push.
