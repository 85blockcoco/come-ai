# MISSION AGENT — Extension des sources de stages (Mission 06)

> **Contexte** : l'utilisateur ne trouve que ~120 offres par exploration, majoritairement Greenhouse (85 %), sans `employment_type`, `posted_date`, `country`. Il faut **ajouter 2–4 sources réellement démontrables** (pages carrières officielles) avec connecteurs bornés, santé de source, et **aucune invention**.
> Base : `main` après intégration CVBOOST (tag `v2-cvboost-integrated-2026-10-20`, SHA `d6e2985`), 1259 tests verts.

---

## Périmètre autorisé (fichiers que tu PEUX toucher)

| Fichier | Rôle |
|---|---|
| `career/connectors/__init__.py` | registre des connecteurs (`CONNECTOR_REGISTRY`, `register_connector`) |
| `career/connectors/public_ats.py` | connecteurs Greenhouse/Ashby/Lever/SmartRecruiters existants — **étendre seulement** |
| `career/connectors/new_source_*.py` | **nouveaux fichiers** pour chaque source (ex. `welcome_jungle.py`, `jobteaser.py`, `linkedin_career.py`, `apec.py`, `talent_com.py`, `indeed_ats.py` — choisis 2–4) |
| `career/discovery.py` | fonction `discover_stage_offers()` : ajouter l'appel des nouveaux connecteurs dans la boucle |
| `career/stage_search.py` | vocabulaire `stage_search_vocabulary()` : ajouter les nouveaux `source_name` pour l'UI |
| `career/models.py` | si nouveau champ commun (ex. `source_health`) — **uniquement si nécessaire** |
| `tests/test_*_connector.py` | **un fichier de test par source** (fixtures synthétiques uniquement) |
| `docs/agent-reports/CVBOOST-06-SOURCES.md` | ton rapport obligatoire |

**Interdiction formelle** : tout autre fichier (`career/service.py`, `career/router.py`, `career_static/*`, `requirements*.txt`, migrations, `SCHEMA_VERSION`).

---

## Contraintes produit (non négociables)

