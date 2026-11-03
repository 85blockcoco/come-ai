# MISSION SPEC KIT — SK-01 : Confiance dans les sources officielles

> **Priorité : P0** — Module indépendant, worktree dédié, peut tourner en parallèle SK-02/SK-03/SK-04

---

## Contexte

L'interface affiche « Source officielle liée » à partir des métadonnées. Ce signal doit être renforcé par un **contrat de confiance déterministe** explicable, pas un booléen opaque.

---

## Nouveau module à créer

```
career/source_trust.py
tests/test_source_trust.py
tests/fixtures/source_trust/
```

---

## Résultat attendu (contrat JSON)

```json
{
  "status": "verified",
  "provider": "greenhouse",
  "canonical_host": "boards.greenhouse.io",
  "employer_match": "confirmed",
  "registry_evidence": "registry:greenhouse:example",
  "reasons": [],
  "checked_at": "..."
}
```

### Statuts autorisés
- `verified` — source confirmée (ATS connu + cohérence employeur)
- `unverified` — domaine lié mais pas prouvé officiel
- `contradictory` — incohérence détectée (ex: fournisseur connu, entreprise différente)
- `missing` — URL absente

---

## Cas obligatoires (fixtures synthétiques)

| Cas | Attendu |
|-----|---------|
| Greenhouse officiel | `verified` |
| Lever officiel | `verified` |
| Ashby officiel | `verified` |
| SmartRecruiters officiel | `verified` |
| Page carrière employeur | `verified` si domaine match |
| Domaine ressemblant officiel | `unverified` |
| Sous-domaine trompeur | `contradictory` |
| URL raccourcie | `unverified` |
| URL manquante | `missing` |
| Fournisseur connu, entreprise incohérente | `contradictory` |
| Redirection (fixture) | selon cible finale |
| Métadonnée « officielle » sans preuve | `unverified` |

---

## Contraintes non négociables

1. **Aucun booléen source ne constitue seul une preuve** — chaque décision contient `reasons[]`
2. **Aucun domaine légitime rejeté** uniquement car pas dans les 4 ATS connus
3. **Interface différencie** : vérifié / lié non vérifié / contradictoire
4. **Aucune requête réseau** dans les tests
5. **Aucune modification** interface, matching, vérification réseau réelle

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_source_trust.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `source_trust.check_trust(url, employer_hint=None) -> TrustResult` pure, déterministe
- [ ] 12+ fixtures synthétiques couvrant tous cas obligatoires
- [ ] Chaque `TrustResult` a `status`, `provider`, `canonical_host`, `employer_match`, `registry_evidence`, `reasons`, `checked_at`
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK01-SOURCE_TRUST.md`

---

## Squelette minimal

```python
# career/source_trust.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass
class TrustResult:
    status: Literal["verified", "unverified", "contradictory", "missing"]
    provider: Optional[str]           # "greenhouse", "lever", "ashby", "smartrecruiters", "employer", "unknown"
    canonical_host: Optional[str]     # ex: "boards.greenhouse.io"
    employer_match: Literal["confirmed", "mismatch", "unknown"]
    registry_evidence: Optional[str]  # ex: "registry:greenhouse:acme-corp"
    reasons: list[str]                # explications lisibles
    checked_at: str                   # ISO 8601

def check_trust(url: str, *, employer_hint: str | None = None) -> TrustResult:
    # 1. Parser URL, extraire host, path, query
    # 2. Matcher contre registre ATS connus (Greenhouse, Lever, Ashby, SmartRecruiters)
    # 3. Si ATS connu: vérifier cohérence employer_hint vs path/params
    # 4. Sinon: heuristiques domaine employeur (whois local, patterns connus)
    # 5. Détecter: raccourcis, redirections, sous-domaines trompeurs
    # 6. Construire reasons[] pour chaque décision
    # 7. Retourner TrustResult
    ...
```

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk01-source-trust`, worktree dédié, code, tests (12+ cas), rapport, push. Je relis et j'intègre.