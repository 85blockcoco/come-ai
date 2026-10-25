# SPEC-030 — Export & partage lecture CV

**Date** : 2026-10-25
**Branche** : `worker/cvboost-65-1792965334617`
**Base** : `8fe62ab`
**Périmètre** : `career/share_export.py`, `career/service.py`, `career/router.py`,
`tests/test_share_export.py`, `tests/fixtures/share_synthetic.json`

---

## Résumé

Génération locale d’un **dossier de candidature ZIP** (`manifest.json` + vues JSON +
brouillons CV/lettre) et d’une **vue « lecture » partagée** qui n’expose que des champs
explicitement autorisés. Aucun réseau, aucun modèle, aucune clé, aucune donnée réelle :
les tests utilisent uniquement la fixture synthétique
`tests/fixtures/share_synthetic.json`.

Chaque export est **tracé** dans le journal d’audit existant
(`career_audit_log`, action `share_bundle_exported`) et listable via
`GET /api/career/share-exports`. Aucune migration, `SCHEMA_VERSION` reste **8**.

### Double barrière de confidentialité

1. **Liste blanche stricte** — `PROFILE_SHARE_FIELDS`, `JOB_SHARE_FIELDS`,
   `APPLICATION_SHARE_FIELDS`. Un champ absent de la liste n’est jamais copié.
2. **Garde-fou sur les noms privés** — `is_private_field()` refuse tout champ dont le nom
   normalisé contient `email`, `phone`, `note`, `approval`, `reference`, `checklist`,
   `event`, `token`, `secret`, `linkedin`, `address`, `salary`, etc. Même si un développeur
   ajoute par erreur `contact_email` à une liste blanche, la valeur ne sort pas.
3. **Manifeste sans fuite** — le ZIP exporté ne contient que des compteurs
   (`redacted_counts`) : ni le nom ni la valeur d’un champ privé n’y figure. La liste
   nominative `redacted` reste locale à `share_view()` pour l’explication dans l’UI.

Les structures imbriquées (`dict`, `set`, objets) ne sont **jamais** sérialisées :
elles pourraient cacher une clé privée que la liste blanche de premier niveau n’a pas
inspectée. Les listes ne sont acceptées que si elles ne contiennent que des scalaires.

---

## Contrats Python

```python
@dataclass
class ShareBundle:
    files: dict[str, bytes]        # chemin -> contenu (sans manifest.json)
    manifest: dict                 # version, offer_id, generated_at, checksums, redacted_counts

@dataclass
class ShareView:
    fields: dict[str, object]      # champs autorisés uniquement
    redacted: list[str]            # champs omis volontairement (noms, jamais valeurs)

build_bundle(*, offer_id, job, profile=None, application=None,
             documents=None, sensitive_values=(), generated_at=None) -> ShareBundle
redact(record, allowed_fields, *, text_limit=MAX_TEXT_LENGTH) -> ShareView
scrub_text(text, sensitive_values=()) -> str
verify_bundle(bundle) -> bool
bundle_filename(offer_id, generated_at=None, *, nonce="") -> str
```

### Manifeste

```json
{
  "version": "1.0",
  "offer_id": "job_…",
  "generated_at": "2026-10-25T12:00:00Z",
  "read_only": true,
  "checksums": {"offre.json": "sha256…", "profil.json": "sha256…"},
  "files": ["candidature.json", "lisez-moi.txt", "offre.json", "profil.json"],
  "redacted_counts": {
    "job": 7,
    "profile": 10,
    "application": 9
  },
  "documents_scrubbed": true
}
```

- `checksums` couvre **chaque fichier** du ZIP sauf `manifest.json` lui-même.
- `redacted_counts` ne contient que des **compteurs** : ni le nom ni la valeur d’un
  champ privé n’est répété dans le manifeste exporté (test dédié). La vue locale
  `share_view` continue, elle, d’exposer la liste `redacted` pour que l’UI explique
  ce qui a été omis.
- `documents_scrubbed` indique qu’au moins un brouillon a été filtré.

### Documents

Seuls les **brouillons texte UTF-8** (`.md`) sont acceptés. Les octets binaires (PDF,
images) sont refusés : ils ne peuvent pas être contrôlés par la redaction. Le texte des
brouillons est passé dans `scrub_text()` avec les valeurs privées connues du profil
(e-mail, téléphone, LinkedIn, notes, entreprises cibles) : si un CV généré répète le bloc
contact, il est remplacé par `[coordonnées non partagées]`. Les documents sont pris dans
le **brouillon le plus récent** de l’offre, pour ne pas joindre une version obsolète.

