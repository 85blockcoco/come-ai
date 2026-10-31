# WORKER TEMPLATE — Inclus dans le prompt pour que le Worker sache comment rapporter ses résultats

## 📋 COMMENT RAPPORTER TON TRAVAIL (OBLIGATOIRE)

À la fin de ton travail, tu DOIS écrire un fichier `messages/result.json` dans le worktree avec ce format :

```json
{
  "status": "done|failed",
  "files_created": [
    "career/cv_quality/ats.py",
    "tests/test_cv_quality_ats.py",
    "docs/agent-reports/CVBOOST-04-ATS.md"
  ],
  "output": "Résumé de ce qui a été livré (1-2 phrases)",
  "logs": "Ce qui s'est passé (derniers logs pertinents)",
  "error": null
}
```

### RÈGLES :
1. **`files_created`** : Liste TOUS les fichiers créés/modifiés (chemins relatifs au worktree)
2. **`output`** : Résumé court de ce qui a été livré
3. **`logs`** : Derniers logs pertinents (tests, erreurs, etc.)
4. **`error`** : `null` si succès, message d'erreur si échec
5. **Écris ce fichier AVANT de terminer** — l'orchestrateur le lit pour faire ton rapport

### EXEMPLE RÉUSSI :
```json
{
  "status": "done",
  "files_created": [
    "career/cv_quality/ats.py",
    "career/cv_quality/models.py",
    "tests/test_cv_quality_ats.py",
    "docs/agent-reports/CVBOOST-04-ATS.md"
  ],
  "output": "Module ATS local complet (9 détecteurs, score pondéré, 12 tests synthétiques)",
  "logs": "pytest -q tests/test_cv_quality_ats.py → 12 passed\nruff check . → All checks passed",
  "error": null
}
```

### EN CAS D'ÉCHEC :
```json
{
  "status": "failed",
  "files_created": ["career/cv_quality/ats.py"],
  "output": "Partiel — détecteurs 1-5 faits, 6-9 bloqués",
  "logs": "Erreur import pdfplumber manquant\npytest → 3 failed, 9 passed",
  "error": "Module pdfplumber non installé, détecteurs 6-9 inopérants"
}
```

---

## ✅ CHECKLIST AVANT DE TERMINER

- [ ] `./checklist_codex.sh` → TOUT VERT
- [ ] `pytest -q` → TOUT VERT (pas de régression)
- [ ] `git diff --check` → PROPRE
- [ ] `messages/result.json` ÉCRIT dans le worktree
- [ ] Branch prête pour audit/relecture

---

## 🔧 OUTILS DISPONIBLES DANS LE WORKTREE

```bash
# Tests
.venv/bin/python -m pytest -q                    # Suite complète
.venv/bin/python -m pytest -q tests/test_*.py    # Tests ciblés

# Lint
.venv/bin/python -m ruff check .

# Git
git diff --check
git status --short
```