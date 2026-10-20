# HANDOFF — Agent Career

**Destinataire** : Agent Career (Codex / autre)
**Émetteur** : Audit nocturne
**Base** : `main` (`ed8a6b9`) — Stage Hunter **livré**

---

## 1. État actuel dans `main`

- Stage Hunter opérationnel : `/career#career/stagehunter`
- 159 tests ciblés + 681 DevKit verts
- Preuve navigateur réelle (port 8877, base synthétique)
- Découverte : **seulement** boards Greenhouse configurés explicitement (max 8)
- Classement : lexical explicable, pas probabiliste

---

## 2. Ce qui manque / à intégrer

| Artefact | Emplacement | Contenu |
|---|---|---|
| **Catalogue de sources** | `feature/career-sources-overnight` / `career_source_hunter/` | 3 472 offres observées, **15 stages finance confirmés**, 9 boards découverts, classifieur 2 axes testé |
| **Mode « Explorer »** | **Introuvable** partout | Non implémenté → soit le coder, soit le retirer des promesses |

---

## 3. Tâches

1. **Intégrer le catalogue** : câbler `career_source_hunter/` (offres + provenance) dans le moteur central de découverte, sans régresser Stage Hunter.
2. **Clarifier « Explorer »** : implémenter un onglet/recherche catalogue, ou documenter qu'il n'existe pas.
3. **Gardes faux positifs** : documenter les warnings existants (ex. `"full time"` dans `_PERMANENT_CONTRACT_PATTERNS` → avertissement sur « Full-time Intern »).

---

## 4. Preuves d'acceptation

```bash
# Dans le worktree Career après intégration
cd ~/AI-Excel-Agent-career   # ou worktree cible
.venv/bin/python -m pytest -q tests/test_career_stage_hunter.py tests/test_career_agent.py

# Test navigateur synthétique (port libre)
# - onglet catalogue visible
# - 15 stages finance confirmés atteignables
# - aucun appel LinkedIn/banques universel
```

---

## 5. Fichiers concernés

- `career/service.py` (découverte, cache)
- `career/discovery.py` (connecteur Greenhouse)
- `career/stage_search.py` (classement, warning `full time`)
- `career_static/` (UI catalogue/Explorer)
- `career_source_hunter/` (à consommer, puis archiver)

---

## 6. Interdits

- Pas de recherche universelle LinkedIn / banques / fonds.
- Pas de soumission de candidature automatique.
- Pas d'appel payant pour la validation.
- Pas de régression Stage Hunter.

---

## 7. Contacts

- Agent Mémoire : partage profil / mémoire pour candidature
- Agent Study Coach : préparation entretien (questions)
- Agent Codex : validation globale