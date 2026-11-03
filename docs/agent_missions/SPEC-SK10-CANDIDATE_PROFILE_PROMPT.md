# MISSION SPEC KIT — SK-10 : Profil candidat avec preuves approuvées

> **Priorité : P1** — Après SK-01 (structure CV Mission 01).

---

## Objectif

Transformer le CV importé en **profil structuré contrôlé par l'utilisateur**.

---

## Pipeline

```
PDF/DOCX/image
  → extraction locale (Mission 01 parser)
  → OCR local si nécessaire
  → propositions de faits (skills, experiences, education, languages, etc.)
  → provenance page/passage (offsets exacts)
  → approbation champ par champ (UI)
  → profil actif (seuls faits approuvés)
```

---

## Statuts par fait

| Statut | Sémantique |
|--------|------------|
| `proposed` | Extrait automatiquement, en attente validation |
| `approved` | Validé par utilisateur → utilisable pour matching/candidature |
| `rejected` | Rejeté par utilisateur (erreur OCR, hors sujet) |
| `modified` | Corrigé par utilisateur (ex: date, niveau langue) |
| `suspended` | Mis de côté temporairement |

---

## Critères non négociables

1. **Résultat OCR jamais automatiquement approuvé** — tout passe par validation
2. **Chaque compétence, expérience, date, diplôme garde sa source** (page, offsets, quote)
3. **Suppression et export fonctionnent** (profil portable)
4. **Aucun document réel dans les tests** (fixtures synthétiques uniquement)
5. **Faits non approuvés ≠ justifier une candidature** (bloquant pour SK-11)
6. **Vrais essais utilisateur séparés des fixtures Git**

---

## Modules

```
career/candidate_profile.py        # Modèle Profil, Fait, Statut
career/profile_builder.py          # Pipeline extraction → propositions → approbation
career/cv_quality/parser.py        # Réutiliser Mission 01 (existante)
career/router.py                   # Endpoints profil CRUD + approbation
career_static/js/profile-builder.js # UI approbation champ par champ
tests/test_candidate_profile.py
tests/fixtures/candidate_profile/
```

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_candidate_profile.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] Pipeline complet: PDF → propositions → approbation → profil actif
- [ ] 5 statuts implémentés
- [ ] Provenance exacte (page, offsets, quote) pour chaque fait
- [ ] OCR jamais auto-approuvé
- [ ] Suppression/export fonctionnels
- [ ] Tests 100% synthétiques
- [ ] Faits non approuvés exclus du matching/candidature
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK10-CANDIDATE_PROFILE.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk10-candidate-profile`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.