# MISSION SPEC-018 — Web Researcher Intelligence (recherche internet par stage)

> **Priorité : P1** — Alimente reformulations CV/lettre avec du contexte internet. Worktree dédié.

## Contexte
Une lettre / CV de stage gagne à connaître **l'entreprise** : stack technique, actualités récentes,
produits, valeurs, technologies demandées. Objectif : automate la **recherche internet** et rendre
ces faisaisons traçables (source, url, extrait).

## Sources internet
1. **Offre pipe** (SK-02 ; offre déjdé) — dès fiches_connul.
2. **Site entreprise** — accueil, /about, /careers, /engineering-blog.
3. **GitHub organisation** — repo public, langages main, releases récentes.
4. **Moteur (fetch)** — query ville + nom entreprise, thème, saisie synthtique.

## Modules
```
career/web_research.py        # orchestrateur recherche (async, cache 24h)
career/web_sources.py         # fetchers site + github + recherche d'index
career/web_evidence.py        # renvoyer des "web" EvidenceItem avec url + extrait
tests/test_web_research.py
docs/agent-reports/SPEC-018-WEB_RESEARCHER.md
```

## Contrats
```python
@dataclass
class WebFacts:
    company: str
    stack: list[str]                    # ex: ["python", "k8s", "spark"]
    values: list[str]
    recent_news: list[WebNewsHit]
    repos_summary: dict                 # langues, top-requested  / stars
    evidence_ids: list[str]             # ← preuves SD (SPEC-018)
    fetched_at: str
    confidence: float

@dataclass
class WebNewsHit:
    title: str
    url: str
    date: str | None
    excerpt: str
```

## Règles
- **Zona fluide**: déniation toujours traço (url + extrait cité, pas de remplissage inventé).
- Cache 24h par domain; respect de robots.txt sans bloquer le cas usuel.
- PRC/engineering language regardé en premier (`skills.yaml` existants).
- Si non intrusis net (entreprise très ciblé), `confidence` baisse et un rapport public.

## API
```
GET  /web/research/{offer_id}          # WebFacts complet + evidence_ids
POST /web/research/{offer_id}/provide  # injection utilisateur (fiche entreprise perso)
GET  /web/research/{offer_id}/freshness
```

## Validation
```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_web_research.py
.venv/bin/python -m pytest -q
git diff --check
```

## Critères de réussite
- [ ] WebFacts extrait avec preuves URLDL (pas d'invention)
- [ ] Test offline (sans réseau) → degrade gr的环境中 reuse cache + fixtures
- [ ] Intégration dans evidence center (où la preuve web est classable)
- [ ] Ruff clean, suite verte, git diff --check + rapport SPEC-018

**Tu as tout. Lance-toi.** Branche `agent/spec-018-web-researcher`, worktree dédié, code, tests, rapport, push.
