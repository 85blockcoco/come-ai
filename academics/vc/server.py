"""Offline HTTP façade for the VC revision coach.

The server is deliberately minimal and dependency-free: it uses only the
standard library and reuses the deterministic engine.  It exposes a small
JSON API and serves a static page.  No cloud call is ever made.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .cli import _emit  # noqa: F401  (kept for parity)
from .content import load_content
from .dates import today_iso
from .mastery import build_study_plan, mastery_radar
from .storage import VcStore


def _json(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _text(handler: BaseHTTPRequestHandler, body: str, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
    data = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class VcHttpHandler(BaseHTTPRequestHandler):
    store: VcStore
    content = None

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            _text(self, _STATIC_PAGE)
            return
        if path == "/sw.js":
            _text(self, _SERVICE_WORKER, content_type="application/javascript; charset=utf-8")
            return
        if path == "/api/radar":
            day = (query.get("today") or [today_iso()])[0]
            records = mastery_radar(
                self.content,
                self.store.load_reviews(),
                today=day,
                case_attempts=self.store.load_case_attempts(),
                exam_results=self.store.load_exam_history(),
                drill_attempts=self.store.load_drill_attempts(),
                paper_attempts=self.store.load_paper_attempts(),
                progress=self.store.load_progress(),
            )
            _json(self, {"topics": [r.to_dict() for r in records], "generated_at": day})
            return
        if path == "/api/plan":
            minutes = int((query.get("minutes") or ["30"])[0])
            day = (query.get("today") or [today_iso()])[0]
            records = mastery_radar(
                self.content,
                self.store.load_reviews(),
                today=day,
                case_attempts=self.store.load_case_attempts(),
                exam_results=self.store.load_exam_history(),
                drill_attempts=self.store.load_drill_attempts(),
                paper_attempts=self.store.load_paper_attempts(),
                progress=self.store.load_progress(),
            )
            exam_date = (query.get("exam_date") or [self.store.load_settings().get("exam_date")])[0]
            plan = build_study_plan(self.content, records, minutes=minutes, today=day, exam_date=exam_date)
            _json(self, plan.to_dict())
            return
        if path == "/api/health":
            _json(self, {"status": "ok", "offline": True})
            return
        if path == "/api/exam-date":
            _json(self, self.store.load_settings())
            return
        if path == "/api/drills":
            topic = (query.get("topic") or [None])[0]
            limit = int((query.get("limit") or ["50"])[0])
            offset = int((query.get("offset") or ["0"])[0])
            filtered = [d for d in self.content.drills if topic is None or d.topic_id == topic]
            page = filtered[offset:offset + limit]
            _json(self, {"drills": [{"drill_id": d.id, "topic_id": d.topic_id, "prompt": d.prompt} for d in page], "total": len(filtered), "limit": limit, "offset": offset})
            return
        if path == "/api/cases":
            limit = int((query.get("limit") or ["50"])[0])
            offset = int((query.get("offset") or ["0"])[0])
            page = self.content.cases[offset:offset + limit]
            _json(self, {"cases": [{"case_id": c.id, "topic_id": c.topic_id, "title": c.title} for c in page], "total": len(self.content.cases), "limit": limit, "offset": offset})
            return
        if path == "/api/papers":
            from .pastpapers import load_papers

            limit = int((query.get("limit") or ["50"])[0])
            offset = int((query.get("offset") or ["0"])[0])
            papers = load_papers()
            page = papers[offset:offset + limit]
            _json(self, {"papers": [{"year": p.year, "paper_id": p.paper_id, "title": p.title} for p in page], "total": len(papers), "limit": limit, "offset": offset})
            return
        if path == "/api/topics":
            _json(self, {"topics": [{"topic_id": t.id, "title": t.title_en, "exam_weight": t.exam_weight} for t in self.content.topics]})
            return
        if path == "/api/glossary":
            q = (query.get("q") or [""])[0].lower()
            matches = [e for e in self.content.glossary if not q or q in e.term_en.lower() or q in e.term_fr.lower() or q in e.definition.lower()]
            limit = int((query.get("limit") or ["50"])[0])
            offset = int((query.get("offset") or ["0"])[0])
            page = matches[offset:offset + limit]
            _json(self, {"matches": [{"term_en": e.term_en, "term_fr": e.term_fr, "definition": e.definition, "topic_id": e.topic_id} for e in page], "total": len(matches), "limit": limit, "offset": offset})
            return
        if path == "/api/search":
            q = (query.get("q") or [""])[0].lower()
            results = []
            if q:
                for t in self.content.topics:
                    if q in t.title_en.lower() or q in t.title_fr.lower():
                        results.append({"type": "topic", "id": t.id, "title": t.title_en})
                for d in self.content.drills:
                    if q in d.prompt.lower():
                        results.append({"type": "drill", "id": d.id, "title": d.prompt[:80]})
                for c in self.content.cases:
                    if q in c.title.lower() or q in c.context.lower():
                        results.append({"type": "case", "id": c.id, "title": c.title})
                for g in self.content.glossary:
                    if q in g.term_en.lower() or q in g.definition.lower():
                        results.append({"type": "glossary", "id": g.term_en, "title": g.term_en})
            limit = int((query.get("limit") or ["50"])[0])
            offset = int((query.get("offset") or ["0"])[0])
            _json(self, {"results": results[offset:offset + limit], "total": len(results), "limit": limit, "offset": offset})
            return
        if path == "/api/export":
            payload = {
                "settings": self.store.load_settings(),
                "progress": {k: v.to_dict() for k, v in self.store.load_progress().items()},
                "reviews": [e.to_dict() for e in self.store.load_reviews()],
                "drills": [d.to_dict() for d in self.store.load_drill_attempts()],
                "papers": [p.to_dict() for p in self.store.load_paper_attempts()],
                "cases": [c.to_dict() for c in self.store.load_case_attempts()],
            }
            _json(self, payload)
            return
        if path == "/api/papers":
            from .pastpapers import load_papers

            papers = load_papers()
            _json(self, {"papers": [{"year": p.year, "paper_id": p.paper_id, "title": p.title} for p in papers]})
            return
        _json(self, {"error": "not found"}, status=404)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/drills/grade":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                _json(self, {"error": "invalid json"}, status=400)
                return
            drill_id = payload.get("drill_id")
            answer = payload.get("answer")
            try:
                drill = self.content.drill(drill_id)
            except Exception:
                _json(self, {"error": "unknown drill"}, status=404)
                return
            from .dates import new_id, now_iso
            from .drills import grade_drill
            from .models import DrillAttempt

            result = grade_drill(drill, str(answer))
            given = result.get("given")
            given_value = given.get("value") if isinstance(given, dict) else None
            self.store.append_drill_attempt(
                DrillAttempt(
                    attempt_id=new_id("drill"),
                    drill_id=drill.id,
                    topic_id=drill.topic_id,
                    answer=str(answer),
                    accepted=bool(result.get("accepted")),
                    expected=float(result.get("expected", drill.answer)),
                    expected_unit=str(result.get("expected_unit", drill.answer_unit)),
                    given_value=given_value,
                    diagnostic=result.get("diagnostic"),
                    submitted_at=now_iso(),
                    message=str(result.get("message", "")),
                )
            )
            _json(self, result)
            return
        _json(self, {"error": "not found"}, status=404)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        import os

        if os.environ.get("VC_SERVE_LOG") == "1":
            super().log_message(format, *args)


_SERVICE_WORKER = """self.addEventListener('install', (e) => { self.skipWaiting(); });
self.addEventListener('activate', (e) => { self.clients.claim(); });
self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;
  e.respondWith(fetch(e.request).catch(() => new Response('offline', {status: 503})));
});
"""

_STATIC_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NAGE VC — Offline Hub</title>
<style>
body { font-family: system-ui, sans-serif; margin: 2rem; background: #0f172a; color: #e2e8f0; }
h1 { color: #38bdf8; }
.card { background: #1e293b; padding: 1rem; border-radius: 8px; margin: 1rem 0; }
button { background: #38bdf8; color: #0f172a; border: none; padding: 0.5rem 1rem; border-radius: 6px; cursor: pointer; margin: 0.25rem; }
pre { background: #020617; padding: 1rem; border-radius: 6px; overflow: auto; }
</style>
</head>
<body>
<h1>NAGE VC — Offline Revision Hub</h1>
<p>All data stays local. No cloud calls.</p>
<div class="card">
  <h2>Radar</h2>
  <button onclick="loadRadar()">Load radar</button>
  <pre id="radar">—</pre>
</div>
<div class="card">
  <h2>Plan (30 min)</h2>
  <button onclick="loadPlan()">Load plan</button>
  <pre id="plan">—</pre>
</div>
<div class="card">
  <h2>Exam date</h2>
  <button onclick="loadExam()">Load exam date</button>
  <pre id="exam">—</pre>
</div>
<script>
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(()=>{});
async function loadRadar(){ const r=await fetch('/api/radar'); document.getElementById('radar').textContent=JSON.stringify(await r.json(),null,2); }
async function loadPlan(){ const r=await fetch('/api/plan?minutes=30'); document.getElementById('plan').textContent=JSON.stringify(await r.json(),null,2); }
async function loadExam(){ const r=await fetch('/api/exam-date'); document.getElementById('exam').textContent=JSON.stringify(await r.json(),null,2); }
document.addEventListener('keydown', (e) => {
  if (e.key === 'r') loadRadar();
  if (e.key === 'p') loadPlan();
  if (e.key === 'e') loadExam();
  if (e.key === 'h') { const r=fetch('/api/health').then(x=>x.json()).then(d=>alert(JSON.stringify(d))); }
});
</script>
</body>
</html>
"""


def serve(store: VcStore, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    content = load_content()
    handler = type("Handler", (VcHttpHandler,), {"store": store, "content": content})
    server = ThreadingHTTPServer((host, port), handler)
    return server


def run_server(store: VcStore, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = serve(store, host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()