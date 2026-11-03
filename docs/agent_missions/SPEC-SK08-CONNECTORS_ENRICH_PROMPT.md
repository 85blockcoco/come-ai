# MISSION SPEC KIT — SK-08 : Enrichissement des connecteurs existants

> **Priorité : P0** — Après SK-01/SK-02/SK-03 validés.

---

## Objectif

Faire remonter dans le contrat commun les informations **déjà présentes** dans les réponses des sources.

### Connecteurs concernés (8)

- Greenhouse
- Lever
- Ashby
- SmartRecruiters
- Welcome to the Jungle
- JobTeaser
- Talent.com
- APEC

---

## Problème réel constaté

Plusieurs connecteurs renvoient encore :
```python
posted_date = ""
start_date = ""
deadline_date = ""
duration_months = None
requirements = ""
```
alors que certaines informations sont présentes dans le texte ou champs structurés.

---

## Règles non négociables

1. **Le connecteur transmet la matière source** — pas de logique de qualification
2. **`offer_dates` (SK-02) traite les dates**
3. **`offer_requirements` (existant) traite les prérequis**
4. **`source_trust` (SK-01) traite la confiance**
5. **Toute valeur structurée garde le nom du champ source** (ex: `greenhouse.posted_at`)
6. **Contradiction champ structuré vs description = conservée** (pas tranchée)

---

## Champs à remonter par connecteur (exemples)

| Connecteur | Champs disponibles | À mapper vers |
|------------|-------------------|---------------|
| Greenhouse | `posted_at`, `updated_at`, `requisition_id`, `content` | `source_fields.greenhouse.posted_at`, `description_original` |
| Lever | `posted`, `requisition`, `description` | `source_fields.lever.posted`, `description_original` |
| Ashby | `published_at`, `employment_type`, `description` | `source_fields.ashby.published_at`, `description_original` |
| SmartRecruiters | `postedDate`, `jobAd.sections`, `requisitionId` | `source_fields.smartrecruiters.postedDate`, `description_original` |
| WJ | `date`, `contract_type`, `description` | `source_fields.welcome_jungle.date`, `description_original` |
| JobTeaser | `start_date`, `contract_type`, `description` | `source_fields.jobteaser.start_date`, `description_original` |
| Talent.com | `date_posted`, `job_type`, `description` | `source_fields.talent_com.date_posted`, `description_original` |
| APEC | `date_publication`, `type_contrat`, `description` | `source_fields.apec.date_publication`, `description_original` |

---

## Validation

- 1 fixture synthétique par fournisseur (8 total)
- Contrôle réel borné et séparé quand conditions source le permettent

---

## Modules à modifier

```
career/connectors/greenhouse.py
career/connectors/lever.py
career/connectors/ashby.py
career/connectors/smartrecruiters.py
career/connectors/welcome_jungle.py
career/connectors/jobteaser.py
career/connectors/talent_com.py
career/connectors/apec.py
tests/test_connectors_enrich.py
tests/fixtures/connectors_enrich/
```

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_connectors_enrich.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] 8 connecteurs enrichis avec `source_fields.*` et `description_original` peuplés
- [ ] Aucune logique de qualification dans connecteurs
- [ ] Noms champs sources préservés
- [ ] Contradictions conservées
- [ ] 8 fixtures synthétiques + contrôles réels séparés
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK08-CONNECTORS_ENRICH.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk08-connectors-enrich`, worktree dédié, code, tests (8 fixtures + réels), rapport, push. Je relis et j'intègre.