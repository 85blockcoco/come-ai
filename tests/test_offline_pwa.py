"""SPEC-050 — mode hors-ligne (service worker + cache) — tests ciblés."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from career.service import CareerService
from come_ai_web import create_app

STATIC = Path(__file__).resolve().parents[1] / "desktop_static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_service_worker_precaches_the_app_shell():
    worker = _read("sw.js")
    assert 'addEventListener("install"' in worker
    assert 'addEventListener("activate"' in worker
    assert 'addEventListener("fetch"' in worker
    assert '"/app"' in worker
    assert '"/app.webmanifest"' in worker
    assert '"/app-static/app.css"' in worker
    assert '"/app-static/app.js"' in worker
    assert '"/app-static/offline.html"' in worker
    assert "SKIP_WAITING" in worker


def test_service_worker_uses_targeted_strategies():
    worker = _read("sw.js")
    # Les trois stratégies attendues, sans mise en cache des écritures.
    assert 'request.method !== "GET"' in worker
    assert 'request.mode === "navigate"' in worker
    assert 'url.pathname.startsWith("/api/")' in worker
    assert 'url.pathname.startsWith("/app-static/")' in worker
    assert "X-Nage-Offline" in worker
    assert "caches.delete" in worker
    assert "self.clients.claim()" in worker


def test_manifest_declares_an_installable_app():
    manifest = json.loads(_read("manifest.webmanifest"))
    assert manifest["name"].startswith("NAGE")
    assert manifest["start_url"] == "/app"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#050705"
    icons = {icon["src"] for icon in manifest["icons"]}
    assert "/app-static/icon.png" in icons


def test_app_shell_links_manifest_and_offline_banner():
    html = _read("index.html")
    assert 'rel="manifest" href="/app.webmanifest"' in html
    assert 'id="offlineBanner"' in html
    assert 'id="offlineBannerText"' in html
    assert 'name="theme-color"' in html


def test_app_js_registers_worker_and_tracks_connectivity():
    script = _read("app.js")
    assert 'navigator.serviceWorker.register("/sw.js", { scope: "/" })' in script
    assert 'window.addEventListener("online", syncConnectivity)' in script
    assert 'window.addEventListener("offline", syncConnectivity)' in script
    assert "navigator.onLine" in script
    assert 'response.headers.get("X-Nage-Offline")' in script


def test_offline_fallback_page_respects_the_csp():
    html = _read("offline.html")
    assert "/app-static/app.css" in html
    assert 'href="/app"' in html
    # La CSP du serveur interdit les scripts/styles inline : la page doit rester
    # purement déclarative.
    assert "<script" not in html
    assert "<style" not in html


def test_service_worker_is_served_at_root_scope(tmp_path: Path):
    client = TestClient(create_app(tmp_path, agent_override=object(), career_override=CareerService(tmp_path)))
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert response.headers["service-worker-allowed"] == "/"
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.text == _read("sw.js")


def test_manifest_and_app_routes_are_served(tmp_path: Path):
    client = TestClient(create_app(tmp_path, agent_override=object(), career_override=CareerService(tmp_path)))
    manifest = client.get("/app.webmanifest")
    assert manifest.status_code == 200
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    assert manifest.json()["start_url"] == "/app"

    shell = client.get("/app")
    assert shell.status_code == 200
    assert 'id="offlineBanner"' in shell.text

    cached_assets = client.get("/app-static/app.js")
    assert cached_assets.status_code == 200
    assert "serviceWorker" in cached_assets.text
