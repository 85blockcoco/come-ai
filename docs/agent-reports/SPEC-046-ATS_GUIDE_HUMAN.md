# SPEC-046 — Détection de plateforme ATS et guide humain d'application

**Statut :** livré (branche `agent/spec-046-ats-guide-human`)
**Priorité :** P0

## Objectif

Quand une offre est consultée, la personne doit savoir ce qui l'attend avant de
cliquer « postuler » : quelle plateforme ATS, quel lien de formulaire, quelles
étapes, quels champs, combien de temps, et si un compte est nécessaire.

Le module est **100 % local** : aucune requête HTTP sortante, aucune
soumission, aucun compte créé. Le guide décrit ce que la personne fera
elle-même sur le site de l'employeur.

## Livrables

| Fichier | Rôle |
|---|---|
| `career/ats_guide.py` | `detect_platform()`, `human_apply_guide()`, `GuideStep`, `ApplyGuide`, guides par plateforme |
| `career/router.py` | `GET /api/career/ats-guide/{job_id}` + capacité `ats_guide` dans `/api/career/health` |
| `career/service.py` | déclaration de la capacité locale `ats_guide` |
| `tests/test_career_ats_guide.py` | 54 tests (6 plateformes minimum largement dépassé) |
| `tests/fixtures/ats_guide_jobs_synthetic.json` | offres synthétiques uniquement |

## Contrats implémentés

```python
@dataclass(frozen=True)
class GuideStep:
    title: str
    fields: list[str]
    tips: str

@dataclass(frozen=True)
class ApplyGuide:
    platform: str | None
    apply_url: str
    steps: list[GuideStep]
    needs_account: bool
    estimated_minutes: int
```

`ApplyGuide.to_dict()` fournit la projection JSON consommée par l'endpoint.

## Plateformes reconnues

| Plateforme | Domaines officiels | Compte | Durée estimée | Lien direct |
|---|---|---|---|---|
| `greenhouse` | `greenhouse.io` | non | 12 min | ancre `#app` |
| `lever` | `lever.co` | non | 10 min | `/apply` |
| `workday` | `myworkdayjobs.com`, `workday.com` | oui | 25 min | page officielle |
| `smartrecruiters` | `smartrecruiters.com` | non | 10 min | page officielle |
| `recruitcrm` | `recruitcrm.io` | oui | 15 min | page officielle |
| `breezy` | `breezy.hr` | non | 8 min | page officielle |
| `jobvite` | `jobvite.com` | non | 15 min | `/apply` |
| `ashby` | `ashbyhq.com` | non | 10 min | `/application` |
| `ripplematch` | `ripplematch.com` | oui | 20 min | page officielle |
| `custom` | site employeur | variable | 15 min | page officielle |
| `None` (inconnue) | — | inconnu | 15 min | page officielle |

Le lien officiel est prioritaire. Le nom de source complète la reconnaissance
lorsque l'employeur héberge le formulaire sur son propre domaine (ex. offre
Greenhouse servie depuis `careers.employeur.test`) ; dans ce cas le lien n'est
**jamais** transformé.

## Champs et réponses types SPEC-045

Chaque `GuideStep.fields` utilise des jetons stables :

- `document:*` : CV, lettre, relevé ;
- `profile:*` : nom, e-mail, téléphone, LinkedIn, formation, langues… ;
- `quick_answer:*` : clés SPEC-045 (`availability_start`,
  `work_authorization`, `languages`, `education`, `internship_duration`,
  `mobility`, `current_status`, `motivation`, `salary_expectations`) ;
- `question:screening` : questions propres à l'employeur ;
- `review:all` : relecture finale.

`FIELD_LABELS` fournit les libellés lisibles correspondants. Le module
n'importe pas `career/quick_answers.py` : la correspondance se fait par clés,
donc aucun couplage cassant si SPEC-045 évolue.

## Refus propres (URL suspecte)

`detect_platform()` et `human_apply_guide()` lèvent `UserFacingError`
(message utilisateur, HTTP 400 côté API) pour :

- schéma non `http(s)` : `javascript:`, `data:`, `file:`, `ftp:` ;
- identifiants ou mot de passe dans l'URL ;
- caractères de contrôle, espaces ou antislash (injection d'en-tête/URL) ;
- port non standard (autre que 80/443) ;
- adresse IP, `localhost`, nom d'hôte non public ou non ASCII ;
- domaine imitant une marque ATS (`greenhouse.io.evil.test`,
  `my-lever.example`, `jobs.ashbyhq.example`) ;
- incohérence entre le nom de source et le domaine (source `greenhouse` sur
  une URL `lever.co`) ;
- absence de lien officiel.

Une URL publique valide mais inconnue n'est **pas** refusée : elle reçoit un
guide générique honnête, `platform=None`, et le lien officiel est conservé.

## Endpoint

`GET /api/career/ats-guide/{job_id}`

```json
{
  "job_id": "…",
  "company": "…",
  "title": "…",
  "platform": "greenhouse",
  "apply_url": "https://job-boards.greenhouse.io/…/jobs/…​#app",
  "steps": [{"title": "…", "fields": ["…"], "tips": "…"}],
  "needs_account": false,
  "estimated_minutes": 12,
  "automated_submission": false
}
```

- Offre inconnue → HTTP 400 avec message utilisateur ;
- URL refusée → HTTP 400 avec la raison ;
- `schema_version=7` et les routes existantes ne sont pas modifiés.

La capacité est exposée dans `/api/career/health` :

```json
"ats_guide": {
  "enabled": true,
  "local_only": true,
  "network_requests": false,
  "automated_submission": false,
  "platforms": ["greenhouse", "…", "custom"]
}
```

## Preuves

```text
pytest -q tests/test_career_ats_guide.py            → 54 passed
pytest -q tests/test_career_agent.py \
          tests/test_career_job_summary_consent.py  → 43 passed
ruff check career/ats_guide.py career/router.py \
           tests/test_career_ats_guide.py           → All checks passed
```

Un test coupe `socket.socket` et `socket.create_connection` et vérifie que le
guide se construit quand même : **aucune connexion réseau**. Un test
adversarial couvre l'usurpation de domaine et l'injection de caractères de
contrôle.

## Limites assumées

- Les URL directes ne sont transformées que pour les motifs certains
  (Greenhouse, Lever, Jobvite, Ashby) ; pour Workday, SmartRecruiters,
  RecruitCRM, Breezy et RippleMatch, le lien officiel est conservé car l'URL
  du formulaire varie par tenant.
- `needs_account` reste un booléen : pour `platform=None` et `custom`, la
  valeur `false` signifie « non confirmé », ce que le guide dit explicitement.
- Les durées sont des estimations d'interface, pas des mesures.
- Aucune soumission automatique, aucun stockage de mot de passe de plateforme.
