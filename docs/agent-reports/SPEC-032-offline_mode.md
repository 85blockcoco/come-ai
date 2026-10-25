# SPEC-032 — Mode hors-ligne & cache local

**Mission** : CVBOOST-67 (SPEC-032)
**Branche de travail** : `worker/cvboost-67-1792965306227`
**Branche de livraison demandée** : `agent/spec-032-offline-cache`
**Base** : `8fe62ab` (worktree orchestrateur, branche `worker/cvboost-67-1792965306227`)
**Date** : 2026-10-25
**Auteur** : Worker CVBOOST-67

---

## 1. Ce qui est livré

Une couche de lecture hors-ligne locale, sans migration de base et sans appel
réseau propre :

| Élément | Rôle |
|---------|------|
| `OfflineCache` | Cache JSON borné, atomique, privé (`0600`, dossier `0700`) dans `career_data/offline/` |
| `freshness_policy()` | Fenêtre de fraîcheur par type de lecture, surchargeable par code ou par `CAREER_OFFLINE_MAX_AGE_HOURS` |
| `serve_or_cache()` | Sert le réseau, la copie encore fraîche (`cache`) ou la copie périmée (`stale`), avec la liste des champs à revérifier |
| `offline_banner()` | Bandeau d'état hors-ligne (`online` / `cached` / `stale`) prêt pour l'interface |
| Routes REST | Statut, inventaire, lecture/écriture/suppression, lecture hors-ligne réelle via `create_app()` |

Aucune donnée réelle n'est utilisée : la fixture est
`tests/fixtures/offline_synthetic.json` (domaines `.test` uniquement).

## 2. Politique de fraîcheur

| Type de lecture | Fenêtre par défaut |
|-----------------|--------------------|
| `jobs`, `offers`, `dashboard` | 6 h |
| `applications`, `dossiers` | 12 h |
| `profile` | 24 h |
| `checklists` | 72 h |
| autre / `default` | 24 h |

* `CAREER_OFFLINE_MAX_AGE_HOURS` ne remplace que la fenêtre par défaut des
  types non listés (une valeur d'environnement invalide est ignorée, elle ne
  casse jamais le démarrage).
* Un `overrides={"jobs": 48}` explicite gagne et est validé (entier, 1 h à
  8 760 h, booléens refusés).

## 3. Décisions de conception

1. **Le cache ne ment jamais.** Trois sources seulement :
   - `network` : lecture locale réussie, copie enregistrée au passage ;
   - `cache` : copie dans la fenêtre de fraîcheur ;
   - `stale` : copie plus vieille que la politique ; `degraded_fields` liste
     les champs de premier niveau à revérifier et le bandeau l'affiche.
2. **Aucun schéma modifié.** `SCHEMA_VERSION` de `career/service.py` reste
   intact ; le cache est un fichier JSON à côté de la base, pas une table.
   Un test lit `PRAGMA user_version` avant/après usage des routes.
3. **Panne réseau silencieuse, panne de cache non bloquante.** Un lecteur qui
   lève une exception bascule sur la copie locale ; une écriture de cache
   impossible (disque plein) renvoie quand même la donnée fraîche.
4. **Pas de fausse donnée.** Sans réseau *et* sans copie, la route renvoie
   `503` avec un message honnête — jamais un objet vide présenté comme réel.
5. **Bornes.** 80 entrées max, 256 Ko par payload, 8 Mio par fichier ; les
   entrées les plus anciennes sont élaguées, puis le fichier est réécrit de
   façon atomique (`mkstemp` + `os.replace`).
6. **Clés fermées.** `[a-z0-9][a-z0-9._:-]{0,119}` : ni `/`, ni `..`, ni
   saut de ligne, donc aucune évasion de répertoire possible.
7. **Lecture seule côté réseau réel.** `GET /api/career/offline/read/{kind}/{key}`
   utilise uniquement les méthodes locales de `CareerService`
   (`list_jobs`, `list_applications`, `get_profile`, `dashboard`) ; aucun
   connecteur n'est appelé. `network=false` simule la coupure et n'appelle
   jamais le lecteur.
8. **Confidentialité.** Le cache vit dans le dossier privé Career. Le reset
   explicite `DELETE /api/career/data` efface aussi le cache hors-ligne (les
   copies contiennent les mêmes offres/checklists/profil). L'inventaire
   n'expose jamais les payloads, seulement clé/âge/nombre de champs.

## 4. Contrats Python

```python
@dataclass(frozen=True)
class CacheEntry:
    key: str
    payload: dict
    fetched_at: str
    max_age_hours: int

@dataclass(frozen=True)
class OfflineDecision:
    source: Literal["network", "cache", "stale"]
    age_hours: float | None
    degraded_fields: list[str]

def freshness_policy(kind="default", *, overrides=None, environ=None) -> int
def serve_or_cache(key, *, cache, reader=None, network_ok=True,
                   kind="default", max_age_hours=None, now=None) -> OfflineRead
```

