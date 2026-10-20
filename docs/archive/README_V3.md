# AI Workspace V3

> **Documentation historique — fichier archivé.** L'interface Tkinter décrite
> ci-dessous (`app_v3.py`) a été retirée du dépôt le 2026-10-20 : elle n'était
> lanceable par aucun raccourci actuel et aucun test ne la couvrait. Son
> historique complet reste dans Git (`git log --follow -- app_v3.py`).

## Où aller maintenant

- **Côme AI 5.0 (Assistant, mémoire, finance, tâches)** : [`README_COME_AI_V5.md`](README_COME_AI_V5.md)
  — lanceur : `Lancer Côme AI V3.command` ou `run_come_ai_v3.py`, puis ouvrir `/v5`.
- **Career 4.1 (offres, candidatures, coach)** : ouvrir `/career` après le lancement, doc [`README_CAREER_EXPLORER.md`](README_CAREER_EXPLORER.md).
- **Vue historique `/`** (chat + actions fichiers) : [`README_COME_AI_V3.md`](README_COME_AI_V3.md).

## Vérification (unique et valable)

```bash
cd ~/AI-Excel-Agent
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
```

La suite complète (1130+ tests) couvre l'inspection, les calculs et la
génération de rapports temporaire que le script `test_v3_offline.py` assurait
(précédemment supprimé avec son interface).
