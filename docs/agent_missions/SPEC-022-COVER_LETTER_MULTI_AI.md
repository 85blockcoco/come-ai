# MISSION SPEC-022 — Cover Letter Multi-AI (lettre de motivation de stage)

> **Priorité : P0** — Se contenter de reprendre les infos d'offre : instruis par la multi-IA. Worktree dédié.

## Contexte
La lettre de motivation est la pièce la plus humaine : ton, structure, histoire. Objectif :
générer une lettre **adaptée au stage** : 3 brouillons par 3 IA (SPEC-017), fusion meilleure
des idées, avec interneurs de SPEC-018 (entreprise réelle), SPEC-019/020 (mism clés, matches cofusés).

## Modules
```
career/letter_generator.py     # orchestrateur: 3 drafts multi-IA, fusion, sortie DOCX
career/letter_structure.py     # intro/corps/conclusion + teutiques de connexion
career/letter_tone.py          # adaptaton ton (formel/direct/startup/banque)
career/letter_triage.py        # génération + rang;私家 aussi insights BET/matching SK-21
career_static/js/letter-wizard.js
tests/test_letter_generator.py
docs/agent-reports/SPEC-022-COVER_LETTER.md
```

## Contrats
```python
@dataclass
class LetterDraft:
    draft_id: str
    paragraphs: list[LetterPara]
    tone: Literal["formel","direct","startup","corporate"]
    used_bullets: list[str]           # refs reformulations spécifiées (SPEC-020)
    guessed_facts: list[str]          # = facts montré sourcés uniquement (SPEC-018)
    jury_score: float
    provider: str

@dataclass
class LetterPlan:
    drafts: list[LetterDraft]
    best_id: str
    merged_alternative: LetterDraft   # fusion "meilleures idées" (arena)
    ats_compat_check: dict            # check ATS docx/pdf (SPEC-04 réutilisés)
```

## Structure imposée (4 paragraphes max)
1. **Hook** — intérêt concret pour le poste + 1 fait sourcé sur l'entreprise (SPEC-018)
2. **Preuves** — 2-3 réalisations reformulées (chiffres si preuve existe) alignées aux mots-clés
3. **Projets / cours** — avalisé le SPEC-021 dire la osill du cursus
4. **Clôture** — demande entretien, données de contact du profil

## Règles
- Chaque fait sur l'entreprise → `evidence_refs` obligatoires (pas de "votre réputée d'innovation" flottante).
- Longueur max 350 mots / 1 page A4 ; jamais > 4 paragraphes (imprimé vérifiable).
- Aucune phrase belle qui résume ce que le CV ne montre pas déjà (redondance interdite).
- 2 provider minimum pour un draft; si 1 provider: fonctionne (pas de crash).
- Anti-template : la même offre produise lettres différentes chaque jour (seed + variation).

## API
```
POST /letter/generate/{offer_id}          # → LetterPlan (3 drafts + fusion)
PATCH /letter/{draft_id}                  # édition manuelle (texte, ton)
POST /letter/{draft_id}/export            # DOCX/PDF — produit un file et c'est tout
GET  /letter/{offer_id}/history           # versions
```

## Validation
```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_letter_generator.py
.venv/bin/python -m pytest -q
git diff --check
```

## Critères de réussite
- [ ] 3 drafts distincts + 1 draft-fusion "meilleures idées", tous visibles
- [ ] Zéro fait non sourcé sur l'entreprise (check adversarial 100+ cas)
- [ ] Export DOCX propre, compatible ATS, avec l'import provenancebiliens
- [ ] Diff preuve d'ancieneté appelée fichier développeur
- [ ] Ruff clean, suite verte, git diff --check + rapport SPEC-022

**Tu as tout. Lance-toi.** Branche `agent/spec-022-cover-letter`, worktree dédié, code, tests, rapport, push.
