# CONSENT GUARD V1 — CONTRAT D'INTÉGRATION

Branche : `feature/v3-consent-guard` · Base : `integration/profile-study` @ `c32b284`
Package : `consent_guard/` · Contrat : `come-consent-guard-envelope/1` · Version : `1.0.0`
Destinataire : l'intégrateur (raccordement de `hybrid_chat`, des routeurs cloud et de l'interface).

> Aucun merge dans `main` n'a été fait. Aucun appel cloud réel n'a été effectué.
> Aucune donnée personnelle réelle n'a été utilisée. Transports fictifs uniquement.

---

## 1. Principes non négociables

1. **Un accord, une transmission.** `uses_allowed` vaut toujours `1`. Il n'existe
   aucun réglage, aucune variable d'environnement et aucun paramètre pour
   l'autoriser à plusieurs usages.
2. **L'accord est lié.** Il couvre exactement un quadruplet : fournisseur,
   modèle, objectif, empreinte du contenu sérialisé. Changer l'un des quatre
   invalide l'accord.
3. **Le contenu ne circule jamais en clair dans le garde-fou.** Seule son
   empreinte SHA-256 et sa taille sont stockées. Aucun message d'erreur, aucun
   `repr()`, aucun journal ne le contient.
4. **Le refus précède l'appel.** Tout refus est décidé avant tout contact avec un
   fournisseur : aucun socket, aucune clé, aucun catalogue de modèles.
5. **Le paquet est muet sur le transport.** Il n'embarque aucun expéditeur. Le
   `sender` est fourni par l'intégrateur et appelé après consommation seulement.
6. **Le garde-fou ne route rien.** Le choix du fournisseur et du modèle appartient
   à l'appelant, et fait partie de l'accord.

---

## 2. Point d'entrée unique

```python
from consent_guard import ConsentGuard, transmit
```

| Méthode | Rôle | Retour | Lève |
| --- | --- | --- | --- |
| `guard.grant(payload, *, provider, model, purpose, actor="", note="", ttl_seconds=None, expires_at=None, consent_id=None)` | enregistre un accord | `ConsentEnvelope` | `ConsentGuardError` si la demande est mal formée |
| `guard.check(consent_id, *, provider, model, purpose, payload, request=None, now=None)` | décide sans lever | `ConsentDecision` | jamais pour un refus |
| `guard.consume(consent_id, *, provider, model, purpose, payload, request=None)` | consomme une fois | `TransmissionReceipt` | `ConsentRefusal` |
| `transmit(guard, consent_id, *, provider, model, purpose, payload, sender)` | vérifie, consomme, envoie | réponse du `sender` | `ConsentRefusal` |
| `guard.revoke(consent_id, *, actor="", note="")` | révoque | `ConsentEnvelope` | `UnknownConsentError`, `StoreError` |
| `guard.get(consent_id)` / `guard.active()` / `guard.journal()` / `guard.stats()` / `guard.forget_everything()` | état et diagnostic | objets, tuples, dictionnaire, booléen | `StoreError` |

---

## 3. Modèle de données

### `TransmissionRequest` — ce que l'appelant veut envoyer

Champs : `provider`, `model`, `purpose`, `payload` (+ `digest`, `size` calculés).

* `payload` accepte du texte (`str`), des octets (`bytes`) ou une structure JSON
  (tableau associatif, liste).
* `payload` est exclu de `repr()` et de la comparaison : deux demandes sont
  comparées par empreinte, jamais par contenu, et aucune trace d'appel ne peut le
  révéler.
* `as_dict()` ne rend que les métadonnées et l'empreinte.

### `ConsentEnvelope` — l'accord mémorisé

| Champ | Rôle |
| --- | --- |
| `consent_id` | identifiant stable `cgt_<hex>` |
| `provider`, `model`, `purpose` | cible liée |
| `payload_digest`, `payload_bytes` | empreinte et taille du contenu autorisé |
| `issued_at`, `expires_at` | instants UTC `YYYY-MM-DDTHH:MM:SSZ` |
| `state` | `granted`, `used`, `revoked` |
| `uses_allowed`, `uses_consumed`, `consumed_at` | consommation unique |
| `actor`, `note` | traçabilité de l'accord |
| `binding_digest` | empreinte des cinq champs de liaison |