1. **Règle utilisateur R1** : destinations 100 % hors France — tes connecteurs doivent **filtrer côté source** (paramètre `country`/`location`) ou le marquer pour exclusion ultérieure.
2. **Règle utilisateur R2** : résumé complet — chaque offre rapportée doit avoir **provenance exacte** (URL officielle, sélecteur CSS/XPath documenté).
3. **Zéro invention** : si une page est injoignable, HTML malformé, ou champ absent → **aucune offre fabriquée**, compteur d'échec incrémenté, log explicite.
4. **Connecteur borné** : chaque source a **timeout ≤ 15 s**, **max_pages ≤ 5**, **rate_limit ≥ 2 s/requête**, **user-agent identifié** (`ComeAI-StageBot/1.0`).
5. **Santé de source** : chaque connecteur expose `health_check()` → `{last_ok, last_error, consecutive_failures, raw_offers, valid_offers, finance_offers, stage_offers, conforming_offers, to_verify_offers}`.
6. **Pas de doublons gonflés** : déduplication par `canonical_url` + `external_id` + `company` + `title` + `location` (la logique existe dans `job_deduplication.py` — tu la réutilises, tu ne la réécris pas).
7. **Opt-in explicite** : l'utilisateur coche la source dans l'UI avant la première exploration (pas d'activation par défaut).
8. **Tests** : fixtures **synthétiques uniquement** (HTML factice dans le test, aucun fichier réel, aucune donnée personnelle).

---

## Livrables obligatoires

1. **Branche** `agent/cvboost-06-sources` (worktree dédié, créé par toi).
2. **2 à 4 connecteurs** dans `career/connectors/` + enregistrement dans `CONNECTOR_REGISTRY`.
3. **Intégration** dans `discover_stage_offers()` (appel conditionnel si source activée).
4. **Tests** : `tests/test_<source>_connector.py` — 10+ cas par source (HTML valide, HTML vide, 404, timeout, pagination, champs manquants, déduplication).
5. **Rapport** `docs/agent-reports/CVBOOST-06-SOURCES.md` contenant :
   - Sources choisies + justification (page carrière officielle, date de vérification).
   - Pour chaque source : `raw_offers`, `valid_offers`, `finance_offers`, `stage_offers`, `conforming_offers`, `to_verify_offers` mesurés sur 3 runs réels.
   - Preuves de santé (logs `health_check`).
   - Preuves d'absence d'invention (cas d'échec gérés).
   - Captures d'écran optionnelles (navigateur headless loopback).
6. **Checklist Codex** : `./checklist_codex.sh` vert (sauf étape 5 préexistante).

---

## Ordre de travail suggéré

1. **Choisis 2–4 sources** parmi : Welcome to the Jungle, JobTeaser, APEC, LinkedIn Career Pages, Talent.com, Indeed (ATS), Glassdoor, Company career pages directes (ex. BNP Paribas, Société Générale, Amundi, Crédit Agricole, BNP, HSBC, Deutsche Bank, JP Morgan, Goldman, Morgan Stanley, Rothschild, Lazard, Centerview, Perella, Evercore, Moelis, BNP Paribas Asset Management, Amundi, Carmignac, Oddo BHF, Lazard Frères, Rothschild & Co, Kepler Cheuvreux, Bryan Garnier, Alantra, Greenhill, PJT Partners, Houlihan Lokey, William Blair, Stifel, Piper Sandler, Jefferies, Baird, Needham, Cowen, Raymond James, Macquarie, Nomura, Mizuho, SMBC, Daiwa, MUFG).
2. **Pour chaque source** : écris le connecteur → test unitaire → health check → intégration discovery.
3. **Exécute 3 explorations réelles** (sans réseau pour les tests, avec réseau borné pour les mesures de santé — note les métriques).
4. **Écris le rapport** et pousse la branche.

---

## Commandes de validation (tu les lances avant de dire « fini »)

```bash
# Dans ton worktree
./checklist_codex.sh
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q tests/test_*_connector.py
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q
git diff --check
```

---

## Exemple de squelette de connecteur (à copier-coller)

```python
# career/connectors/welcome_jungle.py
from __future__ import annotations
import re, time, urllib.request
from dataclasses import dataclass
from typing import Iterator
from career.connectors.public_ats import register_connector, ConnectorBase, RawOffer

@dataclass
class WelcomeJungleHealth:
    last_ok: bool = False
    last_error: str | None = None
    consecutive_failures: int = 0
    raw_offers: int = 0
    valid_offers: int = 0
    finance_offers: int = 0
    stage_offers: int = 0
    conforming_offers: int = 0
    to_verify_offers: int = 0

_HEALTH = WelcomeJungleHealth()
_BASE = "https://www.welcometothejungle.com/fr/jobs"
_TIMEOUT = 15
_MAX_PAGES = 5
_RATE = 2.0

def _fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": "ComeAI-StageBot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        _HEALTH.last_error = str(e)
        _HEALTH.consecutive_failures += 1
        return None

def health_check() -> dict:
    return {k: getattr(_HEALTH, k) for k in WelcomeJungleHealth.__dataclass_fields__}

def iter_offers(query: str = "stage finance", location: str = "europe") -> Iterator[RawOffer]:
    # TODO: vraie pagination, sélecteurs, mapping vers RawOffer
    # Respecte _MAX_PAGES, _RATE, _TIMEOUT, santé
    yield  # placeholder

register_connector("welcome_jungle", iter_offers, health_check)
```

---

## Critères de validation (ce que je vérifierai comme relecteur)

- [ ] 2–4 sources réelles, pages carrières officielles documentées.
- [ ] Connecteurs bornés (timeout, pages, rate, UA).
- [ ] `health_check()` fonctionnel, métriques rapportées.
- [ ] Filtrage France appliqué (paramètre ou post-filtre documenté).
- [ ] Zéro invention : cas d'erreur gérés, compteurs d'échec.
- [ ] Tests synthétiques ≥ 10 par source.
- [ ] Suite globale ≥ 1259 tests (pas de régression).
- [ ] Rapport complet avec métriques de 3 runs réels.
- [ ] `main` non touché, branche `agent/cvboost-06-sources` prête.

---

**Tu as tout. Lance-toi.** Branche, worktree, code, tests, rapport, push. Je relis et j'intègre.