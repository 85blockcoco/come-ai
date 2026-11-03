from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

from academics.vc.storage import VcStore


def test_end_to_end_serve_radar_plan_grade_report(tmp_path: Path) -> None:
    from academics.vc.server import serve

    home = tmp_path / "vc"
    store = VcStore(home)
    server = serve(store, port=8821)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)
    try:
        # radar
        with urllib.request.urlopen("http://127.0.0.1:8821/api/radar") as r:
            assert r.status == 200
            radar = json.loads(r.read())
            assert "topics" in radar
        # plan
        with urllib.request.urlopen("http://127.0.0.1:8821/api/plan?minutes=15") as r:
            plan = json.loads(r.read())
            assert plan["total_minutes"] <= 15
        # grade a drill
        req = urllib.request.Request(
            "http://127.0.0.1:8821/api/drills/grade",
            data=json.dumps({"drill_id": "VC04-D001", "answer": "10 M€"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
            assert result["accepted"] is True
        # export
        with urllib.request.urlopen("http://127.0.0.1:8821/api/export") as r:
            export = json.loads(r.read())
            assert "drills" in export
            assert len(export["drills"]) == 1
        # health
        with urllib.request.urlopen("http://127.0.0.1:8821/api/health") as r:
            assert json.loads(r.read())["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_concurrent_requests_are_stable(tmp_path: Path) -> None:
    import concurrent.futures

    from academics.vc.server import serve

    home = tmp_path / "vc"
    store = VcStore(home)
    server = serve(store, port=0)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(1.0)
    try:
        def fetch(path):
            for _ in range(3):
                try:
                    with urllib.request.urlopen("http://127.0.0.1:" + str(port) + path, timeout=5) as r:
                        return r.status, json.loads(r.read())
                except Exception:
                    time.sleep(0.2)
            raise RuntimeError("fetch failed")

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(fetch, "/api/radar") for _ in range(10)] + [pool.submit(fetch, "/api/plan?minutes=5") for _ in range(10)]
            for f in concurrent.futures.as_completed(futures):
                status, payload = f.result()
                assert status == 200
                assert isinstance(payload, dict)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)