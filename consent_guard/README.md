# consent_guard — garde-fou de consentement cloud

Package autonome, local et intégrable. Il autorise **une seule** transmission de
donnée personnelle, liée à quatre champs : le fournisseur, le modèle, l'objectif
et l'empreinte du contenu sérialisé exact. Toute modification du contenu ou du
modèle invalide l'accord.

Contrat : `come-consent-guard-envelope/1` · Version : `1.0.0` · Python 3.12,
bibliothèque standard uniquement.

## Ce que le paquet fait

| Méthode | Rôle |
| --- | --- |
| `guard.grant(payload, *, provider, model, purpose, ttl_seconds=…)` | enregistre un accord unique, lié et daté |
| `guard.check(consent_id, *, provider, model, purpose, payload)` | répond sans lever : autorisé ou refusé, avec un code stable |
| `guard.consume(consent_id, *, provider, model, purpose, payload)` | consomme l'accord de façon atomique et rend un reçu |
| `transmit(guard, consent_id, *, …, sender)` | vérifie, consomme, puis appelle l'expéditeur **une fois** |
| `guard.revoke(consent_id)` | révoque un accord avant expiration |
| `guard.active()` / `guard.journal()` / `guard.stats()` | état, refus tracés, compteurs |

## Ce que le paquet ne fait pas

* aucun appel réseau, aucun socket, aucune clé de fournisseur, aucun catalogue
  de modèles ;
* aucun transport, fictif ou réel : `sender` est fourni par l'intégrateur et
  appelé seulement après une consommation réussie ;
* aucun routage : choisir le fournisseur et le modèle reste à l'appelant, et ce
  choix fait partie de l'accord ;
* aucune lecture de fichier de configuration ou de variable d'environnement.

## Codes de refus

Évalués dans cet ordre : `consent_unknown` → `consent_revoked` →
`envelope_mismatch` → `consent_expired` → `consent_exhausted`.

Une demande mal formée donne `invalid_request`, précisé par `payload_empty`,
`payload_too_large`, `payload_type` ou `payload_unserialisable`.

Chaque refus porte un `fallback` : `local_engine`, c'est-à-dire traiter la
demande en local et l'annoncer à l'utilisateur.

## Exemple

```python
from consent_guard import ConsentGuard, transmit

guard = ConsentGuard("/dossier/local/prive")
grant = guard.grant(
    provider="gemini",
    model="gemini-3.8-flash",
    purpose="exam_revision",
    payload="Contexte synthétique à transmettre.",
    ttl_seconds=900,
)

decision = guard.check(
    grant.consent_id,
    provider="gemini",
    model="gemini-3.8-flash",
    purpose="exam_revision",
    payload="Contexte synthétique à transmettre.",
)
if decision.allowed:
    receipt = guard.consume(
        grant.consent_id,
        provider="gemini",
        model="gemini-3.8-flash",
        purpose="exam_revision",
        payload="Contexte synthétique à transmettre.",
    )
    # receipt prouve la consommation ; l'intégrateur transmet ici, une seule fois.
```

## Lignes de commande

```bash
python -m consent_guard.demo                                  # démonstration locale complète
python -m consent_guard.check consent_guard/fixtures/synthetic_transmission.json
python -m pytest -q tests/test_consent_guard_*.py
```

## Fichiers

```
consent_guard/
    __init__.py     barrel et contrat
    errors.py       erreurs sûres et codes de refus stables
    envelope.py     sérialisation canonique, empreinte, champs, expiration
    guard.py        ConsentGuard, transmit, protocole CloudTransport
    store.py        SQLite locale privée, consommation atomique
    check.py        contrôle à blanc d'une demande (rien n'est envoyé)
    demo.py         démonstration sur données synthétiques
    contracts/integration_contract.json   contrat d'intégration lisible par machine
    fixtures/synthetic_transmission.json  demande entièrement synthétique
```

Aucune donnée personnelle réelle n'est utilisée, lue ou écrite par ce paquet.
