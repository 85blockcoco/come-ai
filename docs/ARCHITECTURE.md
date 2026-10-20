# Architecture Côme IA (2026-10-20)

Une application FastAPI monoprocès, entièrement locale par défaut, composée de
surfaces web distinctes qui partagent le même cœur.

```
come_ai_web.create_app()      ← point d'entrée unique (uvicorn)
├── web_static/  v5_static/  career_static/   ← 3 interfaces sans build
├── workspace_core.py         ← cœur V3 : fichiers, analyse, outils agents
├── hybrid_chat.py            ← chat à modèles (Gemini/Ollama) + budget d'appels
├── personal_memory.py        ← mémoire SQLite/FTS5, citations,secure_delete
├── task_queue.py             ← file de tâches persistante (V5)
├── career/service.py         ← Career 4.1 (schéma 7) : offres, CV, lettre
├── consent_guard/            ← consentement signé, usage unique, fail-closed
├── secret_redaction.py       ← politique unique des motifs de secrets
├── devkit/                   ← atelier développeur, jeton local seulement
└── study_coach/              ← non branché (4 500 lignes, à trancher)
```

## Invariants

1. **Local d'abord** : tout outil agent est déterministe et ne touche que
   `data/` (lecture) et `output/` (écriture de rapports). Le modèle ne peut
   jamais exécuter du code ni ouvrir des chemins arbitraires.
2. **Consentement exact** : tout départ de contenu personnel vers un modèle
   distant passe par `consent_guard` (réception unique sur le prompt exact,
   un usage, fail-closed si le garde est absent).
3. **Citations-traçabilité** : la mémoire renvoie toujours
   document — page/lignes — extrait, jamais de réponse nu.
4. **Écriture contrôlée** : `CrossSiteWriteMiddleware` bloque les méthodes non
   sûres cross-origin ; `ensure_directories` pose 0700 ; `secure_delete` est
   activé sur les bases personnelles.
5. **Secrets** : `secret_redaction.py` est la seule source de motifs
   (clés AIza, `AQ…`, `sk-…`, en-têtes d'autorisation) ; `task_queue` et
   `usage_ledger` déléguent.

## Choix structurants (pourquoi ainsi)

- **Monoprocès + locks** : application d'un seul utilisateur sur un seul Mac ;
  la simplicité et le coût en temps réaliste passent avant la scalabilité.
- **Schémas versionnés** (`user_version`) : la base Career refuse
  d'ouvrir une version ultérieure à celle du code (fail-closed) et migre en
  arrière-plan avec sauvegarde préalable — le banc réel a prouvé l'importance
  de ce garde.
- **Deux interfaces de chat** : V3 (historique, riche) et V5 (orchestration
  locale sans modèle, mémoire, finance). Pas de migration forcée entre elles.

## Annexes

- Exploitation quotidien : lancer avec `Lancer Côme AI V3.command`.
- Tests d'acceptation par surface : `tests/` (1 153 tests, base `main` à
  l'intégration du lot CV Boost).
- Historique des décisions de conduite : `docs/audits/`,
  `docs/agent-reports/`, `docs/archive/`.
