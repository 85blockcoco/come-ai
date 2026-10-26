#!/usr/bin/env python3
"""SPEC-049 — vérification navigateur du centre de notifications.

Le script démarre l’application locale FastAPI sur un répertoire temporaire,
mocke les réponses ``/api/*`` avec des données synthétiques, puis pilote Chrome
headless via CDP (Playwright) pour vérifier l’interface réelle de ``/app``.

Aucune base réelle n’est lue, aucune requête externe n’est autorisée et aucune
relance n’est envoyée. Usage :

    .venv/bin/python scripts/notif_center_cdp_check.py
"""

from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import uvicorn
from playwright.sync_api import Page, Route, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from come_ai_web import create_app  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

API: dict[str, Any] = {
    "/api/career/dashboard": {
        "jobs_total": 2,
        "jobs_open": 2,
        "shortlisted": 1,
        "to_review": 0,
        "interviews_total": 0,
        "interviews_active": 0,
        "drafts_total": 1,
        "action_plan": [{"title": "Relancer Banque Synthétique", "detail": "", "target_view": "tracking"}],
    },
    "/api/career/application-pipeline": {
        "pipeline": [
            {
                "job_id": "job-deadline",
                "company": "Cabinet Synthétique",
                "title": "Analyste junior",
                "tracking_stage": "ready_to_apply",
                "official_url": "https://careers.example.test/jobs/deadline",
                "deadline_date": "2026-10-28",
                "deadline_status": "urgent",
                "days_until_deadline": 2,
                "next_action_code": "final_review",
                "next_action_detail": "Vérifie les faits, les PDF et la langue.",
            },
            {
                "job_id": "job-receipt",
                "company": "École Synthétique",
                "title": "Assistant administratif",
                "tracking_stage": "receipt_unknown",
                "official_url": "",
                "deadline_date": "",
                "deadline_status": "unknown",
                "next_action_code": "confirm_receipt",
                "next_action_detail": "Contrôle le portail officiel avant toute relance.",
            },
        ],
        "summary": {},
    },
    "/api/career/apply-tracker": {
        "items": [
            {
                "job_id": "job-due",
                "application_id": "app-due",
                "title": "Stagiaire M&A",
                "company": "Banque Synthétique",
                "official_url": "https://careers.example.test/jobs/due",
                "follow_up_due_date": "2026-10-20",
                "days_waiting": 16,
                "status": "due",
                "overdue": True,
                "followup_draft": "Bonjour, je me permets de revenir vers vous…",
            }
        ],
        "totals": {"due": 1, "overdue": 1},
    },
    "/api/career/jobs": {"jobs": []},
    "/api/v5/overview": {
        "memory": {"source_count": 1, "chunk_count": 2, "project_count": 1, "engine": "local"},
        "task_queue": {"active_count": 0},
    },
    "/api/app/missions": {"available": True, "counts": {"done": 1}, "missions": [], "workers": 0, "load": 0.0},
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(app: Any, port: int) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server
        time.sleep(0.05)
    raise RuntimeError("serveur local non démarré")


def mock_api(route: Route) -> None:
    path = urlparse(route.request.url).path
    if path in API:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(API[path]))
    else:
        route.fulfill(status=404, content_type="application/json", body='{"detail":"synthetic 404"}')


def check(results: list[dict[str, Any]], name: str, ok: bool, detail: str = "") -> None:
    results.append({"check": name, "ok": bool(ok), "detail": detail})
    print(("PASS" if ok else "FAIL"), name, detail)


def run(base: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    external: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=CHROME, headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page: Page = context.new_page()
        page.route("**/api/**", mock_api)
        page.on(
            "request",
            lambda request: external.append(request.url) if not request.url.startswith(base) else None,
        )

        page.goto(f"{base}/app", wait_until="domcontentloaded")
        page.wait_for_selector("#notifBadge:not([hidden])", timeout=15_000)
        check(results, "badge non lues", page.inner_text("#notifBadge") == "3", page.inner_text("#notifBadge"))
        check(results, "panneau fermé au départ", page.locator("#notifPanel").is_hidden())

        page.click("#notifBtn")
        page.wait_for_selector("#notifPanel:not([hidden])")
        check(results, "ouverture accessible", page.get_attribute("#notifBtn", "aria-expanded") == "true")
        check(results, "trois notifications", page.locator(".notif-row").count() == 3,
              str(page.locator(".notif-row").count()))

        page.click('[data-notif-filter="followups"]')
        check(results, "filtre relances", page.locator(".notif-row").count() == 1,
              str(page.locator(".notif-row").count()))
        page.click('[data-notif-filter="all"]')

        page.click(".notif-row .notif-action")
        check(results, "relance copiée annoncée", "copiée" in page.inner_text("#notifStatus"))

        page.click("#notifReadAll")
        check(results, "tout lu masque le badge", page.locator("#notifBadge").is_hidden())

        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector("#notifPanel", state="attached")
        time.sleep(0.4)
        check(results, "lecture persistée après reload", page.locator("#notifBadge").is_hidden())

        page.click("#notifBtn")
        page.wait_for_selector("#notifPanel:not([hidden])")
        page.locator(".notif-row .notif-dismiss").first.click()
        check(results, "masquage immédiat", page.locator(".notif-row").count() == 2,
              str(page.locator(".notif-row").count()))

        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector("#notifPanel", state="attached")
        time.sleep(0.4)
        page.click("#notifBtn")
        page.wait_for_selector("#notifPanel:not([hidden])")
        check(results, "masquage persisté après reload", page.locator(".notif-row").count() == 2,
              str(page.locator(".notif-row").count()))

        page.keyboard.press("Escape")
        check(results, "Échap ferme le panneau", page.locator("#notifPanel").is_hidden())
        check(results, "aucune requête externe", not external, ", ".join(external[:3]))

        context.close()
        browser.close()
    return results


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="nage-notif-") as temp:
        port = free_port()
        server = serve(create_app(Path(temp)), port)
        base = f"http://127.0.0.1:{port}"
        try:
            results = run(base)
        finally:
            server.should_exit = True
    passed = sum(item["ok"] for item in results)
    print(json.dumps({"passed": passed, "total": len(results), "results": results}, ensure_ascii=False, indent=2))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