Aucun champ ne contient de contenu personnel.

### `ConsentDecision` — la réponse de `check`

`allowed`, `code`, `message`, `fallback`, `consent_id`, `fields`.
`fields` nomme les champs divergents (`provider`, `model`, `purpose`, `payload`)
sans jamais révéler leur valeur.

### `TransmissionReceipt` — la preuve de consommation

`transmission_id`, `consent_id`, `provider`, `model`, `purpose`,
`payload_digest`, `payload_bytes`, `consumed_at`. Le reçu prouve l'usage ; il ne
contient ni le contenu ni aucune clé.

---

## 4. Sérialisation et empreinte

| Type de contenu | Octets sérialisés |
| --- | --- |
| `str` | octets UTF-8 exacts de la chaîne |
| `bytes` | octets exacts |
| structure JSON | JSON canonique (`sort_keys`, séparateurs compacts, `ensure_ascii=False`) encodé en UTF-8 |

L'empreinte est `SHA-256` hexadécimale de ces octets.

Conséquence à connaître avant tout raccordement : **l'ordre des clés d'un objet
ne change pas l'empreinte, l'ordre des éléments d'une liste la change**. Une
liste de contexte personnel est donc un contenu ordonné : la réordonner exige un
nouvel accord. C'est volontaire — la liste sérialisée est le contenu.

Limites : `MAX_PAYLOAD_BYTES = 262_144` (256 Kio), contenu vide refusé, types non
sérialisables refusés.

---

## 5. Expiration, consommation unique, révocation

* Durée de vie par défaut : `DEFAULT_TTL_SECONDS = 900`. Plafond absolu :
  `MAX_TTL_SECONDS = 86_400`, non configurable au-delà.
* La frontière est inclusive : à l'instant d'expiration exact, l'accord est déjà
  expiré.
* Un accord expiré n'est jamais réanimé. `store.mark_expired()` peut le clore
  en `revoked` ; sans appel, il reste `granted` mais refusé.
* La consommation est atomique au niveau de la base (`BEGIN IMMEDIATE` +
  `UPDATE … WHERE uses_consumed < uses_allowed`) : deux threads ou deux processus
  ne peuvent pas consommer le même accord, le second reçoit `consent_exhausted`.
* Une révocation est explicite et définitive. Un accord consommé ne se révoque
  pas : il est clos.

---

## 6. Codes de refus et repli

Ordre d'évaluation : `consent_unknown` → `consent_revoked` →
`envelope_mismatch` → `consent_expired` → `consent_exhausted`.

La correspondance est examinée avant l'état : un accord qui ne couvre pas la
demande ne la couvre pas, quel que soit son âge.

| Code | Signification | Action recommandée |
| --- | --- | --- |
| `consent_unknown` | identifiant inconnu | redemander un accord |
| `consent_revoked` | accord révoqué | redemander un accord |
| `envelope_mismatch` | un champ diffère (`fields`) | redemander un accord pour la bonne cible |
| `consent_expired` | accord trop vieux | redemander un accord |
| `consent_exhausted` | accord déjà consommé | ne pas rejouer |
| `invalid_request` (+ `payload_*`) | demande mal formée | corriger la demande |

Tous portent `fallback = "local_engine"` : traiter la demande en local, sans
transmission, et l'annoncer à l'utilisateur. `fallback_notice(decision)` rend la
phrase affichable, sans contenu ni identifiant de modèle.

---

## 7. Erreurs

```
ConsentGuardError (ValueError)
├── EnvelopeError          demande ou enveloppe mal formée (grant, construction)
├── StoreError             persistance locale indisponible
└── ConsentRefusal         transmission refusée, avec .code, .fields, .fallback
    ├── InvalidRequestError       invalid_request, payload_empty, payload_too_large, …
    ├── UnknownConsentError       consent_unknown
    ├── RevokedConsentError       consent_revoked
    ├── EnvelopeMismatchError     envelope_mismatch
    ├── ExpiredConsentError       consent_expired
    └── ConsumedConsentError      consent_exhausted
```

