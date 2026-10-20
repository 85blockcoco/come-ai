# Côme IA — point d'entrée unique

Application personnelle d'analyse de fichiers et d'aide aux candidatures qui
tourne **sur ce Mac uniquement** (`http://127.0.0.1:8765`), sans envoyer de
donnée à un tiers sans consentement explicite.

## Démarrer

```bash
./Lancer\ Côme\ AI\ V3.command        # double-clic depuis le Finder aussi
# vérification complète (environ 65 s)
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

## Les surfaces

| Section | URL | Doc de référence |
|---|---|---|
| V5 — espace unifié (orchestration, mémoire citée, finance) | `/v5` | [`README_COME_AI_V5.md`](README_COME_AI_V5.md) |
| V3 — interface historique de chat et analyse | `/` | [`README_COME_AI_V3.md`](README_COME_AI_V3.md) |
| Career 4.1 — candidatures (profil, offres, CV, lettre) | `/career` | section Career de [`README_COME_AI_V3.md`](README_COME_AI_V3.md) et [`docs/CONSENT_GUARD_CONTRACT.md`](docs/CONSENT_GUARD_CONTRACT.md) |
| Atelier développeur (devkit) | `/devkit` | jeton local seulement, voir [`HANDOFF_consent_guard.md`](HANDOFF_consent_guard.md) |

## Architecture en une page

Voir [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) : le serveur
(`come_ai_web.create_app`) branche le cœur local (`workspace_core`), le chat
hybride (`hybrid_chat`), la mémoire (`personal_memory`), Career
(`career/service.py`), la file de tâches (`task_queue`) et le garde-fou de
consentement (`consent_guard/`).

## Règles du projet (non négociables)

1. Aucune donnée ne part sans consentement signé sur le prompt exact
   (`consent_guard/`, réception unique, usage unique).
2. Les écritures de rapport vont uniquement dans `output/` ; les fichiers
   sources sont jamais modifiés.
3. CSRF sur méthodes non-sûres, permissions 0700 sur `data/ output/ logs/`,
   suppression sécurisée SQLite pour les données personnelles.
4. Pas de données personnelles réelles dans les fixtures ni dans le dépôt ;
   pas de secrets trackés.
5. Beaucoup de tests : toute modification passe `pytest` puis `ruff`.

## Allez plus loin

- [`docs/ATELIER_AGENTS.md`](docs/ATELIER_AGENTS.md) —brancher OpenCode,
  Codex, Gemini, Ollama et GitHub Education ensemble en boutique d'agents.
- [`CODEX_READY.md`](CODEX_READY.md) — workflow et critères d'acceptation pour
  une mission d'agent automatisé.
- [`docs/HYGIENE_DEPOT_2026-10-20.md`](docs/HYGIENE_DEPOT_2026-10-20.md) —
  purge du dépôt (bundle + archives hors dépôt).
- [`docs/BANC_REEL_WORKSPACE_2026-10-20.md`](docs/BANC_REEL_WORKSPACE_2026-10-20.md) —
  validation sur un vrai dossier de devoirs et les correctifs qui en sont sortis.
- Historique, aphorismes et anciens handoffs : `docs/archive/`.
