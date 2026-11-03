# RAPPORT FLOTTE — 31/10 02:08

## 1. Introduceurs clés

| Indicateur | Valeur |
|---|---|
| Missions livrées (total) | 83/87 · **95 %** |
| Taux succès (résultats) | **40 %** (356 OK / 537 KO) |
| Durée médiane mission OK | **0 min** |
| Workers actifs | **0/4** |
| File d'attente | 4 mission(s) |
| P0 restantes | aucune |
| Charge machine | 33 |

## 2. Dernières livraisons (24 h)

| Heure | Mission | Modèle | Durée | Résultat | Push |
|---|---|---|---|---|---|
| 23:19 | #90 | opencode/deepseek-v4.1-flash-free | 4 min | done | — |
| 23:14 | #90 | opencode/deepseek-v4.1-flash-free | 18 min | done | — |
| 20:55 | #90 | beam-free | 1 min | done | — |
| 20:52 | #90 | grok-4.7 | 242 min | done | — |
| 16:49 | #90 | opencode/big-pickle | 0 min | done | — |
| 16:49 | #90 | beam-free | 5 min | done | ✓ |
| 16:43 | #90 | opencode/big-pickle | 5 min | done | — |
| 16:37 | #90 | opencode/big-pickle | 2 min | done | ✓ |

## 3. En train de tourner

- aucun worker actif

## 4. Qui a fait quoi (par modèle)

| Modèle | Tâches | OK | Taux OK | Temps total OK |
|---|---|---|---|---|
| opencode/big-pickle | 138 | 99 | 72 % | 304 min |
| beam-free | 214 | 82 | 38 % | 985 min |
| opencode/mimo-v2.6-flash-free | 97 | 81 | 84 % | 240 min |
| opencode/deepseek-v4.1-flash-free | 140 | 69 | 49 % | 296 min |
| qwen3.8-flash | 12 | 8 | 67 % | 44 min |
| grok-4.7 | 7 | 5 | 71 % | 244 min |
| mimo-v2.6-flash | 4 | 4 | 100 % | 2 min |
| minimax-m3 | 5 | 4 | 80 % | 45 min |
| opencode/nemotron-3.5-super-vl-free | 135 | 2 | 1 % | 24 min |
| glm-5.3-flash | 52 | 2 | 4 % | 23 min |
| qwen3.7-plus | 2 | 0 | 0 % | 0 min |
| kimi-k2.7-code | 1 | 0 | 0 % | 0 min |
| google/gemini-3.1-flash-lite | 65 | 0 | 0 % | 0 min |
| qwen3.8-max | 2 | 0 | 0 % | 0 min |
| opencode/glm-5.3-flash | 17 | 0 | 0 % | 0 min |
| longcat-2.0 | 1 | 0 | 0 % | 0 min |
| claude-haiku-5-5 | 1 | 0 | 0 % | 0 min |

## 5. Codex (branche consolidation)

- dernier commit sur origin : `c8e0756`
- latence /api/career/application-pipeline : **4s** (objectif < 3 s)
- périmètre : `career/**` + perf ; ne touche ni l'UI bureau ni l'orchestrateur

## 6. Estimation délai avant résultats

- file restante : 4 mission(s) → **vidée de la file dans ≈ 0 min** (4 slots, médiane 0 min)
- P0 (candidature facile) : ETA ≈ 1 h après leur lancement
- pipeline < 3 s : blocée sur Codex

