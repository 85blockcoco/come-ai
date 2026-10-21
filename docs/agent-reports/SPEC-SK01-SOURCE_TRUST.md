# SPEC-SK01 — Confiance dans les sources officielles

**Mission** : CVBOOST-22 — SK-01 — contrat de confiance déterministe pour le lien officiel d'une offre
**Branche** : `agent/spec-sk01-source-trust` (worktree dédié `AI-Excel-Agent-worker-cvboost-22-1792596946`)
**Base** : `main` (`a054c97`)
**Date** : 2026-10-21
**Auteur** : Worker Mission CVBOOST-22

---

## 1. Problème treated

L'interface affiche « Source officielle liée » à partir d'une métadonnée (`official_url` + `source_name` +
`source_verified`). Ce signal est un **booléen opaque** : il ne dit ni *ce qui* a été prouvé, ni *sur quoi*,
ni *ce qui reste à vérifier*. Il est de plus **faux par construction** dans deux cas :

- un `source_verified=True` posé par un connecteur ne prouve rien sur le *domaine* du lien ;
- une URL ressemblante à un ATS (`greenhouse-jobs.exemple.test`) passe pour une source Greenhouse.

SK-01 remplace ce booléen par un **contrat JSON explicable, déterministe et rejouable**.

> Portée volontairement limitée : **aucune modification de l'interface, du matching, ni de la vérification
> réseau réelle** (contrainte 5 de la mission). Le module est livré seul, prêt à être branché.

---

## 2. Fichiers créés

| Fichier | Rôle |
|---------|------|
| `career/source_trust.py` | Module de confiance : `check_trust(...) -> TrustResult` + contrat JSON |
| `tests/test_source_trust.py` | 66 tests synthétiques (20 cas de fixtures + invariants + régressions) |
| `tests/fixtures/source_trust/trust_cases.json` | 20 cas synthétiques (les 12 cas obligatoires + 8 cas limites) |
| `tests/fixtures/source_trust/redirects.json` | Cibles de redirection synthétiques (le raccourcisseur n'est jamais contacté) |
| `docs/agent-reports/SPEC-SK01-SOURCE_TRUST.md` | Ce rapport |

**Aucun fichier existant n'a été modifié** (interface, matching, connecteurs, registre curaté : intacts).

---

## 3. Le contrat

```python
@dataclass(frozen=True)
class TrustResult:
    status: Literal["verified", "unverified", "contradictory", "missing"]
    provider: Optional[str]           # greenhouse | lever | ashby | smartrecruiters | employer | unknown
    canonical_host: Optional[str]     # hôte réellement observé (jamais l'hôte imité)
    employer_match: Literal["confirmed", "mismatch", "unknown"]
    registry_evidence: Optional[str]  # "registry:<provider>:<token>" — la preuve qui soutient la décision
    reasons: list[str]                # explications lisibles, jamais vides
    checked_at: str                   # ISO 8601 (horloge injectable)
```

`TrustResult.to_dict()` renvoie exactement les 7 clés ci-dessus : c'est le contrat JSON destiné à l'interface.

### 3.1 Signatures

```python
check_trust(
    url: str,
    *,
    employer_hint: str | None = None,      # l'employeur que le lien est censé désigner
    declared_provider: str | None = None,  # la source déclarée par les métadonnées (une affirmation)
    final_url: str | None = None,          # cible déjà résolue d'un lien raccourci
    clock: Callable[[], str] | None = None,# horloge injectable => décision rejouable
) -> TrustResult
```

L'appel minimal de la mission reste valide : `check_trust(url, employer_hint=None)`.

### 3.2 Statuts

| Statut | Signification | Preuve exigée |
|--------|---------------|---------------|
| `verified` | source confirmée | ATS connu **et** cohérence employeur **et** hôte de board officiel |
| `unverified` | domaine lié, pas encore prouvé | aucune preuve ne rattache le lien à un employeur |
| `contradictory` | incohérence détectée | le lien contredit l'employeur, la source déclarée, ou imite un domaine officiel |
| `missing` | URL absente ou inexploitable | — |

### 3.3 `registry_evidence` — la preuve qui soutient la décision

`registry_evidence` **n'est renseigné que si et seulement si `status == "verified"`** (invariant vérifié par
test). Il désigne l'enregistrement qui prouve la décision :

