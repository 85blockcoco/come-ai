"""Contrôle à blanc d'une demande de transmission, sans rien envoyer.

Usage :

    python -m consent_guard.check consent_guard/fixtures/synthetic_transmission.json
    python -m consent_guard.check --ttl 600 --json demande.json

Le contrôle lit un fichier JSON local décrivant une demande de transmission
(fournisseur, modèle, objectif, contenu), valide chaque champ, calcule
l'empreinte et la taille du contenu sérialisé, puis affiche un rapport sûr.
Il n'écrit rien, ne mémorise aucun accord, n'appelle aucun fournisseur et
n'imprime jamais le contenu lui-même.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from .envelope import (
    CONTRACT_ID,
    TransmissionRequest,
    resolve_expiry,
)

#: Schéma attendu d'une demande de transmission sérialisée.
REQUEST_SCHEMA = "come-consent-guard-request/1"


def check_request(
    data: Any, *, ttl_seconds: int | None = None
) -> tuple[bool, list[str], dict[str, Any]]:
    """Valide une demande et renvoie (ok, lignes, résumé sûr)."""

    lines: list[str] = []
    if not isinstance(data, dict):
        return False, ["ERREUR : la demande doit être un objet JSON."], {}

    schema = data.get("schema")
    if schema != REQUEST_SCHEMA:
        return False, [f"ERREUR : schéma « {schema} » inconnu, attendu « {REQUEST_SCHEMA} »."], {}

    try:
        request = TransmissionRequest(
            provider=data.get("provider", ""),
            model=data.get("model", ""),
            purpose=data.get("purpose", ""),
            payload=data.get("payload"),
        )
        expires_at = resolve_expiry(ttl_seconds=ttl_seconds)
    except ValueError as error:
        lines.append(f"ERREUR : {error}")
        return False, lines, {}

    summary = {
        "contract": CONTRACT_ID,
        "provider": request.provider,
        "model": request.model,
        "purpose": request.purpose,
        "payload_digest": request.digest,
        "payload_bytes": request.size,
        "expires_at_if_granted_now": expires_at,
        "single_use": True,
    }
    lines.append(f"Contrat       : {CONTRACT_ID}")
    lines.append(f"Fournisseur   : {request.provider}")
    lines.append(f"Modèle        : {request.model}")
    lines.append(f"Objectif      : {request.purpose}")
    lines.append(f"Empreinte     : {request.digest}")
    lines.append(f"Taille        : {request.size} octets sérialisés")
    lines.append(f"Usage unique  : oui (une seule transmission par accord)")
    lines.append(f"Si accordé maintenant, expiration : {expires_at}")
    lines.append("Contenu       : non affiché, non mémorisé, jamais journalisé")
    return True, lines, summary


def check_text(text: str, *, ttl_seconds: int | None = None) -> tuple[bool, list[str], dict[str, Any]]:
    """Valide un texte JSON de demande de transmission."""

    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as error:
        return False, [f"ERREUR : le fichier n'est pas un JSON valide ({error.msg}, ligne {error.lineno})."], {}
    return check_request(data, ttl_seconds=ttl_seconds)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m consent_guard.check",
        description="Contrôle à blanc d'une demande de transmission (aucun envoi, aucune mémorisation).",
    )
    parser.add_argument("fichier", help="Chemin du fichier JSON de demande.")
    parser.add_argument("--ttl", type=int, default=None, help="Durée de validité simulée, en secondes.")
    parser.add_argument("--json", action="store_true", help="N'imprimer que le rapport JSON.")
    arguments = parser.parse_args(list(argv) if argv is not None else None)

    path = Path(arguments.fichier).expanduser()
    if not path.is_file():
        print(f"ERREUR : fichier introuvable ({path.name}).", file=sys.stderr)
        return 2
    ok, lines, summary = check_text(path.read_text(encoding="utf-8"), ttl_seconds=arguments.ttl)
    if arguments.json:
        payload = {"ok": ok, "lines": lines, "summary": summary}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    print()
    print("=" * 78)
    print(" CONSENT GUARD — CONTRÔLE À BLANC D'UNE DEMANDE DE TRANSMISSION")
    print("=" * 78)
    for line in lines:
        print(f" {line}")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover - point d'entrée CLI
    raise SystemExit(main())
