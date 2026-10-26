# SPEC-034 — Sauvegarde / restauration du workspace Career

**Mission** : export ZIP versionné (manifeste + checksums SHA-256) et restauration
non destructive du workspace local Career, avec validation de schéma et diff
avant toute écriture.

**Branche livrée** : `agent/spec-034-workspace-backup` (worktree
`AI-Excel-Agent-worker-cvboost-69-1792968035902`).

**Périmètre** : uniquement des fixtures synthétiques (`tests/fixtures/backup_synthetic.json`).
Aucune donnée personnelle réelle, aucun réseau, aucun LLM, aucun secret.

---

## 1. Fichiers livrés

| Fichier | Rôle |
|---|---|
| `career/workspace_backup.py` | Module complet : création, manifeste, diff, restauration, validation d'archive |
| `tests/test_workspace_backup.py` | 28 tests (contrat, cas limites, adversarial, smoke API) |
| `tests/fixtures/backup_synthetic.json` | Workspace synthétique (candidatures, lettre, export, preuve) |
| `career/router.py` | 5 routes REST ajoutées à `create_career_router()` (adaptateur mince) |
| `docs/agent-reports/SPEC-034-workspace_backup.md` | Ce rapport |

Aucun changement de `SCHEMA_VERSION` (migration SQLite) ni des dépendances.

---

## 2. Contrat public

```python
@dataclass
class BackupManifest:
    created_at: str
    schema_version: int   # version du format de sauvegarde = 7
    files: list[str]
    checksums: dict[str, str]

@dataclass
class RestorePlan:
    to_overwrite: list[str]   # présents localement, candidats au remplacement
    to_add: list[str]         # absents localement
    conflicts: list[str]      # présents et modifiés : jamais écrasés sans accord

create_backup(workspace_dir, destination=None, *, schema_version=7,
              excluded_top_level=("backups",), now=None) -> tuple[Path, BackupManifest]

diff_state(backup_path, workspace_dir, *, local_schema_version=None,
           upgrade=False) -> RestorePlan

restore_backup(backup_path, workspace_dir, *, confirm=False, upgrade=False,
               accept_conflicts=False, local_schema_version=None) -> RestorePlan

read_manifest(backup_path) -> BackupManifest
```

`create_backup()` renvoie aussi le chemin de l'archive. Par défaut elle est
écrite dans `<workspace>/backups/workspace/` ; ce dossier est exclu du parcours,
donc une sauvegarde n'embarque jamais les sauvegardes précédentes.

### Version de schéma

`BACKUP_SCHEMA_VERSION = 7` est la version du **format de sauvegarde** exigée par
la spec. Elle est volontairement distincte de `career.service.SCHEMA_VERSION`
(actuellement `8`, compteur de migrations SQLite) : restaurer un ZIP est une
opération de fichiers, pas une migration de base. `SCHEMA_VERSION` n'a pas été
modifié. Une archive d'une autre version est refusée par défaut ; `upgrade=True`
est l'acceptation explicite.

---

## 3. Garanties de sécurité

### Avant toute écriture

1. Le manifeste est lu et validé (types, chemins, SHA-256 hexadécimaux, unicité).
2. Chaque nom d'entrée est normalisé : refus des chemins absolus, lecteurs
   Windows (`C:`), anti-slashs, segments `.`/`..`, chemins vides ou trop longs,
   noms dupliqués.
3. Les entrées ZIP sont refusées si elles sont chiffrées, symboliques, ou d'un
   type spécial (FIFO, etc.).
4. Toute entrée non listée dans le manifeste est refusée, ainsi que tout fichier
   listé mais absent de l'archive.
5. Chaque checksum est recalculé **avant** la première écriture ; une seule
   discordance annule toute la restauration.
6. Les destinations sont pré-vérifiées : un parent symlinké qui sortirait du
   workspace, une cible symlink ou un dossier appelé à être remplacé par un
   fichier provoquent un refus avant toute écriture (pas de restauration
   partielle).

### Consentement explicite

| Situation | Comportement |
|---|---|
| `confirm=False` | `BackupConfirmationRequired` (HTTP 409), plan renvoyé, zéro écriture |
| Fichier local modifié (`conflicts`) | `BackupConflictError` (HTTP 409), zéro écriture |
| `accept_conflicts=True` | remplacement explicite des conflits |
| `schema_version` différente | `BackupSchemaMismatch` (HTTP 409) sauf `upgrade=True` |
| Fichier local absent de l'archive | jamais supprimé |

### Intégrité SQLite