`serve_or_cache` retourne `OfflineRead(payload, decision)` pour garder le
payload et la décision ensemble ; `offline_banner(decision)` produit le
bandeau. Les deux dataclasses exigées par la mission sont inchangées.

## 5. API REST (via `create_app()`)

| Méthode | Route | Comportement |
|---------|-------|--------------|
| `GET` | `/api/career/offline/status` | Inventaire + politique ; ne touche ni réseau ni base |
| `GET` | `/api/career/offline/cache` | Liste des clés (sans payload) |
| `GET` | `/api/career/offline/cache/{key}` | Entrée + décision + bandeau, `404` sinon |
| `POST` | `/api/career/offline/cache` | Enregistre une copie explicite (`201`) |
| `DELETE` | `/api/career/offline/cache/{key}` | Supprime une clé |
| `DELETE` | `/api/career/offline/cache` | Vide le cache, retourne le nombre supprimé |
| `GET` | `/api/career/offline/read/{kind}/{key}` | Sert réseau/cache/stale, `503` sans copie |

Types de lecture acceptés : `jobs`, `offers`, `applications`, `checklists`,
`dossiers`, `profile`, `dashboard`.

Exemple de réponse hors-ligne :

```json
{
  "kind": "jobs",
  "key": "jobs:fr",
  "payload": {"jobs": [...]},
  "decision": {"source": "stale", "age_hours": 120.0, "degraded_fields": ["jobs"]},
  "banner": {"offline": true, "level": "stale", "message": "Mode hors-ligne — copie locale vieille de 120.0 h ; 1 champ(s) à revérifier avant toute décision."},
  "automatic_submission": false
}
```

## 6. Tests

`tests/test_offline_mode.py` — **46 tests** :

* politique de fraîcheur (défauts, env, overrides, valeurs invalides) ;
* aller-retour, persistance entre instances, permissions `0600`/`0700` ;
* frontière exacte frais/périmé, horodatage futur ramené à 0 h ;
* élagement (80 entrées → 3 dans le test) et inventaire sans payload ;
* `serve_or_cache` : réseau, hors-ligne sans appel au lecteur, panne du
  lecteur, copie périmée, absence de copie, cache non inscriptible ;
* **adversarial** : clés `../escape`, `/`, `..`, majuscules, accents, saut de
  ligne, 121 caractères ; payloads vides, non-dict, objets Python, `NaN`,
  > 256 Ko ; fichier corrompu (JSON invalide, mauvais schéma, booléen à la
  place d'une durée, entrée déplacée, date invalide) ; fichier > 8 Mio ;
* HTTP réel via `create_app()` : smoke complet, bandeau stale, `503` sans
  copie, refus des entrées adversariales, `SCHEMA_VERSION` inchangé, reset
  confidentialité qui vide le cache.

## 7. Limites assumées

* **Pas de chiffrement** : le fichier est du JSON en clair dans le dossier
  privé de l'utilisateur (`0700`/`0600`), ce que la mission autorise
  explicitement. Un chiffrement au repos demanderait une gestion de clé
  locale hors périmètre.
* **Pas de bandeau dans `career_static/`** : la mission liste les modules
  autorisés et le bandeau est fourni par l'API (`banner`) pour éviter tout
  conflit avec les autres SPEC qui touchent l'interface. Brancher
  `banner.message` dans l'UI est un ajout purement additif.
* **Pas de cache des documents lourds** : plafond de 256 Ko par entrée ; les
  exports et pièces jointes ne sont pas mis en cache.
* **Écriture concurrente multi-processus** non verrouillée entre processus
  (le serveur local est mono-processus). Entre threads, un verrou par
  instance protège lecture/écriture.
* **Un test préexistant ajusté** : `tests/test_career_agent.py` attendait
  6 familles de préférences alors que `career/service.py` en seed 14 depuis
  le commit `cd0e5e8` (`JOB_FAMILIES`) : ce test était donc rouge sur la base
  `8fe62ab`. L'assertion est alignée sur 14 ; aucun comportement produit n'est
  modifié.

## 8. Vérifications

```text
python -m pytest -q tests/test_offline_mode.py            → 46 passed
python -m pytest -q tests/test_offline_mode.py tests/test_career_agent.py → 85 passed
python -m pytest -q                                       → 1554 passed, 1 skipped (466 s)
python -m ruff check .                                    → All checks passed
./checklist_codex.sh secrets / injection / lint           → TOUT VERT
git diff --check                                          → CLEAN
```

Le seul test ignoré (`tests/test_offer_summary_exhaustiveness.py`) l'est pour
une raison préexistante (script/base absents de l'environnement), sans lien
avec ce lot. Suite complète rejouée sous charge (2 autres workers en parallèle),
d'où la durée.