| Forme | Signification |
|-------|---------------|
| `registry:greenhouse:acme-corp` | board **enregistré dans le registre curaté** (`career/source_registry.py`), preuve la plus forte : provenance + date de vérification |
| `registry:greenhouse:acme-corp` | board **déduit** d'un domaine ATS officiel + d'un jeton cohérent avec l'employeur (preuve structurelle, pas un enregistrement) |
| `registry:employer:acme-corp.com` | **domaine de l'employeur** : le domaine est celui de l'employeur annoncé (preuve : le domaine lui-même) |

Les trois formes sont distinguables dans `reasons[]` : la ligne « Preuve : … » dit explicitement de quelle
preuve il s'agit, et si un enregistrement curaté existe ou non.

---

## 4. Règles de décision

Ordre d'évaluation (aucune requête réseau à aucun moment) :

1. **URL vide / schéma non http(s) / identifiants dans l'URL / port invalide** → `missing`.
2. **Raccourcisseur connu** (`bit.ly`, `t.co`, `tinyurl.com`, …) :
   - cible inconnue → `unverified` (un lien raccourci ne prouve jamais rien sans requête réseau) ;
   - cible fournie par l'appelant (`final_url`) → la décision suit **la cible finale**, avec une raison
     « URL raccourcie résolue vers … ».
3. **Hôte officiel d'un ATS connu** (Greenhouse, Lever, Ashby, SmartRecruiters, y compris les hôtes API
   documentés) → le **jeton de board** est lu selon la disposition documentée de chaque fournisseur.
4. **Imitation d'un domaine officiel** (`boards.greenhouse.io.exemple.test`) → `contradictory` : l'hôte
   imite un domaine mais n'est pas contrôlé par le fournisseur.
5. **Hôte sous le domaine du fournisseur, non documenté comme hôte de board** (`custom.greenhouse.io`) →
   fournisseur identifié, décision employeur classique, la nature de l'hôte est signalée dans les raisons.
6. **Domaine ressemblant** (`greenhouse-jobs.exemple.test`) → `unverified` : la mention d'une marque ne
   prouve jamais une source officielle.
7. **Domaine d'employeur** (hors ATS) → la cohérence avec `employer_hint` décide.

### 4.1 Cohérence employeur

| Cas | Règle |
|-----|-------|
| Employeur connu + jeton de board identique (comparaison sans accents, sans casse, sans séparateurs) | `confirmed` → `verified` |
| Employeur connu + board enregistré au registre curaté sous un autre jeton | `mismatch` → `contradictory` |
| Employeur connu + jeton sans lien | `mismatch` → `contradictory` |
| Employeur connu + jeton opaque (UUID, identifiant numérique) | `unknown` → `unverified` (impossible de comparer) |
| Aucun employeur fourni | `unknown` → `unverified` |
| Domaine d'employeur + étiquette de domaine cohérente | `confirmed` → `verified` |
| Domaine d'employeur + étiquette incohérente | `mismatch` → `contradictory` |

Règle anti-faux-positif : une correspondance par *containment* exige au moins 4 caractères distinctifs
(`"clever.com"` ne contient donc pas le nom `"lever"`), et la détection de marque repose sur des
segments de libellé entiers (`greenhouse-jobs` → `greenhouse`), jamais sur une sous-chaîne arbitraire.

### 4.2 Ce qui **ne** constitue jamais une preuve

- un `source_verified=True` / un `source_name` déclaré : c'est une **affirmation**. Elle est confrontée à
  l'URL observée ; si elle contredit le fournisseur observé, la décision devient `contradictory` ; si elle
  n'est pas confirmée, elle est signalée comme telle et **ne change pas la décision** ;
- un lien en `http` (non chiffré) : une décision `verified` est **retrogradée** en `unverified` ;
- un port non standard : idem ;
- une redirection non résolue : `unverified` ;
- un domaine ressemblant à un fournisseur : `unverified` ;
- un board hébergé sur un ATS connu mais sans aucun rattachement à un employeur : `unverified`.