Les bases (`*.sqlite3`, `*.sqlite`, `*.db`) sont copiées via l'API
`sqlite3.Connection.backup()` : l'instantané inclut les transactions validées du
WAL. Les sidecars `-wal`, `-shm`, `-journal` ne sont jamais archivés
séparément ; après restauration d'une base, les sidecars locaux sont retirés
pour éviter qu'un WAL obsolète ne corrompe le fichier restauré.

Le diff compare le **contenu logique** (`iterdump()` trié) des bases, pas leurs
octets : un checkpoint ou un `PRAGMA` peut modifier la mise en page sans changer
la moindre donnée. Des octets différents avec un contenu identique ne sont donc
pas signalés comme conflit ; une différence de schéma ou de lignes l'est.

---

## 4. API REST

Routes ajoutées dans `create_career_router()` (pattern existant de
`career/router.py`, monté par `come_ai_web.create_app()`), toutes locales :

| Méthode | Route | Résultat |
|---|---|---|
| `POST` | `/api/career/workspace/backups` | 201, `filename`, `size_bytes`, `download_url`, `manifest` |
| `GET` | `/api/career/workspace/backups` | liste + `schema_version` |
| `GET` | `/api/career/workspace/backups/{filename}` | téléchargement `application/zip`, `Cache-Control: no-store` |
| `POST` | `/api/career/workspace/backups/{filename}/plan` | diff, zéro écriture |
| `POST` | `/api/career/workspace/backups/{filename}/restore` | `confirm`/`upgrade`/`accept_conflicts` explicites |

Codes : 400 nom invalide, 404 archive inconnue, 409 consentement/conflit/schéma,
422 archive non sûre ou corrompue. Le nom de fichier est réduit à son composant
de base et confiné à `<data_dir>/backups/workspace`, donc aucune traversée par
l'URL n'est possible.

Le smoke test REST couvre : création, liste, téléchargement, plan, refus sans
confirmation, refus des conflits, restauration acceptée, refus de traversée de
chemin, refus de schéma sans `upgrade`, et montage réel des routes dans
l'application produite par `come_ai_web.create_app()`.

---

## 5. Tests

`pytest -q tests/test_workspace_backup.py` → **28 passed**.

Couverture :

- aller-retour complet, accents/Unicode, fichiers imbriqués ;
- manifeste relu et identique au contrat ;
- destination par défaut et absence de récursion des sauvegardes ;
- `schema_version` invalide, workspace absent ;
- instantané SQLite + exclusion des sidecars ;
- diff vide / identique / modifié ;
- refus sans `confirm`, conflits préservés puis résolution explicite ;
- aucune suppression de fichier local non concerné ;
- refus de schéma sans `upgrade`, acceptation avec `upgrade=True` ;
- **adversarial** : zip-slip `../`, chemin absolu, anti-slash/lecteur Windows,
  checksum falsifié, entrée non listée, entrée symlink, entrée chiffrée,
  doublons, ZIP corrompu, manifeste absent, checksum orphelin, parent symlinké
  sortant du workspace ;
- smoke REST complet via `create_career_router()` et montage réel dans
  l'application produite par `come_ai_web.create_app()`.

`ruff check .` → **All checks passed**.

### Correction hors périmètre fonctionnel (transparence)

La première exécution complète a révélé **un échec préexistant**, sans rapport
avec SPEC-034 : `tests/test_career_agent.py` vérifiait encore
`len(preferences["families"]) == 6`, alors que le commit `cd0e5e8` a étendu
`JOB_FAMILIES` à 14 familles (généralisation sectorielle). L'assertion dérive
maintenant de la constante autoritaire `career.models.JOB_FAMILIES`
(`len(...) == len(JOB_FAMILIES)`), ce qui évite une nouvelle divergence lors
d'une future extension de la taxonomie. Aucun comportement applicatif n'est
modifié par ce changement de test.

---

## 6. Limites assumées

- **Pas de chiffrement applicatif** du ZIP : la confidentialité repose sur les
  permissions du dossier (`0700`, archive `0600`) et sur le chiffrement disque
  de la machine. Ajouter un mot de passe local serait une spec séparée.
- **Pas de suppression** lors d'une restauration : les fichiers locaux absents
  de l'archive restent en place. Un « retour exact » nécessiterait une
  confirmation distincte, hors périmètre.
- **Taille** : 5 000 fichiers / 512 Mo décompressés par archive.
- **Restauration pendant que le service tourne** : les connexions SQLite sont
  courtes, mais une requête concurrente peut encore lire l'ancien inode. En
  production, restaurer hors requête (ou redémarrer le service ensuite) est
  recommandé.
- Les métadonnées de permissions/UID ne sont pas restaurées : les fichiers
  réécrits sont en `0600` et les dossiers créés héritent du umask local.
