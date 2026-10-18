# Consent guard — lot isolé de garde-fou cloud

Branche : `feature/v3-consent-guard` · Base : `integration/profile-study` @ `c32b284`
Worktree : `/Users/comedelavenne/AI-Excel-Agent-v3-consent`
Périmètre : un garde-fou réutilisable autorisant **une seule** transmission
personnelle, liée au fournisseur, au modèle, à l'objectif et au contenu sérialisé
exact.

Un commit propre est livré sur cette branche. Aucun merge dans `main`, aucun
appel cloud réel, aucune donnée personnelle réelle, transports fictifs uniquement.

---

## A. Objectif

Rendre la transmission de donnée personnelle vers un fournisseur cloud
**vérifiable octet par octet** : un accord préalable, lié à quatre champs,
expirant, consommable une seule fois, révocable, et dont tout refus est décidé
sans aucun appel réseau. Le garde-fou décide et trace ; il ne transporte rien.
Le raccordement reste à l'intégrateur.

## B. Ce qui est livré

Package `consent_guard/` (bibliothèque standard uniquement, Python 3.12) :

* `envelope.py` — sérialisation canonique du contenu (texte, octets, JSON
  trié), empreinte SHA-256, normalisation et validation des quatre champs de
  liaison, calcul d'expiration borné, objets `TransmissionRequest`,
  `ConsentEnvelope`, `ConsentDecision`, `TransmissionReceipt`.
* `guard.py` — `ConsentGuard.grant / check / consume / revoke / active /
  journal / stats / forget_everything`, protocole `CloudTransport` et fonction
  `transmit(...)` qui n'appelle l'expéditeur qu'après consommation.
* `store.py` — SQLite locale privée (dossier `0700`, base et journaux `0600`,
  WAL, `synchronous = FULL`), consommation atomique via
  `BEGIN IMMEDIATE` + `UPDATE … WHERE uses_consumed < uses_allowed`, journal des
  refus sans contenu, effacement complet avec compactage.
* `errors.py` — erreurs sûres en français, codes de refus stables et repli
  documenté (`local_engine`).
* `check.py` — contrôle à blanc d'une demande : valide, empreinte, n'envoie et
  ne mémorise rien.
* `demo.py` — démonstration locale en 13 étapes sur données synthétiques, avec
  un transport fictif qui compte ses appels.
* `contracts/integration_contract.json` — contrat d'intégration lisible par
  machine (garanties, signatures, codes, limites).
* `fixtures/synthetic_transmission.json` — demande entièrement synthétique.

