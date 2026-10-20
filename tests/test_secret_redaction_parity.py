"""Divergence de la politique de secrets : interdite entre task_queue et usage_ledger.

Les deux modules portaient chacun leur copie de ``_SECRET_PATTERNS`` et les
listes ont divergé (le préfixe ``AQ.`` n'existait que côté ledger). Ces tests
exigent que chaque appelant protège l'UNION des motifs connus, ce qui force
tout motif nouveau à passer par ``secret_redaction``.
"""

from __future__ import annotations

import task_queue
import usage_ledger
from secret_redaction import SECRET_PATTERNS


SAMPLES = {
    "gemini": "dossier AIzaSYD0123456789abcdefghijklmnopqrstuv affairir?",
    "google_admin": "clé admin AQ.AbCdEfGhIjKlMnOpQrStUv01234 (ne pas stocker)",
    "openrouter": "token sk-or-v1-AbCdEfGhIjKlMnOpQrStUv01234",
    "generic_key": "authentification sk_0123456789abcdef",
    "bearer_header": "authorization: Bearer AbCdEfGh123456789",
}

SECRET_PATTERNS  # importé pour vérifier que le registre existe et n'est pas vide
assert len(SECRET_PATTERNS) >= 5


def test_task_queue_covers_the_full_union_of_patterns() -> None:
    for label, sample in SAMPLES.items():
        redacted = task_queue.redact_text(sample)
        assert "[secret redacted]" in redacted, f"{label} : {sample} doit être masqué"
        assert "AIzaSYD" not in redacted
        assert "AQ." not in redacted
        assert "sk-or-v1-" not in redacted
        assert "sk_0123456789abcdef" not in redacted
        assert "Bearer AbCdEfGh123456789" not in redacted


def test_usage_ledger_covers_the_full_union_of_patterns() -> None:
    for label, sample in SAMPLES.items():
        redacted = usage_ledger.redact_text(sample)
        assert "[redacted]" in redacted, f"{label} : {sample} doit être masqué"
        assert "AQ." not in redacted
        assert "AIzaSYD" not in redacted
        assert "sk-or-v1-" not in redacted


def test_payload_redaction_is_shared() -> None:
    payload = {"api_key": "AIzaSYD0123456789abcdefghijklmnopqrstuv", "note": "authorization: Bearer AbCdEfGh123456789"}
    cleaned = task_queue.redact_payload(payload)
    assert cleaned["api_key"] == "[secret redacted]"
    assert "Bearer" not in str(cleaned["note"])
