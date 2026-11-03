# MISSION SPEC-023 — Personal Memory & Style (mémoire perso des préférences)

> **Priorité : P1** — Fait progresser les reformulations avec l'usage. Worktree dédié.

## Contexte
L'utilisateur choisit, réforme, rejette les variantes. Objectif : construire une **mémoire
personnelle** qui influence automatiquement les futures génération (SPEC-017/020/021/022) :
verbes préférés, tonicité, longueur de bullet, glossaire, décisions passées.

## Modules
```
career/personal_memory.py     # store (JSON local), hook post-choix, API d'injection
career/memory_types.py        # types StylePreference, PastChoice, Glossary
career/memory_report.py       # dashboard + export
career_static/js/memory-panel.js
tests/test_personal_memory.py
docs/agent-reports/SPEC-023-PERSONAL_MEMORY.md
```

## Contrats
```python
@dataclass
class StylePreference:
    key: str                        # "js-action-verb", "tone-length", "glossary:ML"
    value: str
    confidence: float               # ↑ avec répétitions
    source: Literal["user_pick","auto_infer","manual"]
    updated_at: str

@dataclass
class PastChoice:
    context: str                    # "bullet_reformulate:offer_123"
    chosen: dict                    # full slug of option choisie
    rejected: list[dict]
    evidence_refs: list[str]        # preuve de lien avec l'offre
    created_at: str
```

## Règles
- Store JSON append-only (version fermée). Purge possible, jamais de perte silencieuse.
- Les reformulations (arena) **injectent** le top-5 des préférences comme constraints.
- Apprentissage: ≥3 fois la même préférence → `confidence` ≥ 0.8 (appliquée auto).
- Tout choix est **réversible**: section "historique", undo 1 clic.
- Export/Import pour transfert du système (fichier JSON).

## API
```
GET  /memory/prefs                       # liste préférences + confidence
GET  /memory/back                        # historique des choix (avec undo)
POST /memory/prefs                       # creation manuelle
POST /memory/export / import             # JSON file
```

## Validation
```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_personal_memory.py
.venv/bin/python -m pytest -q
git diff --check
```

## Critères de réussite
- [ ] Choix répété 3 fois → application automatique visible dans arena
- [ ] Panel UI avec confidence, source, undo
- [ ] Export/import JSON round-trip sans perte
- [ ] Suite adversarial: mémoire corrompue →确实 restriction seule, pas de génération
- [ ] Ruff clean, suite verte, git diff --check + rapport SPEC-023

**Tu as tout. Lance-toi.** Branche `agent/spec-023-personal-memory`, worktree dédié, code, tests, rapport, push.