Documentation : `docs/CONSENT_GUARD_CONTRACT.md` (contrat d'intégration) et
`consent_guard/README.md`.

## C. Comportement garanti

| Exigence | Réalisation |
| --- | --- |
| Une seule transmission | `uses_allowed = 1`, constante non configurable |
| Liée au fournisseur, modèle, objectif, contenu | `envelope_mismatch` dès qu'un champ diffère |
| Modification du contenu ou du modèle invalide | empreinte comparée avec `hmac.compare_digest` |
| Expiration | TTL 900 s par défaut, plafond 86 400 s, frontière inclusive |
| Consommation unique | `UPDATE` conditionnel atomique ; rejeu → `consent_exhausted` |
| Refus sans appel réseau | décision avant tout transport ; sockets neutralisés dans les tests |
| Révocation | explicite, définitive ; un accord consommé ne se révoque pas |
| Repli | `fallback = "local_engine"` + `fallback_notice(decision)` |
| Aucun contenu dans les traces | empreinte seule en base ; `payload` hors `repr()` ; zéro log dans le paquet |

Ordre d'évaluation des refus : `consent_unknown` → `consent_revoked` →
`envelope_mismatch` → `consent_expired` → `consent_exhausted`. La correspondance
est examinée avant l'état : un accord qui ne couvre pas la demande ne la couvre
pas, quel que soit son âge.

## D. Fichiers ajoutés (aucun fichier existant modifié)

```
consent_guard/__init__.py
consent_guard/check.py
consent_guard/contracts/integration_contract.json
consent_guard/demo.py
consent_guard/envelope.py
consent_guard/errors.py
consent_guard/fixtures/synthetic_transmission.json
consent_guard/guard.py
consent_guard/README.md
consent_guard/store.py
docs/CONSENT_GUARD_CONTRACT.md
HANDOFF_consent_guard.md
tests/test_consent_guard_binding.py
tests/test_consent_guard_contract.py
tests/test_consent_guard_envelope.py
tests/test_consent_guard_expiry.py
tests/test_consent_guard_guard.py
tests/test_consent_guard_isolation.py
tests/test_consent_guard_offline.py
tests/test_consent_guard_replay.py
```

Fichiers **non** touchés, comme demandé : `come_ai_web.py`, `hybrid_chat.py`,
routeurs existants, bases de données, `.env` / `.env.example`, interface
principale (`app_v3.py`, `v5_static/`, `web_static/`, `run_come_ai_v3.py`),
`pytest.ini`, `requirements-v3.txt`, ainsi que tous les paquets des autres lots
(`personal_profile`, `study_coach`, `career`, `devkit`, `evals`, …).

## E. Tests réellement exécutés

```bash
cd /Users/comedelavenne/AI-Excel-Agent-v3-consent
PYTHONDONTWRITEBYTECODE=1 /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python \
  -m pytest -q -p no:cacheprovider tests/test_consent_guard_*.py
```

**185 passed in 3.19 s** (185 tests, 8 fichiers dédiés).

Couverture des exigences demandées :

| Exigence | Fichier | Tests |
| --- | --- | --- |
| Modification de chaque champ | `test_consent_guard_binding.py` | 27 (fournisseur, modèle, objectif, contenu : un caractère, une espace, un élément retiré/ajouté, un nombre, une clé, un type, des octets) |
| Changement de modèle | `test_consent_guard_binding.py` | inclus + empreinte de liaison |
| Expiration | `test_consent_guard_expiry.py` | 11 (frontière inclusive, TTL plafonné, non-résurrection, `mark_expired`) |
| Rejeu | `test_consent_guard_replay.py` | 9 (rejeu refusé, 8 threads → un seul gagnant, 6 threads → un seul envoi) |
| Refus | `test_consent_guard_offline.py` | 16 (transport interdit jamais appelé, `check` sans levée, demande invalide) |
| Fallback | `test_consent_guard_offline.py` | repli `local_engine`, phrase sûre, transport après succès seulement |
| Absence de contenu personnel dans les logs | `test_consent_guard_offline.py`, `test_consent_guard_guard.py` | zéro enregistrement de log, octets de la base scannés, `repr()` et `as_dict()` scannés, journal codes seuls |
| Contrat, outil, fixture | `test_consent_guard_contract.py` | 18 (contrôle à blanc, codes de sortie CLI, fixture synthétique, démonstration) |
| Isolation et non-régression | `test_consent_guard_isolation.py` | 23 (AST : aucun import réseau, stdlib seule, aucun module protégé, périmètre Git, sockets neutralisés, contrat JSON cohérent) |
| Enveloppe | `test_consent_guard_envelope.py` | 59 (sérialisation canonique, empreintes, validation des champs, expiration) |

Autres commandes exécutées :

```bash
PYTHONDONTWRITEBYTECODE=1 …/python -m consent_guard.demo            # 27/27 vérifications OK
PYTHONDONTWRITEBYTECODE=1 …/python -m consent_guard.demo --json     # success: true, transport_calls: 1
PYTHONDONTWRITEBYTECODE=1 …/python -m consent_guard.check consent_guard/fixtures/synthetic_transmission.json
git diff --check                                                      # aucune trace d'espace en fin de ligne
```

Aucun test n'utilise de transport réseau ; les seuls expéditeurs présents sont
des objets fictifs définis dans les tests et dans la démonstration.

## F. Interaction connue avec le gardien d'un autre lot

`tests/test_personal_profile_isolation.py::TestNoProtectedFileTouched::
test_no_module_outside_the_package_is_modified` (fichier d'un autre lot, **non
modifié**) exécute `git ls-files --modified --others --exclude-standard` et
échoue si des fichiers étrangers à `personal_profile/` sont **non suivis par
Git**. Tant que ce lot n'est pas indexé, cette assertion voit `consent_guard/`
comme du travail en cours et échoue.

Vérifié : `git add` puis `git ls-files --modified --others --exclude-standard`
ne renvoie plus rien (0 fichier) et le test redevient vert. C'est une
interaction d'index Git, pas une régression fonctionnelle. La résolution
retenue est le commit de ce lot, comme demandé par la mission.

## G. Ce qui n'a **pas** été vérifié

* La suite complète du dépôt n'est relancée qu'après commit (l'interaction du
  point F disparaît alors) ; le résultat final est consigné au point J.
* Aucune exécution dans un navigateur, aucune montée en charge, aucun test sur
  disque réseau ou dossier synchronisé (Dropbox/iCloud).
* Aucun test de recours réel contre un fournisseur cloud : interdit par la
  mission, et le paquet n'en a aucun.
* Aucune vérification de la politique de rétention du journal des refus au-delà
  de sa borne en mémoire.

## H. Limites assumées

* **Pas d'interface de demande d'accord** : l'écran, la case à cocher et le
  rappel de la portée « une seule transmission » restent à construire.
* **Pas de transport** : `sender` est fourni par l'intégrateur ; aucune stratégie
  de réessai, de chiffrement ou de délai n'existe ici.
* **Pas de routage** : le garde-fou ne choisit ni fournisseur ni modèle et ne
  connaît aucun catalogue.
* **Persistance locale uniquement** : un accord n'est valable que sur la machine
  qui l'a délivré ; aucune synchronisation entre appareils.
* **Granularité de l'appel** : découper un contenu en plusieurs envois demande
  plusieurs accords.
* **Deux familles d'erreurs** : `grant` lève `EnvelopeError` pour une demande
  mal formée, `consume` lève `ConsentRefusal` ; toutes deux dérivent de
  `ConsentGuardError`.
* **L'ordre des clés d'un objet JSON est neutre, celui d'une liste ne l'est
  pas** : réordonner une liste de contexte exige un nouvel accord. C'est
  volontaire — la liste sérialisée est le contenu.

## I. Intégration — ce que l'intégrateur doit faire

```python
from consent_guard import ConsentGuard, transmit

guard = ConsentGuard(base_dir / "consent_data")          # dossier privé local

# 1. Contenu borné, jamais une liste de profils entière.
contenu = "…"

# 2. Accord affiché à l'utilisateur (fournisseur, modèle, objectif, extrait).
grant = guard.grant(contenu, provider="gemini",
                    model="gemini-3.8-flash", purpose="exam_revision")

# 3. Au moment de l'appel, une seule fois :
reponse = transmit(guard, grant.consent_id,
                   provider="gemini", model="gemini-3.8-flash",
                   purpose="exam_revision", payload=contenu,
                   sender=votre_transport_cloud)
```

Sur `ConsentRefusal` : basculer sur le moteur local, afficher
`fallback_notice(decision)`, journaliser `decision.code` — jamais le contenu.

Ordre imposé : `construire le contenu → grant → check → consume → sender.send`.
`hybrid_chat.ask(...)` conserve son paramètre `allow_personal_cloud` : ce lot ne
le remplace pas, il le rend vérifiable octet par octet.

## J. Sécurité

* Aucun import réseau dans le paquet (vérifié par analyse AST) ; sockets
  neutralisés pendant un cycle complet dans les tests.
* Bibliothèque standard uniquement ; aucun module possédé par un autre lot
  n'est importé ni modifié.
* Aucune lecture de fichier de configuration ; l'environnement ne peut pas
  assouplir le garde-fou (tests dédiés).
* Dossier `0700`, base et journaux `0600`, WAL, `synchronous = FULL`.
* Aucune donnée personnelle réelle : la fixture est synthétique, les marqueurs
  de test sont fictifs, et les tests scannent les octets de la base pour
  prouver l'absence de fuite.

## K. État Git

```bash
git log --oneline -1                       # commit du lot sur feature/v3-consent-guard
git diff --name-only c32b284 HEAD          # ajouts du lot uniquement
git status --short                         # arbre propre
```

Aucun merge dans `main`, aucune autre branche touchée.

## L. Démonstration en 2 minutes

```bash
cd /Users/comedelavenne/AI-Excel-Agent-v3-consent
python -m consent_guard.demo
python -m consent_guard.check consent_guard/fixtures/synthetic_transmission.json
python -m pytest -q tests/test_consent_guard_*.py
```

La démonstration enchaîne : refus sans accord, octroi lié, transmission unique
via un transport fictif, rejeu refusé, modification d'un caractère du contenu,
changement de modèle, d'objectif et de fournisseur, expiration, révocation,
repli local, journal des refus sans contenu, effacement complet — 27
vérifications, toutes vertes.

## M. État final

Livré, testé, documenté, commité sur `feature/v3-consent-guard`. Le
raccordement au chat, aux routeurs cloud et à l'interface reste à faire par
l'intégrateur, conformément au contrat `docs/CONSENT_GUARD_CONTRACT.md`.
