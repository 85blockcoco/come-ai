from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path


def test_offline_server_serves_radar_and_plan(tmp_path: Path) -> None:
    from academics.vc.server import serve
    from academics.vc.storage import VcStore

    home = tmp_path / "vc"
    store = VcStore(home)
    server = serve(store, port=8811)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)
    try:
        with urllib.request.urlopen("http://127.0.0.1:8811/api/radar") as response:
            assert response.status == 200
            payload = json.loads(response.read())
            assert "topics" in payload
        with urllib.request.urlopen("http://127.0.0.1:8811/api/plan?minutes=5") as response:
            assert response.status == 200
            plan = json.loads(response.read())
            assert plan["total_minutes"] <= 5
        with urllib.request.urlopen("http://127.0.0.1:8811/") as response:
            assert response.status == 200
            assert b"NAGE VC" in response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)