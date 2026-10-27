#!/usr/bin/env python3
"""Vérification CDP (Chrome headless) de l'accessibilité et du responsive `/app`.

Le script démarre une instance FastAPI isolée (répertoire temporaire, API
simulée), lance Google Chrome en mode headless avec le protocole DevTools,
puis exécute une batterie de contrôles réels : repères, focus, clavier,
dialogues, régions live, cibles tactiles et absence de débordement
horizontal à 1440 px, 720 px (zoom 200 %), 320 px et 390 px (mobile).

Aucune donnée utilisateur n'est lue : toutes les réponses API sont des
constantes locales définies ci-dessous.

Usage :
    python scripts/check_desktop_a11y_cdp.py
    python scripts/check_desktop_a11y_cdp.py --url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MOCK_DELAY = 0.6  # laisse le temps d'observer `aria-busy` au chargement

MOCK_RESPONSES: dict[str, dict] = {
    "/api/career/dashboard": {
        "jobs_total": 12,
        "jobs_open": 8,
        "to_review": 3,
        "shortlisted": 2,
        "interviews_active": 1,
        "interviews_total": 2,
        "drafts_total": 4,
        "action_plan": [
            {
                "title": "Relancer ACME",
                "detail": "Relance due aujourd'hui.",
                "target_view": "applications",
            }
        ],
    },
    "/api/career/application-pipeline": {
        "pipeline": [
            {
                "job_id": "job-1",
                "title": "Data Analyst",
                "company": "ACME",
                "stage": "applied",
                "stage_label": "Envoyé",
                "progress_percent": 40,
                "next_action_label": "Relancer sous 3 jours",
                "deadline_date": "2026-11-01",
                "official_url": "https://example.invalid/offre/1",
            }
        ]
    },
    "/api/career/apply-tracker": {
        "totals": {"due": 1, "overdue": 0, "sent_without_response": 1},
        "items": [
            {
                "title": "Data Analyst",
                "company": "ACME",
                "sent_at": "2026-10-20",
                "follow_up_due": "2026-10-27",
                "progress_percent": 100,
                "channel": "site",
                "follow_up_draft": "Bonjour, je me permets de revenir vers vous…",
            }
        ],
        "honesty": "Sont listées les candidatures déclarées envoyées.",
    },
    "/api/career/jobs": {
        "jobs": [
            {
                "title": "Data Analyst",
                "company": "ACME",
                "city": "Lyon",
                "job_family": "data",
                "official_url": "https://example.invalid/offre/1",
                "source_status": "open",
                "calendar_status": "open",
            },
            {
                "title": "Analyste BI",
                "company": "Globex",
                "city": "Paris",
                "job_family": "data",
                "official_url": "https://example.invalid/offre/2",
                "source_status": "open",
                "calendar_status": "to_verify",
            },
        ]
    },
    "/api/v5/overview": {
        "memory": {
            "source_count": 4,
            "chunk_count": 42,
            "project_count": 2,
            "engine": "sqlite-fts",
        },
        "task_queue": {"active_count": 1},
    },
    "/api/app/missions": {
        "available": True,
        "counts": {"done": 2, "pending": 1},
        "missions": [
            {"id": "M-1", "title": "Mission de test", "blocked_by": [], "status": "pending"}
        ],
        "workers": 0,
        "load": 0.1,
    },
    "/api/career/ats-guide/job-1": {
        "title": "Data Analyst",
        "platform": "Greenhouse",
        "estimated_minutes": 6,
        "needs_account": True,
        "steps": [
            {"title": "Créer un compte", "fields": ["e-mail", "mot de passe"], "tips": "Utilise une adresse dédiée."},
            {"title": "Téléverser le CV", "fields": ["cv"], "tips": "PDF, 2 Mo maximum."},
        ],
        "apply_url": "https://example.invalid/apply",
    },
    "/api/career/apply-kit/job-1": {
        "readiness": 80,
        "block_reasons": [],
        "checklist": [
            {"id": "cv", "label": "CV relu", "done": True, "note": ""},
            {"id": "lettre", "label": "Lettre adaptée", "done": False, "note": "mentionner l'offre"},
        ],
        "export_urls": {"pdf": "/exports/kit.pdf", "docx": "/exports/kit.docx"},
        "deep_link": "https://example.invalid/apply",
    },
    "/api/career/quick-answers/job-1": {
        "answers": [
            {"label": "Prétentions salariales", "value": "45 000 € brut", "confidence": "exact"},
            {"label": "Disponibilité", "value": "Sous un mois", "confidence": "derived"},
        ]
    },
}

ACC_NAME_JS = """(node) => {
  if (!node) return "";
  const text = (n) => (n ? (n.textContent || "").trim() : "");
  const aria = node.getAttribute("aria-label");
  if (aria && aria.trim()) return aria.trim();
  const labelledby = node.getAttribute("aria-labelledby");
  if (labelledby) {
    const joined = labelledby.split(/\\s+/).map((id) => text(document.getElementById(id))).join(" ").trim();
    if (joined) return joined;
  }
  if (node.labels && node.labels.length) {
    const joined = [...node.labels].map((label) => text(label)).join(" ").trim();
    if (joined) return joined;
  }
  const own = text(node);
  if (own) return own;
  const title = node.getAttribute("title");
  return title ? title.trim() : "";
}"""

MISSING_NAMES_JS = """() => {
  const selector = 'button, input, select, textarea, a[href], [role="button"], [role="link"]';
  const missing = [];
  for (const node of document.querySelectorAll(selector)) {
    if (node.type === "hidden") continue;
    if (node.getClientRects().length === 0) continue;
    if (!window.__accName(node)) {
      missing.push(`${node.tagName.toLowerCase()}${node.id ? "#" + node.id : ""}.${node.className || ""}`);
    }
  }
  return missing;
}"""

NO_OVERFLOW_JS = """() => {
  const doc = document.documentElement;
  const scroll = document.querySelector("#scroll");
  return {
    viewport: window.innerWidth,
    document: { scrollWidth: doc.scrollWidth, clientWidth: doc.clientWidth },
    scroll: scroll ? { scrollWidth: scroll.scrollWidth, clientWidth: scroll.clientWidth } : null,
  };
}"""


class Recorder:
    """Collecte les résultats et imprime une ligne par contrôle."""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.items.append({"name": name, "ok": bool(ok), "detail": str(detail)})
        status = "PASS" if ok else "FAIL"
        suffix = f" — {detail}" if detail and not ok else ""
        print(f"{status}  {len(self.items):02d}. {name}{suffix}", flush=True)

    @property
    def passed(self) -> int:
        return sum(1 for item in self.items if item["ok"])


class Step:
    """Contexte qui capture l'échec d'un contrôle sans interrompre la suite."""

    def __init__(self, recorder: Recorder, name: str) -> None:
        self.recorder = recorder
        self.name = name
        self.detail = ""

    def __enter__(self) -> "Step":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.recorder.add(self.name, True, self.detail)
            return False
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            return False
        message = str(exc) or exc_type.__name__
        self.recorder.add(self.name, False, message)
        return True


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.4)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return False


def build_app():
    """Construit l'application FastAPI avec des API simulées en mémoire."""
    from fastapi.responses import JSONResponse

    from come_ai_web import create_app

    base_dir = Path(tempfile.mkdtemp(prefix="nage-a11y-cdp-"))
    app = create_app(base_dir)

    @app.middleware("http")
    async def mock_api(request, call_next):
        path = request.url.path
        if path in MOCK_RESPONSES:
            if MOCK_DELAY:
                await asyncio.sleep(MOCK_DELAY)
            return JSONResponse(MOCK_RESPONSES[path])
        if path.startswith("/api/career/send-confirmation/"):
            return JSONResponse({"ok": True})
        return await call_next(request)

    return app, base_dir


