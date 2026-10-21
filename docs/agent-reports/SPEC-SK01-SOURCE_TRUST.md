# SPEC-SK01 — Confiance dans les sources officielles

**Mission** : CVBOOST-22 (SPEC-KIT SK-01)

**Branche mission** : `agent/spec-sk01-source-trust`

**Branche worker** : `worker/cvboost-22-1792596639`

**Base** : `main` (SHA de base `a054c97`, contient `origin/main` `bc5db69` — dépendances Mission 06 incluses)

**Date** : 2026-10-21

**Auteur** : Agent Worker SK-01

---

## 1. Problème traité

L'interface affiche « Source officielle liée » à partir d'une métadonnée unique
(`source_verified`). Ce booléen est opaque : il ne dit pas *ce qui* a été vérifié,
ni *pourquoi* un lien est considéré comme officiel, ni *ce qui* manque pour
qu'il le soit. La mission remplace ce booléen opaque par un **contrat de
confiance déterministe et explicable**.

Le module livré est **pur** : aucun appel réseau, aucun DNS, aucun accès
fichier, aucune dépendance externe, horloge injectée. La même entrée donne
toujours le même verdict.

---

## 2. Livrables

```
career/source_trust.py                 # module de confiance (720 lignes)
tests/test_source_trust.py             # 64 tests (dont 50 pilotés par fixtures)
tests/fixtures/source_trust/
├── registry.json                      # 6 entrées de registre synthétiques
└── cases.json                         # 25 cas synthétiques
docs/agent-reports/SPEC-SK01-SOURCE_TRUST.md   # ce rapport
```

**Aucune modification** de l'interface, du matching, d'une vérification réseau
réelle, des migrations ou du schéma : `career/service.py`, `career/router.py`,
`career_static/*` sont intacts.

---

## 3. Le contrat

```json
{
  "status": "verified",
  "provider": "greenhouse",
  "canonical_host": "job-boards.greenhouse.io",
  "employer_match": "confirmed",
  "registry_evidence": "registry:greenhouse:acmecorp",
  "reasons": ["« job-boards.greenhouse.io » est un hôte de board public de greenhouse.", "…"],
  "checked_at": "2026-10-21T09:00:00+00:00"
}
```

API publique :

```python
from career.source_trust import check_trust, check_offer_trust

check_trust(url, *, employer_hint=None, registry=None, redirects=None,
            claimed_official=False, clock=None) -> TrustResult
```

| Champ | Type | Valeurs |
|-------|------|---------|
| `status` | `Literal` | `verified` / `unverified` / `contradictory` / `missing` |
| `provider` | `str \| None` | `greenhouse`, `lever`, `ashby`, `smartrecruiters`, `employer`, `unknown` (`None` si aucune URL) |
| `canonical_host` | `str \| None` | hôte normalisé (minuscules, sans port, sans point final) |
| `employer_match` | `Literal` | `confirmed` / `mismatch` / `unknown` |
| `registry_evidence` | `str \| None` | identifiant de preuve local (`registry:<provider>:<token>`) |
| `reasons` | `list[str]` | explications lisibles, **jamais vide** |
| `checked_at` | `str` | ISO 8601 (horloge injectée dans les tests) |

