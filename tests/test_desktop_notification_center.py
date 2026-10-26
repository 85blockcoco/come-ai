"""SPEC-049 — contrat statique du centre de notifications du bureau.

Le comportement est vérifié dans Chrome headless par
``scripts/notif_center_cdp_check.py`` ; ces tests gardent le point d'entrée
``/app`` et les marqueurs d'accessibilité nécessaires au panneau.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from come_ai_web import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_app_page_ships_an_accessible_notification_center(tmp_path) -> None:
    response = TestClient(create_app(tmp_path)).get("/app")

    assert response.status_code == 200
    for marker in (
        'id="notifBtn"',
        'id="notifBadge"',
        'aria-controls="notifPanel"',
        'id="notifPanel"',
        'role="dialog"',
        'id="notifList"',
        'id="notifStatus"',
        'aria-live="polite"',
    ):
        assert marker in response.text


def test_notification_script_derives_from_local_data_only() -> None:
    script = (ROOT / "desktop_static" / "app.js").read_text(encoding="utf-8")

    for marker in (
        "function buildNotifications()",
        "state.tracker?.items",
        "state.pipeline?.pipeline",
        "NOTIF_POST_SUBMISSION",
        "copy_followup",
        "localStorage",
    ):
        assert marker in script
    assert "/api/app/notifications" not in script
