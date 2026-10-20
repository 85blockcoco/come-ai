"""Small integration seam for per-request consent to local-context sharing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from consent_guard import ConsentGuard, TransmissionRequest


def consume_cloud_context_consent(
    storage_dir: Path,
    *,
    provider: str,
    model: str,
    payload: Any,
) -> str:
    """Record and consume one exact provider/model/context authorization.

    The caller must have received an explicit affirmative field on the current
    chat request. The consent database stores the payload digest and metadata,
    not the payload itself.
    """
    request = TransmissionRequest(
        provider=provider,
        model=model,
        # Le contexte du chat contient des extraits de documents personnels :
        # journalisé comme contexte de profil, pas comme un envoi générique.
        purpose="profile_context",
        payload=payload,
    )
    with ConsentGuard(storage_dir) as guard:
        grant = guard.grant(request=request, actor="come_ai_chat_request")
        receipt = guard.consume(
            grant.consent_id,
            provider=provider,
            model=model,
            purpose="profile_context",
            request=request,
        )
    return receipt.transmission_id
