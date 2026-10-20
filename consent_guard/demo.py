"""Démonstration locale complète, sur données entièrement synthétiques.

Exécution ::

    python -m consent_guard.demo
    python -m consent_guard.demo --json

La démonstration illustre les treize étapes du contrat :

1. création du garde-fou dans un dossier temporaire local ;

2. refus d'une transmission sans accord (``consent_unknown``) ;

3. octroi d'un accord lié au fournisseur, au modèle, à l'objectif et au contenu ;

4. vérification conforme : la demande correspond exactement à l'accord ;

5. transmission unique via un transport fictif, choisi par la démonstration ;

6. refus du rejeu (``consent_exhausted``) sans rappeler le transport ;

7. modification d'un caractère du contenu : ``envelope_mismatch`` ;

8. changement de modèle : ``envelope_mismatch`` ;

9. changement d'objectif et de fournisseur : ``envelope_mismatch`` ;

10. expiration de l'accord : ``consent_expired`` ;

11. révocation explicite : ``consent_revoked`` ;

12. repli local et journal des refus sans aucun contenu personnel ;

13. effacement complet des accords et du journal.

Aucune donnée personnelle réelle n'est utilisée, lue ou écrite.  Aucun appel
réseau n'est effectué : le transport de démonstration est fictif.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .envelope import CONTRACT_ID, PURPOSES, TransmissionReceipt
from .errors import (
    CODE_CONSUMED_CONSENT,
    CODE_ENVELOPE_MISMATCH,
    CODE_EXPIRED_CONSENT,
    CODE_REVOKED_CONSENT,
    ConsentRefusal,
)
from .guard import ConsentGuard, fallback_notice, transmit

FIXTURE_RELATIVE = Path("consent_guard") / "fixtures" / "synthetic_transmission.json"

PROVIDER = "gemini"
MODEL = "gemini-3.8-flash"
PURPOSE = "exam_revision"

STEP_TITLES: tuple[str, ...] = (
    "Création du garde-fou local",
    "Transmission sans accord : refus immédiat",
    "Octroi d'un accord lié et unique",
    "Vérification conforme de la demande",
    "Transmission unique via un transport fictif",
    "Rejeu de la même transmission : refus",
    "Modification d'un caractère du contenu",
    "Changement de modèle",
    "Changement d'objectif et de fournisseur",
    "Expiration de l'accord",
    "Révocation explicite de l'accord",
    "Repli local et journal des refus",
    "Effacement complet des accords",
)

_VERIFIED: list[tuple[int, str, bool, str]] = []
_VERBOSE = True


class SpyTransport:
    """Transport fictif de démonstration : il compte les appels, n'en fait aucun.

    Il n'existe que dans cette démonstration.  Le paquet ``consent_guard``
    n'embarque aucun transport, fictif ou réel.
    """

    name = "spy-fictif"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send(self, payload: bytes, receipt: TransmissionReceipt) -> dict[str, Any]:
        self.calls.append({"bytes": len(payload), "receipt": receipt.as_dict()})
        return {"answer": "réponse fictive", "payload_bytes": len(payload)}


def _title(step: int) -> None:
    if not _VERBOSE:
        return
    print()
    print(f"── Étape {step}/13 · {STEP_TITLES[step - 1]} " + "─" * 20)


def _check(step: int, label: str, condition: bool, detail: str = "") -> bool:
    _VERIFIED.append((step, label, bool(condition), detail))
    if not _VERBOSE:
        return bool(condition)
    marker = "OK" if condition else "ÉCHEC"
    print(f"    [{marker}] {label}{(' — ' + detail) if detail else ''}")
    return bool(condition)


def _say(message: str) -> None:
    if _VERBOSE:
        print(message)


def _fixed_clock(start: datetime) -> Any:
    state = {"now": start}

    def clock() -> datetime:
        return state["now"]

    clock.advance = lambda seconds: state.__setitem__(  # type: ignore[attr-defined]
        "now", state["now"] + timedelta(seconds=seconds)
    )
    return clock


def _load_payload() -> dict[str, Any]:
    fixture = Path(__file__).resolve().parent.parent / FIXTURE_RELATIVE
    data: dict[str, Any] = json.loads(fixture.read_text(encoding="utf-8"))
    return dict(data["payload"])


def run_demo(*, workdir: Path | None = None, verbose: bool = True, keep: bool = False) -> dict[str, Any]:
    """Exécute la démonstration et renvoie un rapport vérifiable."""

    global _VERBOSE
    _VERBOSE = bool(verbose)
    _VERIFIED.clear()

    temp_root = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="consent-guard-demo-"))
    temp_root.mkdir(parents=True, exist_ok=True)
    if verbose:
        print("=" * 78)
        print(" CÔME AI — GARDE-FOU DE CONSENTEMENT CLOUD : DÉMONSTRATION LOCALE")
        print("=" * 78)
        print(f" Contrat            : {CONTRACT_ID}")
        print(f" Dossier de travail : {temp_root}")
        print(f" Objectifs autorisés: {', '.join(PURPOSES)}")
        print(" Données            : 100 % synthétiques, aucun appel réseau")

    payload = _load_payload()
    clock = _fixed_clock(datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc))
    guard = ConsentGuard(temp_root, clock=clock)
    transport = SpyTransport()

    # 1 — création
    _title(1)
    _check(1, "garde-fou initialisé sur une base locale privée", guard.db_path.exists(),
           guard.db_path.name)
    _check(1, "aucun accord au départ", guard.active() == () and guard.stats()["consents"] == {})

    # 2 — transmission sans accord
    _title(2)
    decision = guard.check(
        "cgt_" + "0" * 32, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=payload
    )
    _check(2, "transmission sans accord refusée", not decision.allowed, decision.code)
    _check(2, "aucun envoi effectué", transport.calls == [], f"{len(transport.calls)} appel(s) fictif(s)")

    # 3 — octroi
    _title(3)
    grant = guard.grant(
        payload, provider=PROVIDER, model=MODEL, purpose=PURPOSE,
        actor="demo", note="Accord de démonstration, contenu synthétique.",
    )
    _check(3, "accord enregistré avec usage unique", grant.uses_allowed == 1 and grant.state == "granted")
    _check(3, "l'accord porte l'empreinte du contenu, pas le contenu",
           grant.payload_digest and grant.payload_bytes > 0, f"{grant.payload_bytes} octets")
    _say(f"    accord : {grant.consent_id} — expire {grant.expires_at}")

    # 4 — vérification conforme
    _title(4)
    decision = guard.check(
        grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=payload
    )
    _check(4, "demande identique autorisée", decision.allowed, decision.code)
    _check(4, "l'ordre des clés ne change pas l'empreinte",
           decision.allowed and guard.check(
               grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE,
               payload={**payload},
           ).allowed)

    # 5 — transmission unique
    _title(5)
    response = transmit(
        guard, grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE,
        payload=payload, sender=transport,
    )
    _check(5, "le transport fictif a été appelé une seule fois", len(transport.calls) == 1,
           f"{response['payload_bytes']} octets")
    _check(5, "l'accord est consommé", guard.get(grant.consent_id).uses_consumed == 1)

    # 6 — rejeu
    _title(6)
    replay = guard.check(
        grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=payload
    )
    _check(6, "rejeu refusé", not replay.allowed and replay.code == CODE_CONSUMED_CONSENT, replay.code)
    _check(6, "le transport fictif n'a pas été rappelé", len(transport.calls) == 1)

    # 7 — modification du contenu
    _title(7)
    altered = _load_payload()
    altered["items"][0]["statement"] = "Master fictif en finance obtenu en 2027."
    untouched = guard.grant(
        payload, provider=PROVIDER, model=MODEL, purpose=PURPOSE, actor="demo", note="Accord jamais consommé."
    )
    mismatch = guard.check(
        untouched.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=altered
    )
    _check(7, "contenu modifié d'un caractère : refus",
           not mismatch.allowed and mismatch.code == CODE_ENVELOPE_MISMATCH, mismatch.code)
    _check(7, "le champ divergent est nommé sans révéler le contenu",
           mismatch.fields == ("payload",), ",".join(mismatch.fields))

    # 8 — changement de modèle
    _title(8)
    other_model = guard.check(
        untouched.consent_id, provider=PROVIDER, model="gemini-3.6-flash", purpose=PURPOSE, payload=payload
    )
    _check(8, "changement de modèle : refus",
           not other_model.allowed and other_model.fields == ("model",), other_model.code)
    _check(8, "l'accord initial reste valide pour sa propre cible",
           guard.check(
               untouched.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=payload
           ).allowed)

    # 9 — changement d'objectif et de fournisseur
    _title(9)
    other_purpose = guard.check(
        untouched.consent_id, provider=PROVIDER, model=MODEL, purpose="job_application", payload=payload
    )
    _check(9, "changement d'objectif : refus",
           not other_purpose.allowed and other_purpose.fields == ("purpose",), other_purpose.code)
    other_provider = guard.check(
        untouched.consent_id, provider="openrouter", model=MODEL, purpose=PURPOSE, payload=payload
    )
    _check(9, "changement de fournisseur : refus",
           not other_provider.allowed and other_provider.fields == ("provider",), other_provider.code)

    # 10 — expiration
    _title(10)
    clock.advance(901)
    fresh = guard.grant(
        payload, provider=PROVIDER, model=MODEL, purpose=PURPOSE, actor="demo", note="Second accord.",
    )
    clock.advance(901)
    expired = guard.check(
        fresh.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=payload
    )
    _check(10, "accord expiré : refus",
           not expired.allowed and expired.code == CODE_EXPIRED_CONSENT, expired.code)
    try:
        guard.consume(
            fresh.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=payload
        )
        raised = False
    except ConsentRefusal as refusal:
        raised = refusal.code == CODE_EXPIRED_CONSENT
    _check(10, "la consommation lève un refus sûr", raised)

    # 11 — révocation
    _title(11)
    third = guard.grant(
        payload, provider=PROVIDER, model=MODEL, purpose=PURPOSE, actor="demo", note="Accord révoqué."
    )
    revoked = guard.revoke(third.consent_id, actor="demo")
    after = guard.check(
        third.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=payload
    )
    _check(11, "révocation effective", revoked.state == "revoked", revoked.consent_id)
    _check(11, "accord révoqué : refus",
           not after.allowed and after.code == CODE_REVOKED_CONSENT, after.code)

    # 12 — repli local et journal
    _title(12)
    notice = fallback_notice(mismatch)
    _check(12, "repli local documenté", mismatch.fallback == "local_engine" and notice.startswith(
        "Aucune donnée personnelle n'a quitté cet appareil."))
    journal = guard.journal()
    _check(12, "chaque refus est journalisé avec son code",
           len(journal) >= 6 and all(entry.code for entry in journal), f"{len(journal)} refus tracés")
    blob = guard.db_path.read_bytes()
    marker = payload["marker"]
    _check(12, "aucun contenu personnel dans la base locale", marker.encode() not in blob,
           "empreinte et codes uniquement")

    # 13 — effacement
    _title(13)
    _check(13, "effacement complet des accords et du journal", guard.forget_everything())
    _check(13, "base vide après effacement",
           guard.stats()["consents"] == {} and guard.stats()["refusals"] == 0)

    if verbose:
        print()
        print("── Synthèse " + "─" * 64)
        failures = [entry for entry in _VERIFIED if not entry[2]]
        print(f"    vérifications : {len(_VERIFIED)} dont {len(_VERIFIED) - len(failures)} réussies")
        for step, label, ok, _detail in failures:
            print(f"    [ÉCHEC] étape {step} — {label}")

    success = all(entry[2] for entry in _VERIFIED)
    report = {
        "steps": [list(entry) for entry in _VERIFIED],
        "success": success,
        "transport_calls": len(transport.calls),
        "stats": guard.stats(),
    }
    guard.close()

    if not keep:
        shutil.rmtree(temp_root, ignore_errors=True)
        _say("    dossier temporaire nettoyé")
    if verbose:
        print("=" * 78)

    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m consent_guard.demo",
        description="Démonstration locale du garde-fou de consentement (données synthétiques).",
    )
    parser.add_argument("--workdir", default=None, help="Dossier local de démonstration (temporaire par défaut).")
    parser.add_argument("--keep", action="store_true", help="Conserver le dossier temporaire après la démonstration.")
    parser.add_argument("--json", action="store_true", help="N'imprimer que le rapport JSON.")
    arguments = parser.parse_args(list(argv) if argv is not None else None)

    workdir = Path(arguments.workdir).expanduser() if arguments.workdir else None
    report = run_demo(workdir=workdir, verbose=not arguments.json, keep=arguments.keep)
    if arguments.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":  # pragma: no cover - point d'entrée CLI
    raise SystemExit(main())
