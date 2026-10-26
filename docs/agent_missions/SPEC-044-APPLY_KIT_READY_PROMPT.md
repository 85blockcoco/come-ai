# MISSION SPEC-044 — Postuler en un clic : dossier prêt par offre

> **Priorité : P0** — Directif Côme 26/10 : « candidater très facilement à des stages ».

## Contexte
L'app Career possède déjà les briques : variantes CV (`career/cv_variants.py`),
lettres/kit (`career/application_studio.py`), export documents (`career/document_export.py`),
réponses candidat à venir (SPEC-045). Aujourd'hui candidater demande de naviguer entre
plusieurs écrans/actions. Objectif : **un seul appel API** qui retourne un dossier prêt,
100 % action humaine ensuite (aucune soumission automatique — règle absolue).

## Mission — `career/apply_kit.py`
`POST /api/career/apply-kit/{job_id}` → `ApplyKit` :
- `variant` : meilleure variante CV matchée (réutilise les calculs existants, caches inclus) ;
- `letter` : lettre adaptée (draft existant si présent, sinon générée depuis le profil) ;
- `answers` : réponses types aux questions de formulaire (s'appuiera sur SPEC-045 si dispo,
  sinon minimal depuis le profil) ;
- `checklist` : étapes humaines restantes — pièces à joindre, dates à vérifier, deadline proche ;
- `readiness` : 0-100 + `block_reasons` si < 100 (ex. « autorisation de travail non vérifiée ») ;
- `deep_link` : URL directe du formulaire ATS si détectée (delegué à SPEC-046 si dispo) ;
- `export_urls` : PDF (CV, lettre) via l'export existant.

Contraintes : < 3 s si le kit/la préparation existe déjà pour le job ; ne JAMAIS soumettre ;
aucune écriture hors workspace ; si une pièce manque → readiness < 100 + raison claire.

## Contrats
```python
@dataclass
class ApplyKit:
    job_id: str
    readiness: int
    block_reasons: list[str]
    variant: dict | None
    letter: dict | None
    answers: dict[str, str]
    checklist: list[dict]
    deep_link: str | None
    export_urls: dict[str, str]

def build_apply_kit(job_id: str, profile: Mapping) -> ApplyKit: ...
```

## Livrables
1. `career/apply_kit.py` + endpoint via le pattern router existant.
2. Tests `tests/test_apply_kit.py` : kit complet ; kit incomplet → readiness<100+raisons ; job inconnu → erreur propre.
3. Smoke test endpoint ; ruff propre ; fixtures synthétiques uniquement.
4. Push UNIQUEMENT sur `agent/spec-044-apply-kit-ready` + rapport court `docs/agent-reports/`.

## Cadre commun (toutes missions, non négociable)
- Aucune soumission automatique de candidature ; aucune donnée réelle.
- Tests ciblés vert + `ruff check career/` ; ne pas lancer la suite complète pendant les jobs en fond.
- API via le pattern career existant, ne pas casser `schema_version=7`.
- Push UNIQUEMENT sur ta branche dédiée (jamais main) ; preuve = branche poussée + tests rejoués.
- Rapport succinct dans `docs/agent-reports/`.