---

## API REST

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/api/career/jobs/{job_id}/share-view` | Projection lecture seule (JSON) |
| `POST` | `/api/career/jobs/{job_id}/share-bundle` | Génère et télécharge le ZIP (`Cache-Control: no-store`) |
| `GET` | `/api/career/share-exports` | Historique des exports tracés (50 derniers) |

Une offre inconnue renvoie **400** (`UserFacingError`), jamais une trace serveur. Le ZIP
est écrit avec un nom opaque `career_partage_<horodatage>_<sha256[:16]>_<nonce>.zip` :
aucun texte utilisateur n’entre dans le nom de fichier, et deux exports dans la même
seconde ne s’écrasent pas.

---

## Décisions techniques

- **ZIP déterministe** : horodatage fixe `1980-01-01`, entrées triées, `manifest.json`
  en premier, permissions `0600` (`external_attr`), `allowZip64=False`. Deux appels avec
  le même `generated_at` produisent exactement les mêmes octets.
- **Écriture atomique** : fichier temporaire privé puis `os.replace`, `chmod 0600`.
- **Aucune migration** : l’audit réutilise `career_audit_log` ; `SCHEMA_VERSION` reste 8.
- **Reset** : les archives `career_partage_*` sont supprimées par
  `reset_personal_data()` (le glob existant `career_*` les couvre).
- **Module pur** : `share_export.py` ne fait aucune E/S et ne dépend ni de FastAPI ni de
  SQLite ; il est testable seul.

---

## Tests

`tests/test_share_export.py` — **27 tests**, dont :

- liste blanche + garde-fou privé (liste blanche volontairement erronée) ;
- données imbriquées, `NaN`, caractères de contrôle, troncature ;
- manifeste sans nom ni valeur privée, checksums, déterminisme octet-pour-octet ;
- ordre du ZIP, permissions, absence d’archive imbriquée ;
- noms de fichiers hostiles (`../`, chemin absolu, `manifest.json`, majuscules) ;
- document binaire refusé, document surdimensionné refusé ;
- détection de falsification (`verify_bundle`) ;
- smoke REST via `create_app()` : vue, ZIP, en-têtes, contenu, trace d’audit ;
- brouillon CV/lettre : coordonnées masquées dans le ZIP ;
- offre inconnue / identifiant vide → 400.

### Vérifications

```bash
.venv/bin/python -m pytest -q tests/test_share_export.py
# 27 passed

.venv/bin/python -m pytest -q
# 1534 passed, 1 skipped, 1 failed in 250.78s
# L’unique échec est préexistant : tests/test_career_agent.py:506 attend 6 familles de
# préférences alors que la base en contient 14. Il ne touche aucun fichier de ce lot
# (déjà signalé sur la base a472872 / HEAD antérieur).

.venv/bin/python -m ruff check .
# All checks passed

git diff --check
# CLEAN
```

> Note : ce worktree partage le `.venv` du dépôt principal ; `checklist_codex.sh`
> accepte `VENV_PY=/chemin/vers/.venv/bin/python`.

---

## Limites assumées

- **Pas de lien de partage hébergé** : le « partage » est un fichier remis par la
  personne. Aucun jeton, aucune URL publique, aucun stockage serveur.
- **Pas de chiffrement du ZIP** : si un mot de passe est nécessaire, il doit être ajouté
  par un outil externe ; le fichier reste en `0600` sur le disque local.
- **Documents texte uniquement** : les PDF/DOCX ne sont pas intégrés au bundle (ils ne
  peuvent pas être vérifiés par la redaction).
- **Filtrage exact des documents** : `scrub_text` masque les valeurs privées connues,
  mais une reformulation manuelle (téléphone espacé différemment, adresse postale libre)
  n’est pas détectée. La liste blanche des champs structurés reste, elle, stricte.
- **Pas d’interface graphique** : les routes sont prêtes, l’UI n’est pas modifiée dans
  cette mission.
- **Vue locale nominative** : `share_view()` liste les noms des champs omis pour que
  l’UI puisse expliquer la redaction ; cette liste nominative n’entre jamais dans le
  manifeste ni dans le ZIP exporté.
- **Mission initialement notée `schema_version=7`** : le dépôt est déjà passé à **8** ;
  aucune modification de schéma n’a été faite, la compatibilité est donc préservée.

---

## Reproductibilité

```bash
cd AI-Excel-Agent-worker-cvboost-65-1792965334617
VENV_PY=/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python ./checklist_codex.sh
```

Toutes les données de test sont synthétiques (`*.invalid`, `example.test`).