---

## 5. Les 12 cas obligatoires

| # | Cas | Fixture | Attendu | Obtenu |
|---|-----|---------|---------|--------|
| 1 | Greenhouse officiel | `job-boards.greenhouse.io/acme-corp/jobs/4217` + *Acme Corp* | `verified` | ✅ `registry:greenhouse:acme-corp` |
| 2 | Lever officiel | `jobs.lever.co/acme-corp/2f3a-4b1c` + *Acme Corp* | `verified` | ✅ `registry:lever:acme-corp` |
| 3 | Ashby officiel | `jobs.ashbyhq.com/acme-corp/9d1e` + *Acme* | `verified` | ✅ `registry:ashby:acme-corp` |
| 4 | SmartRecruiters officiel | `jobs.smartrecruiters.com/AcmeCorp/743999` + *Acme Corp* | `verified` | ✅ `registry:smartrecruiters:AcmeCorp` |
| 5 | Page carrière employeur | `careers.acme-corp.com/jobs/finance-intern` + *Acme Corp* | `verified` | ✅ `registry:employer:acme-corp.com` |
| 6 | Domaine ressemblant officiel | `greenhouse-jobs.acme.test/...` | `unverified` | ✅ provider `unknown` |
| 7 | Sous-domaine trompeur | `boards.greenhouse.io.acme.test/...` | `contradictory` | ✅ provider `greenhouse` (imité), hôte observé conservé |
| 8 | URL raccourcie | `bit.ly/3xY2zAcme` | `unverified` | ✅ cible non résolue |
| 9 | URL manquante | `""` | `missing` | ✅ |
| 10 | Fournisseur connu, entreprise incohérente | `boards.greenhouse.io/other-corp/...` + *Acme Corp* | `contradictory` | ✅ `employer_match=mismatch` |
| 11 | Redirection (fixture) | `bit.ly/3xY2zAcme` → `job-boards.greenhouse.io/acme-corp/...` | selon cible finale | ✅ `verified` |
| 12 | Métadonnée « officielle » sans preuve | `careers.acme-corp.example/...` + source déclarée `greenhouse` | `unverified` | ✅ la source déclarée ne prouve rien |

8 cas supplémentaires couvrent : ATS connu sans indice employeur (`unverified`), domaine employeur en
contradiction (`contradictory`), lien `http` (retrogradé), identifiants dans l'URL et `javascript:` (`missing`),
hôte de board non documenté sous le domaine du fournisseur, conflit de source déclarée, jeton de board opaque,
port non standard / port invalide, casse de l'hôte, paramètres de tracking, et les quatre dispositions d'URL
documentées des API publiques.

---

## 6. Contraintes non négociables

| # | Contrainte | Comment elle est tenue | Preuve |
|---|-----------|------------------------|--------|
| 1 | Aucun booléen source ne constitue seul une preuve | `source_verified` / `source_name` ne sont jamais lus ; seule la source déclarée est confrontée à l'URL | `test_a_source_flag_alone_never_proves_an_official_source`, cas 12 |
| 2 | Aucun domaine légitime rejeté uniquement car hors des 4 ATS | Un domaine d'employeur cohérent est `verified` ; `test_a_legitimate_employer_domain_outside_the_four_ats_is_not_rejected` | test dédié |
| 3 | L'interface différencie vérifié / lié non vérifié / contradictoire | 4 statuts distincts + `STATUS_LABELS` ; l'interface n'est **pas** modifiée (contrainte 5) | `test_the_interface_can_differentiate_the_three_states` |
| 4 | Aucune requête réseau dans les tests | `socket` neutralisé en fixture autouse ; aucun client HTTP dans le module | `deny_network` |
| 5 | Aucune modification interface / matching / vérification réseau | Seuls des fichiers **nouveaux** sont livrés | `git diff --stat` (4 fichiers ajoutés, 0 modifié) |

Autres garanties :

