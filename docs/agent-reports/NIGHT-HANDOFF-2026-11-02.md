# HANDOFF NOCTURNE — 02/11/2026 (état au réveil)

## Où en est NAGE (tout est poussé et vérifié)

- **Branche de livraison : `origin/agent/n100-carrier-20261101`**
- **Tip vérifié : `63635d715a866a8d08599895995aa2ce2b939882`** (`git ls-remote` == local)
- v1 : 87/87 done.
- N100 : **99/100 done** (`missions_next100.json`).
  - Seule **J04 (PWA hors-ligne)** reste ouverte : l'app est déjà locale,
    une PWA sans serveur n'apporte pas de valeur et pourrait masquer des
    données personnelles. Décision humaine attendue.
- Codex consolidé **U2+U3+U4+U5+U7** : revu, testé, intégré
  (merge `0aa7224`, dédup `bd07d64`).
- CLI `nage.py` : finance, maths, budget local, plan du jour, brief,
  recherche, méthode devoirs. 8 tests dédiés.
- Recette J10 : **56 passed in 12.92s**, instance HTTP jetable vérifiée,
  rapport `docs/agent-reports/N100-J10-RECIPE.md`.
- Guide utilisateur : `docs/USER_GUIDE_V2.md`.
- Serveurs : 8765 (dev) et 8766 (NAGE Bureau) = **200 / 200**.

## Reprendre après redémarrage machine

```bash
cd /Users/comedelavenne/AI-Excel-Agent
git fetch origin
git checkout agent/n100-carrier-20261101
git merge --ff-only origin/agent/n100-carrier-20261101

# serveur dev (8765)
.venv/bin/python run_come_ai_v3.py --no-browser --port 8765
# NAGE Bureau (8766), dans un autre terminal
cd /Users/comedelavenne/NAGE-release
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python run_come_ai_v3.py --no-browser --port 8766
```

Puis ouvrir :
- Career : http://127.0.0.1:8765/career
- Espace unifié : http://127.0.0.1:8765/v5
- Bureau : http://127.0.0.1:8766/

## Vérifications rapides

```bash
cd /Users/comedelavenne/AI-Excel-Agent
.venv/bin/python -m pytest -q \
  tests/test_e2e_local_pipeline.py tests/test_career_letter_routes.py \
  tests/test_career_shortlist_routes.py tests/test_career_dossier_routes.py \
  tests/test_n100_letter_ui.py tests/test_n100_career_accessibility.py \
  tests/test_academics_routes.py tests/test_academics_integration.py \
  tests/test_nage_cli.py tests/test_urgency_shortlist.py
# attendu : 56 passed

.venv/bin/python nage.py finance future_value pv=100 rate=0.1 periods=2
.venv/bin/python nage.py plan --minutes 120 --task "NPV|2026-11-03|45|1"
```

## WIP UI locale préservé (non intégré)

Des modifications UI non commitées existaient dans le worktree principal avant
la mise à jour (career_static, web_static, v5_static, missions_registry.json).
Elles sont **préservées** dans :

- stash : `WIP UI locale 02/11 - preserve avant ff carrier 9806f9e`
- patch : `/private/var/folders/jd/ymcfd0zs7kzc6f90p1x6gh5c0000gp/T/opencode/local-ui-wip-20261102.patch`

Elles n'ont pas été appliquées : non testées, et potentiellement en conflit
avec U4/U5. À relire avant intégration.

## Règles toujours valables

- Jamais de force-push / reset --hard / git clean / suppression de branche.
- Push uniquement via `HEAD:refs/heads/agent/n100-carrier-20261101` + vérif
  `git ls-remote`.
- Tests ciblés uniquement ; preuve avant tout « done ».
- Aucune soumission automatique de candidature ; approbation humaine
  obligatoire avant export DOCX/PDF.
- Aucune donnée personnelle ni clé API dans le dépôt.