Tous les messages sont en français, sans chemin absolu, sans extrait de contenu,
sans clé et sans détail d'implémentation. `except ConsentGuardError` suffit à
traiter les deux familles.

---

## 8. Raccordement — ce que l'intégrateur doit faire

1. Instancier un garde-fou par espace de travail, dans un dossier privé :
   `guard = ConsentGuard(base_dir / "consent_data")`.
2. Construire le contenu personnel à transmettre (contexte borné, jamais une
   liste de profils entière).
3. Demander l'accord dans l'interface : fournisseur, modèle, objectif visibles,
   extrait du contenu affiché à l'utilisateur, portée « une seule transmission ».
4. `grant = guard.grant(contenu, provider=…, model=…, purpose=…, ttl_seconds=…)`.
5. Au moment de l'appel :
   `receipt = transmit(guard, grant.consent_id, provider=…, model=…, purpose=…, payload=contenu, sender=votre_transport)`.
6. Sur `ConsentRefusal` : basculer sur le moteur local, afficher
   `fallback_notice(decision)`, journaliser `decision.code` — jamais le contenu.
7. Enregistrer `receipt` dans le journal d'usage existant (métadonnées seules).

`hybrid_chat.ask(...)` conserve son paramètre `allow_personal_cloud` : ce lot ne
le remplace pas, il le rend vérifiable octet par octet. Le garde-fou ne remplace
pas non plus le routage ni le catalogue de modèles.

### Ordre imposé dans le code appelant

```
construire le contenu → grant (accord UI) → check → consume → sender.send
```

`sender.send` n'est jamais atteint si l'une des quatre étapes précédentes échoue.

---

## 9. Isolation vérifiée

* Aucun import réseau (`socket`, `ssl`, `http`, `httpx`, `requests`, `urllib`,
  `asyncio`, `openai`, `anthropic`, `google`, …) dans le paquet : vérifié par
  analyse AST dans `tests/test_consent_guard_isolation.py`.
* Bibliothèque standard uniquement ; aucun module possédé par un autre lot n'est
  importé (`hybrid_chat`, `intelligence_bridge`, `come_ai_web`,
  `free_ai_router`, `v5_orchestrator`, `workspace_core`, `personal_memory`,
  `memory_storage`, `task_queue`, `usage_ledger`, `career`, `devkit`, `evals`,
  `personal_profile`, `study_coach`).
* Les sockets sont neutralisés pendant un cycle complet dans les tests.
* Aucun fichier de configuration n'est lu ; l'environnement ne peut pas assouplir
  le garde-fou.
* Dossier `0700`, base et journaux `0600`, mode WAL, `synchronous = FULL`.

---

## 10. Limites à connaître avant tout raccordement

* **Pas d'interface.** La demande d'accord (écran, case à cocher, rappel de la
  portée) reste à construire par l'intégrateur.
* **Pas de transport.** `sender` est fourni par l'appelant ; aucune stratégie de
  réessai, de chiffrement ou de délai n'existe ici.
* **Pas de routage.** Le garde-fou ne choisit ni fournisseur ni modèle, et ne
  connaît aucun catalogue.
* **Persistance locale uniquement.** Une base SQLite par dossier de travail ;
  aucune synchronisation entre appareils, donc un accord n'est valable que sur la
  machine qui l'a délivré.
* **Le journal des refus est local et borné** (`journal(limit=200)` par défaut) ;
  il ne contient que des codes, des champs et des horodatages.
* **`grant` et `consume` ne partagent pas la même famille d'erreurs** : `grant`
  lève `EnvelopeError` pour une demande mal formée, `consume` lève
  `ConsentRefusal`. Les deux dérivent de `ConsentGuardError`.
* **La granularité est l'appel.** Un accord couvre un envoi ; découper un contenu
  en plusieurs envois demande plusieurs accords.

---

## 11. Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_consent_guard_*.py
```

Démonstration et contrôle à blanc :

```bash
python -m consent_guard.demo
python -m consent_guard.check consent_guard/fixtures/synthetic_transmission.json
```

Aucune donnée personnelle réelle, aucun appel réseau, transports fictifs
uniquement. Les résultats chiffrés sont consignés dans `HANDOFF_consent_guard.md`.
