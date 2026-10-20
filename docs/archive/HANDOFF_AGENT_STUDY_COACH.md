# HANDOFF — Agent Study Coach

**Destinataire** : Agent Study Coach (Codex / autre)
**Émetteur** : Audit nocturne
**Branche** : `feature/study-coach-v1` (4 commits, worktree `-study-coach`)
**Base** : `main` (`ed8a6b9`) — **entièrement isolée**

---

## 1. Ce qui existe (prêt)

Paquet `study_coach/` **complet, hors-ligne, 82 tests** :

| Module | Rôle |
|---|---|
| `syllabus.py` | extraction notions sourcées, importance 1–3, gaps `information_absente/ambigue` |
| `questions.py` | 5 familles : `definition`, `qcm`, `numerique`, `progressif`, `ouverte` — **toutes citées** |
| `grading.py` | correction déterministe, `score=None` si non évaluable |
| `scheduler.py` | répétition espacée, sélection notions difficiles |
| `store.py` | SQLite dédiée (jamais la base mémoire) |
| `engine.py` | façade unique `StudyCoach.open(path)` |

**Invariant mécanique** : `document.text[char_start:char_end] == SourceRef.excerpt` vérifié par `SourceRef.matches_text()`.

**Démo CLI** : `python -m study_coach.demo` → parcours complet reproductible.

---

## 2. Ce qui manque (intégration V5)

- **Aucune route** dans `come_ai_web.py`
- **Aucun onglet** dans `v5_static/`
- **Aucun adaptateur** `PersonalMemoryStore` (documents) → `StudyCoach`

---

## 3. Tâches (PROMPT 5)

1. Route `/api/v5/study-coach` (ingestion, session, correction, scheduler).
2. Onglet V5 « Révisions » (UI complète).
3. Adaptateur : importer un document mémoire comme cours.
4. Tests d'intégration + saisie navigateur synthétique.

---

## 4. Preuves d'acceptation

```bash
# Dans worktree d'intégration
cd ~/AI-Excel-Agent
.venv/bin/python -m pytest -q tests/ -k "study_coach"

# Test navigateur
# - onglet "Révisions" visible
# - importer un cours -> notions sourcées -> questions -> correction
# - zéro invention (tests de citation passent)
```

---

## 5. Fichiers concernés

- `study_coach/` (existant, ne pas modifier la logique)
- `come_ai_web.py` (nouvelles routes)
- `v5_static/` (nouvel onglet + JS/CSS)
- `tests/` (tests d'intégration)

---

## 6. Interdits

- Aucune notion non citée (invariant `matches_text()`).
- `score=None` si non évaluable.
- Hors-ligne par défaut.
- Pas d'appel modèle pour générer du contenu.

---

## 7. Contacts

- Agent Mémoire : adaptateur `PersonalMemoryStore` → ingestion cours
- Agent Career : préparation entretien (questions Study Coach)
- Agent Codex : validation globale