"""Garde-fous d'écriture locale : permissions disque et anti-CSRF."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from come_ai_web import create_app


class _NoopAgent:
    def chat(self, message: str, **kwargs: object) -> dict[str, object]:  # pragma: no cover
        return {"answer": "", "provider": "offline", "model": "noop", "route_reason": "test",
                "tool_events": [], "citations": [], "usage": {}, "latency_seconds": 0.0,
                "remote_model_used": False}

    def provider_status(self) -> dict[str, object]:  # pragma: no cover - simple stub
        return {"configured": False}


def test_user_directories_are_owner_only(tmp_path: Path) -> None:
    app = create_app(tmp_path, agent_override=_NoopAgent())
    assert app.title
    for name in ("data", "output", "logs"):
        path = tmp_path / name
        path.mkdir(exist_ok=True)  # cas du dossier déjà présent mais trop ouvert
        mode = os.stat(path).st_mode & 0o777
        path.chmod(0o755)  # simule un dossier créé avant le durcissement
    # L'app relance la création via un second démarrage complet :
    second = create_app(tmp_path, agent_override=_NoopAgent())
    assert second.title
    for name in ("data", "output", "logs"):
        mode = os.stat(tmp_path / name).st_mode & 0o777
        assert mode == 0o700, f"{name} doit être propriétaire-seul, trouvé {oct(mode)}"


def test_foreign_origin_writes_are_rejected_before_reaching_endpoints(tmp_path: Path) -> None:
    app = create_app(tmp_path, agent_override=_NoopAgent())
    client = TestClient(app)
    foreign = {"Origin": "https://page-volante.invalid"}
    # Un formulaire simple (multipart/json sans preflight) ne doit pas atteindre
    # un endpoint de mutation depuis un site tiers.
    assert client.post("/api/files/upload", data={"x": "1"}, headers=foreign).status_code == 403
    assert client.post("/api/v5/memory/projects", json={"name": "piège"}, headers=foreign).status_code == 403
    # Un navigateur moderne marque sans-Origin cross-site via Sec-Fetch-Site.
    assert client.post("/api/v5/memory/projects", json={"name": "piège"},
                       headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    # GET n'est pas concerné.
    assert client.get("/api/health", headers=foreign).status_code == 200


def test_same_origin_sec_fetch_site_is_admitted(tmp_path: Path) -> None:
    app = create_app(tmp_path, agent_override=_NoopAgent())
    client = TestClient(app)
    # Navigateur moderne same-origin sans Origin explicite (GET-like POST).
    assert client.post("/api/v5/memory/projects", json={"name": "mémoire fidédèle"},
                       headers={"Sec-Fetch-Site": "same-origin"}).status_code not in (403, 400)


def test_same_origin_and_local_clients_are_not_blocked(tmp_path: Path) -> None:
    app = create_app(tmp_path, agent_override=_NoopAgent())
    client = TestClient(app)
    same = {"Origin": "http://testserver"}
    assert client.post("/api/v5/memory/projects", json={"name": "mémoire"}, headers=same).status_code not in (403, 400)
    # curl/TestClient sans Origin restent admis (les navigateurs envoient toujours Origin en POST).
    assert client.post("/api/v5/memory/projects", json={"name": "mémoire 2"}).status_code not in (403, 400)