`TrustResult` expose aussi `label` (libellé français prêt pour l'interface) et
`is_official`. `to_dict()` renvoie exactement les 7 champs du contrat.

---

## 4. Matrice de décision (ordre d'évaluation)

Les règles sont évaluées **dans cet ordre** ; la première qui s'applique
détermine le statut, et chaque étape ajoute sa raison.

| # | Situation | Statut | `employer_match` |
|---|-----------|--------|------------------|
| 1 | Aucune URL | `missing` | `unknown` |
| 2 | Schéma non `http(s)`, URL sans identifiants | `unverified` | `unknown` |
| 3 | URL porteuse d'identifiant / mot de passe | `unverified` | `unknown` |
| 4 | Domaine qui ** usurpe** un fournisseur | `contradictory` | `unknown` |
| 5 | Raccourcisseur non résolu | `unverified` | `unknown` |
| 6 | Fournisseur connu + employeur rattaché + hôte canonique | **`verified`** | `confirmed` |
| 7 | Fournisseur connu, mais employeur non rattaché | `unverified` | `unknown` |
| 8 | Fournisseur connu + board d'un **autre** employeur | `contradictory` | `mismatch` |
| 9 | Fournisseur connu sur un hôte **secondaire** (API, embed, autre) | `unverified` | (`confirmed` si l'employeur est rattaché) |
| 10 | Domaine d'employeur cohérent avec l'employeur attendu | **`verified`** | `confirmed` |
| 11 | Domaine d'employeur connu mais appartenant à un autre employeur | `contradictory` | `mismatch` |
| 12 | Domaine ressemblant, agrégateur, tiers non attesté | `unverified` | `unknown` |

### 4.1 Les quatre fournisseurs connus

| Fournisseur | Domaine | Hôtes canoniques (boards publics) |
|-------------|---------|-----------------------------------|
| `greenhouse` | `greenhouse.io` | `boards.greenhouse.io`, `job-boards.greenhouse.io` |
| `lever` | `lever.co` | `jobs.lever.co`, `jobs.eu.lever.co` |
| `ashby` | `ashbyhq.com` | `jobs.ashbyhq.com` |
| `smartrecruiters` | `smartrecruiters.com` | `careers.smartrecruiters.com`, `jobs.smartrecruiters.com` |

Un hôte secondaire du fournisseur (`boards-api.greenhouse.io`, `my.greenhouse.io`,
`api.smartrecruiters.com`…) **ne prouve rien** : le statut reste `unverified`
et la raison le dit. Le token de board est extrait du premier segment du
chemin ; pour Greenhouse, le board embarqué
(`boards.greenhouse.io/embed/job_board?for=<token>`) est lu dans le paramètre
`for`.

### 4.2 Usurpation et sous-domaine trompeur

Deux formes structurelles sont détectées, toutes deux **contradictoires** :

* le domaine du fournisseur est **collé** dans un domaine qui ne lui appartient
  pas : `job-boards.greenhouse.io.acmecorp.example`, `notgreenhouse.io` ;
* la marque du fournisseur est le **premier label** du domaine d'un tiers :
  `greenhouse.acmecorp.example`, `ashby.acmecorp.example`.

Un simple air de famille (`greenhouse-jobs.example.net`) **n'est pas** une
usurpation : il reste `unverified` — le domaine est lié, mais rien ne prouve
qu'il est officiel.

### 4.3 Raccourcisseurs

Les 30 raccourcisseurs connus (`bit.ly`, `t.co`, `tinyurl.com`, `lnkd.in`,
`rebrand.ly`…) rendent le verdict `unverified` tant que la destination n'est
pas connue localement. Le module sait suivre une redirection **fournie par
l'appelant** (`redirects={...}`, 5 sauts maximum, boucle détectée) : le verdict
est alors celui de la **cible finale**, et la redirection est tracée dans les
raisons.

### 4.4 Comparaison d'employeur

Les formes juridiques et connectives sont neutralisées (`Acme Corp` ≡ `Acme`,
`Qube Research & Technologies` ≡ `Qube Research and Technologies`). Quatre
verdicts :

| Verdict interne | Condition | Effet |
|-----------------|-----------|-------|
| `match` | identité identique, ou extension d'un nom à **frontière de mot** (`Acme` → `acmecorp`, `Man` → `mangroup`) | employeur `confirmed` |
| `compatible` | le slug contient le nom sans frontière de mot (`WNS` → `wnsglobal`) | employeur `unknown` — **jamais** une contradiction |
| `mismatch` | identités sans lien | employeur `mismatch` → `contradictory` |
| aucun | pas d'employeur en face | employeur `unknown` |

### 4.5 Le registre local comme preuve

Le registre (`career/source_registry.py`, 25 entrées curatées) est la preuve
disponible localement. Une entrée est retenue si **le fournisseur et le token
coïncident** et si son `public_url` est servi par un hôte canonique du même
fournisseur. La preuve est alors exposée dans `registry_evidence`
(`registry:greenhouse:acmecorp`) et **confirme l'employeur même sans indice**.

Contrôle sur le registre réel : **25 entrées curatées → 25 `verified`**,
0 faux positif, 0 faux négatif (voir §7).

---

## 5. Contraintes non négociables — conformité

| # | Contrainte | État | Preuve |
|---|-----------|-------|--------|
| 1 | Aucun booléen source ne constitue seul une preuve | ✅ | `claimed_official` est reçu, **tracé** dans les raisons et **n'influence jamais** le statut (`test_a_source_boolean_never_acts_as_a_single_proof`) |
| 2 | Aucun domaine légitime rejeté car hors des 4 ATS | ✅ | `https://jobs.contoso.example/careers/12` + indice `Contoso` → `verified`, `provider="employer"` (`test_a_legitimate_domain_is_not_rejected_only_because_it_is_not_a_known_ats`) |
| 3 | L'interface différencie vérifié / lié non vérifié / contradictoire | ✅ | `STATUS_LABELS` + `TrustResult.label` : 3 libellés distincts (`test_the_interface_can_differentiate_the_three_usable_states`) |
| 4 | Aucune requête réseau dans les tests | ✅ | Aucun `urllib`/`socket`/`http` dans `career/source_trust.py` ; redirections résolues par une table locale ; 100 % synthétique |
| 5 | Aucune modification interface / matching / vérification réseau | ✅ | `git diff --stat` ne touche que `career/source_trust.py`, `tests/…`, `docs/…` |

---

## 6. Les 25 cas synthétiques

`tests/fixtures/source_trust/cases.json` — 25 cas, 10 `verified`, 8 `unverified`,
6 `contradictory`, 1 `missing`.

| Cas de la mission | Cas de fixture | Attendu | Obtenu |
|-------------------|----------------|---------|--------|
| Greenhouse officiel | `greenhouse_official`, `greenhouse_embed_official` | `verified` | ✅ |
| Lever officiel | `lever_official`, `lever_eu_official` | `verified` | ✅ |
| Ashby officiel | `ashby_official` | `verified` | ✅ |
| SmartRecruiters officiel | `smartrecruiters_official` | `verified` | ✅ |
| Page carrière employeur | `employer_careers_page`, `employer_careers_page_without_hint`, `employer_careers_page_without_registry` | `verified` si domaine match | ✅ |
| Domaine ressemblant officiel | `lookalike_official_domain` | `unverified` | ✅ |
| Sous-domaine trompeur | `deceptive_subdomain`, `deceptive_suffix` | `contradictory` | ✅ |
| URL raccourcie | `shortened_url` | `unverified` | ✅ |
| URL manquante | `missing_url` | `missing` | ✅ |
| Fournisseur connu, entreprise incohérente | `known_provider_other_company`, `known_provider_other_board_without_registry`, `employer_page_other_company` | `contradictory` | ✅ |
| Redirection (fixture) | `redirect_to_greenhouse`, `redirect_to_contradictory_target` | selon cible finale | ✅ |
| Métadonnée « officielle » sans preuve | `metadata_claim_without_proof` | `unverified` | ✅ |
| *(hors table)* hôte secondaire du fournisseur | `secondary_vendor_host` | `unverified` | ✅ |
| *(hors table)* fournisseur connu sans élément employeur | `known_provider_without_employer_context` | `unverified` | ✅ |
| *(hors table)* slug souple (`WNS` → `wnsglobal`) | `loose_slug_is_not_a_contradiction` | `unverified` (compatible) | ✅ |
| *(hors table)* schéma non http(s) | `non_http_scheme` | `unverified` | ✅ |
| *(hors table)* identifiants dans l'URL | `credentials_in_url` | `unverified` | ✅ |

Chaque cas est exécuté **deux fois** par pytest : une fois sur le verdict
(champs + statut), une fois sur les raisons (non vides et contenu attendu).

---

## 7. Contrôle sur données réelles (registre curaté)

Les 25 entrées de `CURATED_SOURCES` ont été passées dans `check_trust` avec
leur `company` comme indice :

```
25 entrées → 25 verified, 0 non vérifié
```

Répartition : 21 boards ATS (greenhouse / lever / ashby), 4 boards agrégateurs
curatés (Welcome to the Jungle, JobTeaser, Talent.com, APEC), chacun avec sa
preuve `registry:<provider>:<token>` et `employer_match="confirmed"`.

Ce contrôle montre que les règles d'appariement (extension à frontière de mot,
neutralisation des formes juridiques) ne produisent **aucun faux négatif** sur
les 25 sources réellement curatées — dont `Qube Research & Technologies`
(`quberesearchandtechnologies`), `XTX Markets Technologies`, `Man Group`,
`General Atlantic`, `Optiver US`.

---

## 8. Interprétations explicites (à relire)

1. **`reasons` n'est jamais vide.** Le contrat d'exemple de la mission montre
   `"reasons": []` pour un cas `verified` ; la contrainte 1 exige que
   *chaque décision* contienne des raisons. J'ai retenu la contrainte : une
   décision vérifiée porte ses preuves positives (« hôte de board public de
   greenhouse », « preuve locale `registry:greenhouse:acmecorp` »). Le champ
   reste une `list[str]` conforme au contrat.
2. **`verified` exige un employeur rattaché.** Un hôte de fournisseur connu,
   sans indice d'employeur et sans entrée de registre, reste `unverified`
   (« aucun élément local ne rattache ce board à un employeur »). Le statut
   `verified` signifie « source confirmée **et** cohérence employeur » ; un
   `verified` avec `employer_match="unknown"` aurait été incohérent.
3. **`mismatch` = un employeur identifié qui n'est pas celui attendu.** Sur un
   board de fournisseur connu, le token est l'identité de l'employeur : s'il
   ne correspond pas à l'employeur attendu, c'est une contradiction. Sur un
   domaine tiers non attesté, un simple écart de nom n'est **pas** une
   contradiction (le domaine peut être un agrégateur) : le statut reste
   `unverified` et la raison le dit.
4. **Le slug souple n'est jamais une contradiction.** `wnsglobal` pour `WNS`
   donne `unverified` + `employer_match="unknown"` : le module refuse de
   contredire une source qu'il ne sait pas identifier, mais ne la promeut
   jamais non plus.
5. **Le domaine employeur est approché localement.** Le module calcule un
   domaine enregistrable avec une liste explicite de suffixes publics
   multipartites (`co.uk`, `com.au`…) : pas de PSL téléchargée, pas de réseau.
   Les domaines composed `.example` sont utilisés dans les fixtures.

---

## 9. Limites connues

* Le module ne **vérifie rien en ligne** : il ne prouve que ce qui est locally
  attestable (hôte, token, registre, indice). Une page qui n'existe plus reste
  `verified` tant que le registre l'atteste — c'est le sens de
  `registry_evidence` (preuve historique datée, comme le registre existant).
* La comparaison d'employeur est lexicale : un board dont le slug n'a aucun
  lien avec le nom de l'entreprise tombe en `compatible` (`unverified`), jamais
  en `verified` — c'est volontaire.
* Les agrégateurs curatés (Welcome to the Jungle, JobTeaser, Talent.com,
  APEC) sont classés `provider="employer"` : le contrat de la mission ne
  prévoit que 4 ATS + `employer` + `unknown`, et la source exacte reste lisible
  dans `registry_evidence`.
* Aucune interface n'est branchée sur ce module dans cette mission (contrainte
  5) : la consommation se fera en SK-07 (snapshot) et SK-08 (connecteurs).

---

## 10. Validation

```
$ .venv/bin/python -m pytest -q tests/test_source_trust.py
64 passed

$ .venv/bin/python -m pytest -q
1437 passed, 1 skipped          (base : 1373 passed, 1 skipped → 64 tests ajoutés, 0 régression)

$ .venv/bin/python -m ruff check .
All checks passed!

$ git diff --check
(propre)

$ VENV_PY=/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python ./checklist_codex.sh main
TOUT VERT
```

Aucun appel réseau dans les tests ; toutes les données sont synthétiques
(`example` réservé à la documentation) ; aucun secret, aucune donnée réelle.
