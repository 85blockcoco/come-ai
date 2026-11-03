# MISSION SPEC KIT — SK-07 : Offer Intelligence Bridge

> **Priorité : P0 — Lot d'intégration central** — Ne commence qu'après validation SK-01→SK-06.
> Spécification Spec Kit complète existe dans worktree Spec Kit RC : `specs/003-offer-intelligence-bridge/spec.md`

---

## Objectif

Créer un **snapshot versionné unique** comprenant :
- Faits temporels (SK-02)
- Qualification contractuelle (SK-01 trust, SK-03 requirements)
- Géographie
- Langue
- Prérequis
- Contradictions
- Informations manquantes
- Empreinte du texte source
- Provenance de chaque fait

---

## Consommateurs (TOUS utilisent le MÊME snapshot)

- Explorer (liste offres)
- Matching (CV ↔ Offre)
- Fiche détaillée offre
- Préparation CV
- Lettre de motivation
- Checklist candidature

---

## Critère essentiel

**Une même exigence doit avoir le même identifiant dans tous les écrans.**

---

## Persistance

- Étendre le mécanisme existant de snapshot
- **Ne pas ajouter des dizaines de colonnes** aux offres
- Versioning par hash du texte source

---

## Import répété

| Cas | Comportement |
|-----|--------------|
| Texte identique | Mêmes identifiants dérivés (déterministe) |
| Texte modifié | Nouvelle analyse, nouveaux IDs |
| Note personnelle | Préservée |
| Shortlist | Préservée |
| Candidature | Préservée |
| Preuve obsolète | Non présentée comme actuelle |

---

## Critères de réussite

- [ ] Zéro divergence entre Explorer, détail, matching, prépa
- [ ] Tous les faits confirmés possèdent une citation (quote + offsets)
- [ ] Information manquante = « à vérifier » (pas « absente »)
- [ ] Aucun appel modèle nécessaire
- [ ] Fonctionnement hors ligne
- [ ] Snapshot versionné par hash contenu

---

## Modules

```
career/offer_intelligence.py       # Snapshot builder
career/offer_intelligence_store.py # Persistance versionnée
career/router.py                   # Endpoint GET /offer-intelligence/{offer_id}
tests/test_offer_intelligence.py
tests/fixtures/offer_intelligence/
```

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_offer_intelligence.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de validation

- [ ] `offer_intelligence.build_snapshot(offer_raw, qualified_data) -> OfferIntelligenceSnapshot`
- [ ] Snapshot contient: temporal_facts, qualifications, geo, lang, requirements, contradictions, missing, source_hash, provenance_map
- [ ] Même requirement_id partout (Explorer, matching, fiche, CV prep, lettre, checklist)
- [ ] Import répété: même hash = même IDs, hash modifié = nouvelle analyse
- [ ] Notes/shortlist/candidature préservées
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK07-OFFER_INTELLIGENCE_BRIDGE.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk07-offer-intelligence-bridge`, worktree dédié, code, tests, rapport, push. **Mission centrale d'intégration — responsabilité de l'intégrateur.** Je relis et j'intègre.