- **déterminisme** : horloge injectable, aucun état ambiant, aucune dépendance à l'ordre des fixtures ;
  `test_decision_is_deterministic_and_replayable` ;
- **explication obligatoire** : `reasons` ne peut jamais être vide (invariant vérifié sur les 20 fixtures) ;
- **raccourci non résolu** : jamais `verified` ;
- **URL inexploitable** : jamais une source.

---

## 7. Raccordement de l'interface (non fait ici)

`career_static/career.js` (ligne ~2600) affiche aujourd'hui :

```js
if (job.official_url && job.source_name && job.source_name !== "manual") {
  trust.append(chip("Source officielle liée", "good"));
} else if (job.official_url) {
  trust.append(chip("Lien fourni · origine à vérifier", "warning"));
} else {
  trust.append(chip("Lien officiel manquant", "warning"));
}
```

Le contrat livré permet de remplacer ce booléen par quatre états, **sans toucher au backend de découverte** :

| `status` | Chip proposée | `chip(..., kind)` |
|----------|---------------|-------------------|
| `verified` | « Source officielle vérifiée » | `good` |
| `unverified` | « Source liée · non vérifiée » | `warning` |
| `contradictory` | « Source contradictoire · à vérifier » | `warning` |
| `missing` | « Source officielle manquante » | `warning` |

et d'afficher `reasons[0]` (ou la liste) sous la chip, pour que la décision soit **explicable** et non
seulement affichée. Le module expose `STATUS_LABELS` / `status_label()` pour ce vocabulary.

**Ce raccordement est hors périmètre de SK-01** (contrainte 5) : il est laissé à une mission d'interface
ultérieure, qui consummera `TrustResult.to_dict()`.

---

## 8. Limites assumées

1. **Aucune preuve réseau** : une redirection n'est résolue que si l'appelant fournit la cible finale ;
   une URL qui demande un login reste `unverified`.
2. **Le suffixe public** est une liste courte et explicite (suffixes multi-étiquettes courants) : un TLD
   exotique non listé est traité comme un suffixe simple. Effet : le domaine registrable peut être calculé
   approximativement pour un pays rare — la décision reste `unverified` dans ce cas, jamais `verified` par
   erreur.
3. **Un board enregistré au registre curaté** est une preuve *historique* : le registre documente que la
   source a été identifiée depuis la page carrière officielle de l'employeur, à une date donnée. Il ne
   garantit pas que la source est encore en ligne aujourd'hui.
4. **Hôte sous le domaine du fournisseur, non documenté** (`custom.greenhouse.io`) : le fournisseur est connu
   et le jeton peut être cohérent, la décision peut donc être `verified` ; la nature non documentée de
   l'hôte est toujours signalée dans les raisons.
5. Le module ne **contacte** rien : il ne vérifie pas que l'offre est encore publiée. SK-01 porte sur la
   *confiance dans la source*, pas sur la *fraîcheur de l'offre*.

---

## 9. Validation

```bash
VENV_PY=/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python ./checklist_codex.sh main   # TOUT VERT
.venv/bin/python -m pytest -q tests/test_source_trust.py                                   # 66 passed
.venv/bin/python -m pytest -q                                                            # 1439 passed, 1 skipped
.venv/bin/python -m ruff check .                                                         # All checks passed!
git diff --check                                                                         # propre
```

| Mesure | Avant | Après |
|---------|-------|-------|
| Tests (suite complète) | 1373 passed, 1 skipped | **1439 passed, 1 skipped** (+66, aucune régression) |
| `ruff check .` | All checks passed | All checks passed |
| Fichiers modifiés | — | 0 (4 fichiers ajoutés) |

---

## 10. Ce que la mission a produit, en une phrase

Un contrat de confiance déterministe et explicable (`verified` / `unverified` / `contradictory` / `missing`)
où chaque décision cite sa preuve (`registry_evidence`) et sa raison (`reasons[]`), capable de distinguer
une page carrière d'employeur d'un lien qui *imite* un ATS, sans jamais faire de requête réseau et sans
jamais rejeter un domaine légitime simplement parce qu'il n'est pas chez Greenhouse, Lever, Ashby ou
SmartRecruiters.
