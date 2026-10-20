"""Parcours CVBOOST-09 sur un serveur local réel — données 100 % synthétiques.

Ce script jetable démarre l'application sur un répertoire temporaire vide et
vérifie, par HTTP réel (un navigateur ne peut pas être automatisé ici) :
accueil → offre → suivi → tableau de bord → filtre → checklist → calendrier.
Aucun envoi, aucune donnée personnelle, aucune base Career réelle.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import uvicorn

sys.path.insert(0, "/Users/comedelavenne/AI-Excel-Agent-cvboost-09")

from come_ai_web import create_app  # noqa: E402

temp = Path(tempfile.mkdtemp(prefix="cvboost09-smoke-"))
app = create_app(temp, agent_override=object())
config = uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="error")
server = uvicorn.Server(config)
runner = subprocess.Popen([sys.executable, "-"]) if False else None

import threading  # noqa: E402

thread = threading.Thread(target=server.run, daemon=True)
thread.start()
time.sleep(2.5)

base = "http://127.0.0.1:8765"


def call(path: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, str]:
    request = urllib.request.Request(
        base + path,
        method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"} if payload is not None else {},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


results = []

# 1. Page d'accueil Career avec le nouveau tableau de bord.
status, html = call("/career")
results.append(("GET /career → 200 + radar présent", status == 200 and "applications-radar" in html and 'aria-live="polite"' in html))

# 2. Import d'une offre synthétique.
status, body = call(
    "/api/career/jobs/import",
    method="POST",
    payload={
        "company": "Banque Synthétique du Parcours",
        "title": "Stagiaire Risk",
        "official_url": "https://careers.example.test/jobs/smoke-risk",
        "source_name": "manual",
        "source_id": "",
        "deadline_date": "2026-12-01",
        "source_status": "open",
        "requirements": "Excel modelling.\nEnglish fluency.",
        "description_original": "Stage synthétique du parcours.",
    },
)
results.append(("POST offre synthétique", status == 201))
job = json.loads(body)

# 3. Création du suivi + tableau de bord.
_, body = call("/api/career/applications", method="POST", payload={"job_id": job["id"]})
application = json.loads(body)
status, dashboard_raw = call("/api/career/applications/dashboard")
dashboard = json.loads(dashboard_raw)
results.append((
    "GET dashboard : compteur + note honnête + radar vide (dossier récent)",
    status == 200
    and dashboard["counts_by_stage"]["to_review"] == 1
    and "jamais" in dashboard["honesty"]
    and dashboard["radar"] == []
    and dashboard["entries"][0]["sent_declared"] is False,
))

# 4. Architecture "une ligne SQL ≠ envoi" : l'envoi exige l'approbation.
status, _ = call(f"/api/career/applications/{application['id']}", method="PATCH", payload={"stage": "submitted", "note": ""})
results.append(("PATCH submitted sans approbation → 400", status == 400))

# 5. Filtre par état.
status, filtered = call("/api/career/applications/dashboard?stage=to_review")
results.append(("Filtre stage=to_review → 1 entrée", status == 200 and len(json.loads(filtered)["entries"]) == 1))
status, _ = call("/api/career/applications/dashboard?stage=intrus")
results.append(("Filtre invalide → 400", status == 400))

# 6. Checklist locale : 2/5 puis lecture projetée.
status, _ = call(
    f"/api/career/applications/{application['id']}/checklist",
    method="POST",
    payload={"checked": ["cv_reviewed", "deadline_verified"]},
)
entry = json.loads(call("/api/career/applications/dashboard")[1])["entries"][0]
results.append((
    "Checklist persistée, facteur 40/100, score partiel affiché",
    status == 200
    and entry["checklist"]["checked_keys"] == ["cv_reviewed", "deadline_verified"]
    and entry["prep"]["factors"]["checklist"]["percent"] == 40
    and entry["prep"]["partial"] is True
))

# 7. Calendrier local : l'offre non envoyée crée bien une échéance, sans envoi.
status, ics = call("/api/career/deadlines.ics")
results.append(("Calendrier .ics local avec VEVENT 20261201", status == 200 and "BEGIN:VCALENDAR" in ics and "20261201" in ics))

# 8. La page /career sert bien le JavaScript du suivi enrichi.
status, js = call("/career-static/career.js")
results.append((
    "career.js sert compteur, radar et copie presse-papiers locale",
    status == 200
    and "renderApplicationRadar" in js
    and "navigator.clipboard" in js
    and "createOrShowApplication" in js,
))

print("\n".join(f"{'OK ' if ok else 'FAIL'}  {label}" for label, ok in results))
failed = [label for label, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} vérifications réelles vertes")
server.should_exit = True
thread.join(timeout=5)
if failed:
    sys.exit(1)