def find_chrome() -> str:
    candidates = [
        os.environ.get("CHROME_PATH"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("Google Chrome introuvable (définir CHROME_PATH).")


def start_chrome(chrome: str, cdp_port: int, profile: Path) -> subprocess.Popen:
    command = [
        chrome,
        "--headless=new",
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-background-networking",
        "--disable-extensions",
        "--window-size=1440,900",
        "about:blank",
    ]
    return subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def wait_for_cdp(cdp_port: int, timeout: float = 25.0) -> str:
    endpoint = f"http://127.0.0.1:{cdp_port}/json/version"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(endpoint, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
                browser = payload.get("Browser", "Chrome")
                if payload.get("webSocketDebuggerUrl"):
                    return browser
        except Exception:  # noqa: BLE001 - le port n'écoute pas encore
            time.sleep(0.2)
    raise RuntimeError("Le protocole DevTools de Chrome ne répond pas.")


def new_context(browser, **kwargs):
    context = browser.new_context(**kwargs)
    context.add_init_script(f"window.__accName = {ACC_NAME_JS};")
    context.add_init_script(
        """
        window.__nativeDialogs = 0;
        for (const name of ["alert", "prompt", "confirm"]) {
          window[name] = () => {
            window.__nativeDialogs += 1;
            return name === "confirm" ? true : (name === "prompt" ? null : undefined);
          };
        }
        """
    )
    return context


def goto_app(page, url: str) -> None:
    page.goto(f"{url}/app", wait_until="domcontentloaded", timeout=30_000)


def wait_loaded(page) -> None:
    page.wait_for_function(
        "() => !document.querySelector('#main')?.hasAttribute('aria-busy')",
        timeout=25_000,
    )
    page.wait_for_selector("#statusDot.online", timeout=25_000)


def open_view(page, view: str) -> None:
    page.locator(f'.nav-item[data-view="{view}"]').click()
    page.wait_for_function(
        f"() => !document.querySelector('#view-{view}').hidden",
        timeout=10_000,
    )


def open_dialog(page, selector: str):
    trigger = page.locator(selector).first
    trigger.scroll_into_view_if_needed()
    trigger.click()
    page.wait_for_selector('[role="dialog"]', timeout=10_000)
    return trigger


def overflow_state(page) -> dict:
    return page.evaluate(NO_OVERFLOW_JS)


def assert_no_overflow(state: dict, label: str) -> None:
    doc = state["document"]
    assert doc["scrollWidth"] <= doc["clientWidth"] + 1, (
        f"{label}: document {doc['scrollWidth']}px > {doc['clientWidth']}px"
    )
    scroll = state.get("scroll")
    if scroll:
        assert scroll["scrollWidth"] <= scroll["clientWidth"] + 1, (
            f"{label}: zone scroll {scroll['scrollWidth']}px > {scroll['clientWidth']}px"
        )


def run_desktop(browser, url: str, recorder: Recorder) -> None:
    context = new_context(browser, viewport={"width": 1440, "height": 900})
    context.grant_permissions(["clipboard-read", "clipboard-write"])
    page = context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    goto_app(page, url)

    with Step(recorder, "langue française et titre NAGE") as step:
        lang = page.get_attribute("html", "lang")
        title = page.title()
        step.detail = f"lang={lang} · {title}"
        assert lang == "fr", f"lang={lang!r}"
        assert "NAGE" in title, f"titre={title!r}"

    with Step(recorder, "métadonnées viewport, theme-color et color-scheme") as step:
        metas = page.evaluate(
            """() => Object.fromEntries(
                [...document.querySelectorAll('meta[name]')].map((m) => [m.name, m.content])
            )"""
        )
        step.detail = ", ".join(sorted(metas))
        assert "width=device-width" in metas.get("viewport", "")
        assert metas.get("theme-color"), "theme-color absent"
        assert metas.get("color-scheme"), "color-scheme absent"

    with Step(recorder, "repères main, nav et aside nommés") as step:
        data = page.evaluate(
            """() => ({
                main: !!document.querySelector('main#main'),
                nav: document.querySelector('nav')?.getAttribute('aria-label') || "",
                aside: document.querySelector('aside')?.getAttribute('aria-label') || "",
            })"""
        )
        step.detail = f"nav={data['nav']!r} · aside={data['aside']!r}"
        assert data["main"], "main#main absent"
        assert data["nav"], "nav sans nom accessible"
        assert data["aside"], "aside sans nom accessible"

    with Step(recorder, "les vues sont des régions étiquetées, une seule visible") as step:
        data = page.evaluate(
            """() => {
                const views = [...document.querySelectorAll('.view')];
                return {
                    count: views.length,
                    roles: views.map((view) => view.getAttribute('role')),
                    labels: views.map((view) => view.getAttribute('aria-label')),
                    visible: views.filter((view) => !view.hidden).map((view) => view.id),
                };
            }"""
        )
        step.detail = f"{data['count']} vues · visibles={data['visible']}"
        assert data["count"] == 7, data["count"]
        assert all(role == "region" for role in data["roles"]), data["roles"]
        assert all(data["labels"]), data["labels"]
        assert data["visible"] == ["view-today"], data["visible"]

    with Step(recorder, "aria-busy pendant le chargement puis retiré") as step:
        busy = page.get_attribute("#main", "aria-busy")
        step.detail = f"aria-busy={busy!r} au premier rendu"
        assert busy == "true", "aria-busy doit être présent pendant le chargement"
        wait_loaded(page)
        assert page.get_attribute("#main", "aria-busy") is None, "aria-busy non retiré"
        status = page.inner_text("#statusText")
        assert "local" in status.lower(), status

    with Step(recorder, "régions live et statut présents") as step:
        data = page.evaluate(
            """() => {
                const region = (id) => {
                    const node = document.getElementById(id);
                    return node ? {
                        role: node.getAttribute('role'),
                        live: node.getAttribute('aria-live'),
                    } : null;
                };
                return { announce: region('srAnnounce'), toast: region('toast'), status: region('statusDot') };
            }"""
        )
        step.detail = json.dumps(data, ensure_ascii=False)
        assert data["announce"] == {"role": "status", "live": "polite"}, data["announce"]
        assert data["toast"] == {"role": "status", "live": "polite"}, data["toast"]
        assert data["status"] == {"role": "status", "live": "polite"}, data["status"]

    with Step(recorder, "aucun débordement horizontal à 1440 px") as step:
        page.wait_for_selector(".card.hero", timeout=15_000)
        state = overflow_state(page)
        step.detail = json.dumps(state["document"])
        assert_no_overflow(state, "1440px")

    with Step(recorder, "lien d'évitement visible au premier Tab") as step:
        page.evaluate("() => document.activeElement?.blur()")
        page.keyboard.press("Tab")
        page.wait_for_timeout(300)  # laisse la transition du lien se terminer
        data = page.evaluate(
            """() => {
                const node = document.activeElement;
                const rect = node.getBoundingClientRect();
                const style = getComputedStyle(node);
                return {
                    cls: node.className,
                    text: (node.textContent || '').trim(),
                    top: rect.top,
                    transform: style.transform,
                };
            }"""
        )
        step.detail = f"focus={data['text']!r} top={data['top']:.0f}"
        assert "skip-link" in data["cls"], f"premier focus={data['cls']!r}"
        assert data["top"] >= 0, f"lien hors écran (top={data['top']})"

    with Step(recorder, "le lien d'évitement déplace le focus sur main") as step:
        page.keyboard.press("Enter")
        active = page.evaluate("() => ({ id: document.activeElement.id, tag: document.activeElement.tagName })")
        step.detail = json.dumps(active)
        assert active["id"] == "main", active

    with Step(recorder, "anneau de focus visible sur la navigation") as step:
        page.evaluate("() => document.activeElement?.blur()")
        for _ in range(12):
            page.keyboard.press("Tab")
            if page.evaluate("() => document.activeElement?.classList.contains('nav-item')"):
                break
        data = page.evaluate(
            """() => {
                const style = getComputedStyle(document.activeElement);
                return {
                    cls: document.activeElement.className,
                    outlineStyle: style.outlineStyle,
                    outlineWidth: style.outlineWidth,
                    outlineColor: style.outlineColor,
                };
            }"""
        )
        step.detail = json.dumps(data)
        assert "nav-item" in data["cls"], data["cls"]
        assert data["outlineStyle"] != "none", data
        assert float(data["outlineWidth"].replace("px", "")) >= 2, data

    with Step(recorder, "navigation : 7 boutons nommés, un seul aria-current") as step:
        data = page.evaluate(
            """() => {
                const buttons = [...document.querySelectorAll('.nav-item')];
                return {
                    count: buttons.length,
                    names: buttons.map((b) => window.__accName(b)),
                    current: buttons.filter((b) => b.getAttribute('aria-current') === 'page').map((b) => b.dataset.view),
                    types: buttons.map((b) => b.getAttribute('type')),
                };
            }"""
        )
        step.detail = f"{data['count']} boutons · current={data['current']}"
        assert data["count"] == 7, data["count"]
        assert all(name for name in data["names"]), data["names"]
        assert data["current"] == ["today"], data["current"]
        assert all(kind == "button" for kind in data["types"]), data["types"]

    with Step(recorder, "les flèches déplacent le focus dans la navigation") as step:
        page.locator('.nav-item[data-view="today"]').focus()
        page.keyboard.press("ArrowDown")
        view = page.evaluate("() => document.activeElement.dataset.view")
        page.keyboard.press("ArrowUp")
        back = page.evaluate("() => document.activeElement.dataset.view")
        step.detail = f"bas={view} · haut={back}"
        assert view == "applications", view
        assert back == "today", back

    with Step(recorder, "changement de vue : titre, région et annonce live") as step:
        open_view(page, "applications")
        page.wait_for_function(
            "() => document.querySelector('#viewTitle').textContent.trim().toLowerCase() === 'candidatures'",
            timeout=10_000,
        )
        page.wait_for_function(
            "() => document.querySelector('#srAnnounce').textContent.includes('Candidatures')",
            timeout=10_000,
        )
        data = page.evaluate(
            """() => ({
                title: document.querySelector('#viewTitle').textContent.trim(),
                visible: [...document.querySelectorAll('.view')].filter((v) => !v.hidden).map((v) => v.id),
                announce: document.querySelector('#srAnnounce').textContent,
            })"""
        )
        step.detail = f"titre={data['title']!r} · vue={data['visible']}"
        assert data["title"].lower() == "candidatures", data["title"]
        assert data["visible"] == ["view-applications"], data["visible"]

    with Step(recorder, "le titre du document suit la vue") as step:
        open_view(page, "missions")
        page.wait_for_function("() => document.title.startsWith('Missions')", timeout=10_000)
        step.detail = page.title()
        assert page.title().startswith("Missions"), page.title()

    with Step(recorder, "hashchange ouvre la vue demandée") as step:
        page.evaluate("() => { location.hash = '#memory'; }")
        page.wait_for_function("() => !document.querySelector('#view-memory').hidden", timeout=10_000)
        data = page.evaluate(
            """() => ({
                hash: location.hash,
                title: document.querySelector('#viewTitle').textContent.trim(),
                visible: [...document.querySelectorAll('.view')].filter((v) => !v.hidden).map((v) => v.id),
            })"""
        )
        step.detail = json.dumps(data, ensure_ascii=False)
        assert data["hash"] == "#memory", data
        assert data["title"].lower() == "mémoire", data
        assert data["visible"] == ["view-memory"], data

    with Step(recorder, "aucune image sans alternative, SVG décoratifs masqués") as step:
        data = page.evaluate(
            """() => {
                const images = [...document.querySelectorAll('img')].filter((img) => !img.hasAttribute('alt'));
                const svgs = [...document.querySelectorAll('svg')].filter((svg) => {
                    if (svg.closest('[aria-hidden="true"]')) return false;
                    const host = svg.closest('button, a, [role="img"], [role="button"]');
                    return !host || !window.__accName(host);
                });
                return {
                    images: images.length,
                    svgs: svgs.map((svg) => svg.outerHTML.slice(0, 80)),
                };
            }"""
        )
        step.detail = json.dumps(data, ensure_ascii=False)
        assert data["images"] == 0, f"{data['images']} image(s) sans alt"
        assert not data["svgs"], data["svgs"]

    with Step(recorder, "champ de recherche étiqueté, filtre annoncé") as step:
        open_view(page, "offers")
        page.wait_for_selector("#searchBox:not([hidden])", timeout=10_000)
        name = page.evaluate("() => window.__accName(document.querySelector('#searchInput'))")
        page.fill("#searchInput", "zzz")
        page.wait_for_selector("#view-offers .empty", timeout=10_000)
        page.wait_for_function(
            "() => document.querySelector('#srAnnounce').textContent.includes('0 offre')",
            timeout=10_000,
        )
        announce = page.inner_text("#srAnnounce")
        step.detail = f"nom={name!r} · annonce={announce!r}"
        assert "Filtrer les offres" in name, name
        assert "0 offre" in announce, announce
        page.fill("#searchInput", "")

    with Step(recorder, "tous les contrôles visibles ont un nom accessible") as step:
        open_view(page, "applications")
        page.wait_for_selector("#view-applications .pipeline-item", timeout=10_000)
        missing = page.evaluate(MISSING_NAMES_JS)
        step.detail = json.dumps(missing, ensure_ascii=False)
        assert not missing, missing

    with Step(recorder, "progressbar avec valeurs accessibles") as step:
        data = page.evaluate(
            """() => {
                const bar = document.querySelector('#view-applications [role="progressbar"]');
                if (!bar) return null;
                return {
                    now: bar.getAttribute('aria-valuenow'),
                    min: bar.getAttribute('aria-valuemin'),
                    max: bar.getAttribute('aria-valuemax'),
                    label: bar.getAttribute('aria-label'),
                };
            }"""
        )
        step.detail = json.dumps(data, ensure_ascii=False)
        assert data, "aucune progressbar"
        assert data["now"] == "40", data
        assert data["min"] == "0" and data["max"] == "100", data
        assert data["label"], data

    with Step(recorder, "dialogue ATS : rôle, nom, focus initial") as step:
        open_dialog(page, '#view-applications button[title*="Guide de candidature"]')
        data = page.evaluate(
            """() => {
                const box = document.querySelector('.modal-box');
                const labelledby = box.getAttribute('aria-labelledby');
                return {
                    role: box.getAttribute('role'),
                    modal: box.getAttribute('aria-modal'),
                    labelledby,
                    heading: labelledby ? document.getElementById(labelledby)?.textContent.trim() : "",
                    focusInside: !!document.activeElement.closest('.modal-box'),
                };
            }"""
        )
        step.detail = json.dumps(data, ensure_ascii=False)
        assert data["role"] == "dialog", data
        assert data["modal"] == "true", data
        assert data["heading"] and "Guide ATS" in data["heading"], data
        assert data["focusInside"], "le focus doit entrer dans le dialogue"

    with Step(recorder, "piège de focus : Tab reste dans le dialogue") as step:
        escapes = []
        for _ in range(10):
            page.keyboard.press("Tab")
            inside = page.evaluate("() => !!document.activeElement.closest('.modal-box')")
            if not inside:
                escapes.append(page.evaluate("() => document.activeElement.outerHTML.slice(0, 60)"))
        step.detail = f"{len(escapes)} sortie(s) de focus"
        assert not escapes, escapes

    with Step(recorder, "Échap ferme le dialogue et rend le focus") as step:
        page.keyboard.press("Escape")
        page.wait_for_selector('[role="dialog"]', state="detached", timeout=10_000)
        restored = page.evaluate(
            """() => ({
                insideDialog: !!document.activeElement.closest('.modal-box'),
                title: document.activeElement.getAttribute('title') || '',
                text: (document.activeElement.textContent || '').trim(),
            })"""
        )
        step.detail = json.dumps(restored, ensure_ascii=False)
        assert not restored["insideDialog"], restored
        assert "Guide de candidature" in restored["title"], restored
        assert restored["text"].lower().startswith("guide"), restored

    with Step(recorder, "notification non bloquante pour la copie") as step:
        open_dialog(page, '#view-applications button[title*="Réponses types"]')
        page.locator('.modal-box button[aria-label^="Copier la réponse"]').first.click()
        page.wait_for_function("() => !document.querySelector('#toast').hidden", timeout=10_000)
        data = page.evaluate(
            """() => {
                const toast = document.querySelector('#toast');
                return {
                    role: toast.getAttribute('role'),
                    live: toast.getAttribute('aria-live'),
                    text: toast.textContent.trim(),
                };
            }"""
        )
        step.detail = json.dumps(data, ensure_ascii=False)
        assert data["role"] == "status" and data["live"] == "polite", data
        assert data["text"], "notification vide"
        page.keyboard.press("Escape")

    with Step(recorder, "assistant : journal role=log et saisie étiquetée") as step:
        open_view(page, "assistant")
        page.wait_for_selector("#chatLog", timeout=10_000)
        data = page.evaluate(
            """() => {
                const log = document.querySelector('#chatLog');
                const input = document.querySelector('#chatInput');
                const modes = [...document.querySelectorAll('.modes button')];
                return {
                    role: log.getAttribute('role'),
                    live: log.getAttribute('aria-live'),
                    inputName: window.__accName(input),
                    describedby: input.getAttribute('aria-describedby'),
                    pressed: modes.map((b) => b.getAttribute('aria-pressed')),
                };
            }"""
        )
        step.detail = json.dumps(data, ensure_ascii=False)
        assert data["role"] == "log", data
        assert data["live"] == "polite", data
        assert data["inputName"], data
        assert data["describedby"], data
        assert data["pressed"] == ["true", "false"], data

    with Step(recorder, "aucune erreur console ni exception JavaScript") as step:
        page.wait_for_timeout(400)
        step.detail = json.dumps({"console": console_errors[:3], "page": page_errors[:3]}, ensure_ascii=False)
        assert not console_errors, console_errors[:3]
        assert not page_errors, page_errors[:3]

    with Step(recorder, "aucun dialogue natif bloquant") as step:
        count = page.evaluate("() => window.__nativeDialogs")
        step.detail = f"{count} appel(s)"
        assert count == 0, count

    context.close()


def run_reduced_motion(browser, url: str, recorder: Recorder) -> None:
    context = new_context(browser, viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    page = context.new_page()
    goto_app(page, url)
    wait_loaded(page)
    with Step(recorder, "prefers-reduced-motion : animations neutralisées") as step:
        data = page.evaluate(
            """() => {
                const seconds = (value) => Math.max(
                    0,
                    ...String(value || '0s').split(',').map((part) => {
                        const text = part.trim();
                        if (text.endsWith('ms')) return parseFloat(text) / 1000;
                        return parseFloat(text) || 0;
                    }),
                );
                const nodes = ['.nav-item', '.card', '.skip-link']
                    .map((sel) => document.querySelector(sel))
                    .filter(Boolean);
                const durations = nodes.flatMap((node) => {
                    const style = getComputedStyle(node);
                    return [style.transitionDuration, style.animationDuration];
                }).map(seconds);
                return {
                    max: Math.max(0, ...durations),
                    scanlines: getComputedStyle(document.body, '::after').display,
                };
            }"""
        )
        step.detail = f"durée max={data['max']}s · scanlines={data['scanlines']}"
        assert data["max"] <= 0.001, data
        assert data["scanlines"] == "none", data
    context.close()


def run_reflow(browser, url: str, recorder: Recorder) -> None:
    context = new_context(browser, viewport={"width": 720, "height": 450})
    page = context.new_page()
    goto_app(page, url)
    wait_loaded(page)
    with Step(recorder, "reflow 200 % (720 px) et 400 % (320 px) sans débordement") as step:
        page.wait_for_selector(".card.hero", timeout=15_000)
        results = {}
        for width, height in ((720, 450), (320, 640)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(250)
            state = overflow_state(page)
            results[width] = state
            assert_no_overflow(state, f"{width}px")
            open_view(page, "applications")
            page.wait_for_selector("#view-applications .pipeline-item", timeout=10_000)
            state = overflow_state(page)
            results[f"{width}-applications"] = state
            assert_no_overflow(state, f"{width}px candidatures")
            open_view(page, "offers")
            page.wait_for_selector("#view-offers .offer-row", timeout=10_000)
            state = overflow_state(page)
            results[f"{width}-offers"] = state
            assert_no_overflow(state, f"{width}px offres")
            open_view(page, "today")
        step.detail = json.dumps({key: value["document"] for key, value in results.items()}, ensure_ascii=False)
    context.close()


def run_mobile(browser, url: str, recorder: Recorder) -> None:
    context = new_context(
        browser,
        viewport={"width": 390, "height": 844},
        is_mobile=True,
        has_touch=True,
        device_scale_factor=3,
    )
    page = context.new_page()
    goto_app(page, url)
    wait_loaded(page)
    page.wait_for_selector(".card.hero", timeout=15_000)

    with Step(recorder, "mobile 390 px : aucun débordement horizontal") as step:
        state = overflow_state(page)
        step.detail = json.dumps(state["document"])
        assert state["viewport"] == 390, state["viewport"]
        assert_no_overflow(state, "390px aujourd'hui")
        open_view(page, "applications")
        page.wait_for_selector("#view-applications .pipeline-item", timeout=10_000)
        assert_no_overflow(overflow_state(page), "390px candidatures")
        open_view(page, "offers")
        page.wait_for_selector("#view-offers .offer-row", timeout=10_000)
        assert_no_overflow(overflow_state(page), "390px offres")
        open_view(page, "today")

    with Step(recorder, "mobile : navigation horizontale, cibles ≥ 44 px") as step:
        data = page.evaluate(
            """() => {
                const nav = document.querySelector('.nav');
                const style = getComputedStyle(nav);
                const items = [...document.querySelectorAll('.nav-item')];
                const primary = [...document.querySelectorAll('.nav-item, .ghost-btn, .send-btn, .chip')];
                const tooSmall = primary
                    .filter((node) => node.getClientRects().length > 0)
                    .map((node) => ({ node, rect: node.getBoundingClientRect() }))
                    .filter(({ rect }) => rect.width < 24 || rect.height < 24)
                    .map(({ node, rect }) => `${node.className}:${Math.round(rect.width)}x${Math.round(rect.height)}`);
                return {
                    overflowX: style.overflowX,
                    itemHeights: items.map((item) => Math.round(item.getBoundingClientRect().height)),
                    tooSmall,
                };
            }"""
        )
        step.detail = json.dumps(data, ensure_ascii=False)
        assert data["overflowX"] in ("auto", "scroll"), data
        assert len(data["itemHeights"]) == 7, data
        assert min(data["itemHeights"]) >= 44, data
        assert not data["tooSmall"], data["tooSmall"]

    with Step(recorder, "mobile : dialogue ATS dans le viewport, fermeture overlay, recherche") as step:
        open_view(page, "applications")
        page.wait_for_selector('#view-applications button[title*="Guide de candidature"]', timeout=10_000)
        open_dialog(page, '#view-applications button[title*="Guide de candidature"]')
        data = page.evaluate(
            """() => {
                const box = document.querySelector('.modal-box');
                const overlay = document.querySelector('.modal-overlay');
                const rect = box.getBoundingClientRect();
                return {
                    viewport: { width: window.innerWidth, height: window.innerHeight },
                    box: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom },
                    boxOverflow: box.scrollWidth - box.clientWidth,
                    overlayOverflow: overlay.scrollWidth - overlay.clientWidth,
                    focusInside: !!document.activeElement.closest('.modal-box'),
                };
            }"""
        )
        step.detail = json.dumps(data, ensure_ascii=False)
        assert data["box"]["left"] >= -1 and data["box"]["right"] <= data["viewport"]["width"] + 1, data["box"]
        assert data["box"]["top"] >= -1 and data["box"]["bottom"] <= data["viewport"]["height"] + 1, data["box"]
        assert data["boxOverflow"] <= 1, data["boxOverflow"]
        assert data["overlayOverflow"] <= 1, data["overlayOverflow"]
        assert data["focusInside"], "focus hors dialogue"
        page.mouse.click(2, 2)
        page.wait_for_selector('[role="dialog"]', state="detached", timeout=10_000)
        open_view(page, "offers")
        page.wait_for_selector("#searchBox:not([hidden])", timeout=10_000)
        name = page.evaluate("() => window.__accName(document.querySelector('#searchInput'))")
        page.fill("#searchInput", "ACME")
        page.wait_for_function(
            "() => document.querySelectorAll('#view-offers .offer-row').length === 1",
            timeout=10_000,
        )
        step.detail = f"nom={name!r} · 1 résultat"
        assert "Filtrer les offres" in name, name

    context.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Contrôles CDP accessibilité / responsive de /app")
    parser.add_argument("--url", help="serveur déjà lancé (sinon une instance isolée démarre)")
    parser.add_argument(
        "--report",
        default=str(ROOT / "reports" / "spec-052-a11y-cdp.json"),
        help="chemin du rapport JSON",
    )
    args = parser.parse_args()

    recorder = Recorder()
    server = None
    server_thread = None
    chrome_process = None
    temp_dirs: list[Path] = []
    browser_label = ""
    url = args.url.rstrip("/") if args.url else ""

    try:
        from playwright.sync_api import sync_playwright

        if not url:
            import uvicorn

            app, base_dir = build_app()
            temp_dirs.append(base_dir)
            port = _free_port()
            config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False)
            server = uvicorn.Server(config)
            server_thread = threading.Thread(target=server.run, daemon=True)
            server_thread.start()
            if not _wait_for_port(port, timeout=30.0):
                raise RuntimeError("Le serveur local n'a pas démarré.")
            url = f"http://127.0.0.1:{port}"

        chrome = find_chrome()
        cdp_port = _free_port()
        profile = Path(tempfile.mkdtemp(prefix="nage-a11y-chrome-"))
        temp_dirs.append(profile)
        chrome_process = start_chrome(chrome, cdp_port, profile)
        browser_label = wait_for_cdp(cdp_port)

        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
            run_desktop(browser, url, recorder)
            run_reduced_motion(browser, url, recorder)
            run_reflow(browser, url, recorder)
            run_mobile(browser, url, recorder)
            browser.close()
    finally:
        if chrome_process and chrome_process.poll() is None:
            chrome_process.terminate()
            try:
                chrome_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome_process.kill()
        if server is not None:
            server.should_exit = True
        if server_thread is not None:
            server_thread.join(timeout=10)
        for directory in temp_dirs:
            shutil.rmtree(directory, ignore_errors=True)

    total = len(recorder.items)
    passed = recorder.passed
    failed = total - passed
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "url": url,
        "browser": browser_label,
        "checks": recorder.items,
        "total": total,
        "passed": passed,
        "failed": failed,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("")
    print(f"RÉSULTAT : {passed}/{total} contrôles réussis — rapport {report_path}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
