# MISSION SPEC-046 — Détection plateforme ATS & guide humain

> **Priorité : P0** — L'utilisateur clique « postuler » sans savoir ce qui l'attend.

## Mission — `career/ats_guide.py`
- `detect_platform(url, source_name="") -> str | None` : reconnaissance statique
  (regex URL + nom de source) : greenhouse, lever, workday/myworkdayjobs, smartrecruiters,
  recruitcrm, breezy, jobvite, ashby, ripplematch, custom.
- `human_apply_guide(job) -> ApplyGuide` :
  * `apply_url` : URL directe du formulaire si pattern connu, sinon official_url ;
  * `steps` : étapes humaines numérotées par plateforme (ex. greenhouse : CV upload →
    profil → screening questions → review+submit) avec champs attendus par étape
    (mapper vers les quick-answers SPEC-045) ;
  * `needs_account`, `estimated_minutes` par plateforme ;
  * URL inconnue → platform=None + guide générique honnête ;
  * URL suspecte (injection, hors-liste de domaines) → refus propre.
- Endpoint `GET /api/career/ats-guide/{job_id}`. Aucune requête HTTP sortante.

## Contrats
```python
@dataclass
class GuideStep: title: str ; fields: list[str] ; tips: str
@dataclass
class ApplyGuide: platform: str | None ; apply_url: str ; steps: list[GuideStep] ; needs_account: bool ; estimated_minutes: int
```

## Livrables
1. Module + endpoint, smoke test.
2. Tests : ≥ 6 plateformes ; URL inconnue ; URL malveillante refusée.
3. Ruff ; fixtures synthétiques ; push sur `agent/spec-046-ats-guide-human`.

## Cadre commun (toutes missions, non négociable)
- Aucune soumission automatique de candidature ; aucune donnée réelle.
- Tests ciblés vert + `ruff check career/` ; ne pas lancer la suite complète pendant les jobs en fond.
- API via le pattern career existant, ne pas casser `schema_version=7`.
- Push UNIQUEMENT sur ta branche dédiée (jamais main) ; preuve = branche poussée + tests rejoués.
- Rapport succinct dans `docs/agent-reports/`.
