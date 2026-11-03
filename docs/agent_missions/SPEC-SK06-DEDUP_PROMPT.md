# MISSION SPEC KIT — SK-06 : Déduplication multi-sources avec conservation des preuves

> **Priorité : P0** — Consolider l'existant (`career/job_deduplication.py` dans worktrees), pas créer v3.

---

## Contexte

Travaux de déduplication déjà présents dans certains worktrees. L'agent doit **retrouver et comparer** les contributions existantes autour de `career/job_deduplication.py` et reprendre le meilleur lot.

---

## Avant d'écrire : Recherche obligatoire

L'agent doit :
1. Explorer les worktrees existants pour `career/job_deduplication.py`
2. Comparer les implémentations
3. Reprendre la meilleure plutôt que repartir de zéro

---

## Règles de rapprochement (dans l'ordre de priorité)

1. **Identifiant externe** (ex: Greenhouse job_id)
2. **URL canonique** (sans params tracking, normalisée)
3. **Entreprise canonique** (normalisation nom, alias)
4. **Titre normalisé** (lowercase, stopwords, synonymes)
5. **Lieu** (ville, région, pays, remote)
6. **Date** (publication, début, fraîcheur)
7. **Similarité texte** (Jaro-Winkler ≥ 0.92, embeddings si dispo)
8. **Traductions** (même offre FR/EN)
9. **Alias d'entreprise** (Acme Corp = Acme Inc.)

---

## Garde-fous non négociables

| Règle | Description |
|-------|-------------|
| Score pertinence utilisateur | **Ne décide jamais** qu'il s'agit d'un doublon |
| Provenances | **Toutes conservées** (merged_from list) |
| Contradictions | **Restent visibles** (dates diff, lieux diff, etc.) |
| Source officielle | **Reste principale** (source_trust verified > unverified) |
| Sources secondaires | **Restent consultables** |
| Traduction | **Ne fusionne pas** uniquement sur quelques mots communs |
| Rôles différents | **Jamais fusionnés** même entreprise (ex: "Dev" vs "PM") |

---

## Corpus minimal : 100+ cas synthétiques

| Type de cas | Exemple |
|-------------|---------|
| Doublons exacts | Même Greenhouse ID |
| URLs avec paramètres | `?utm_source=...` vs URL propre |
| Greenhouse + Page employeur | Même offre, 2 sources |
| Même rôle traduit | "Software Engineer" / "Ingénieur Logiciel" |
| Titre proche, rôle différent | "Senior Dev" vs "Junior Dev" |
| Ville différente | Paris vs Lyon (même entreprise) |
| Même entreprise avec alias | "Acme Corp" vs "Acme Inc." |
| Réouverture ancienne annonce | Même rôle, date publication différente |
| Dates incompatibles | Début jan 2025 vs juin 2025 |

---

## Modules

```
career/job_deduplication.py      # Consolidé (existant)
tests/test_job_deduplication.py  # 100+ cas
tests/fixtures/job_deduplication/
```

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_job_deduplication.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] Implémentation consolidée depuis worktrees existants
- [ ] 9 critères de rapprochement implémentés
- [ ] 6 garde-fous respectés
- [ ] 100+ cas synthétiques passent
- [ ] `merged_from` trace toutes provenances
- [ ] Contradictions visibles dans résultat
- [ ] Source officielle (SK-01 verified) reste principale
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK06-DEDUP.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk06-dedup`, worktree dédié, **d'abord rechercher l'existant**, puis consolider, tests (100+ cas), rapport, push. Je relis et j'intègre.