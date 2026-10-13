"""Explicit real Côme/Qwen smoke in an OS network-blocked process."""
from __future__ import annotations

import json
import socket
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from come_ai_web import create_app
from devkit.patching import _atomic_write


def main():
    # A real public TCP attempt must fail. Run this entrypoint under the macOS
    # loopback-only sandbox, not with a mocked transport or DNS-dependent test.
    blocked = False
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=2):
            pass
    except OSError:
        blocked = True
    if not blocked:
        raise SystemExit("Refus : réseau externe non bloqué. Relancer sous sandbox macOS.")
    root = Path(__file__).resolve().parents[1]
    report = {"external_tcp_blocked": True, "synthetic_only": True, "cases": [], "cloud_generations": 0}
    with tempfile.TemporaryDirectory(prefix="come-offline-smoke-") as temporary:
        project = Path(temporary)
        app = create_app(project)
        runtime = app.state.runtime
        try:
            with TestClient(app) as client:
                document = runtime.config.data_dir / "cours-fictif.txt"
                document.write_text("Notes fictives : le dossier Nova doit être rendu mardi. Il contient exactement 8 pages. Le responsable est Lina.", encoding="utf-8")
                runtime.workspace.refresh()
                records = runtime.workspace.list_files()
                file_id = next(row["file_id"] for row in records if row["name"] == document.name)
                runtime.memory.import_file(document, title="Cours fictif Nova")
                cases = [
                    ("conversation", {"message": "Bonjour, présente-toi en français en une phrase."}),
                    ("document", {"message": "Résume ces notes en une phrase en gardant le jour, le nombre de pages et le responsable.", "selected_file_ids": [file_id]}),
                    ("memory", {"message": 'Retrouve dans ma mémoire "Nova" et indique les faits enregistrés.'}),
                    ("calculation", {"message": "Calcule 6*9-12"}),
                ]
                for name, payload in cases:
                    response = client.post("/api/v5/chat", json={"mode": "offline", **payload})
                    if response.status_code != 200:
                        raise ValueError("Offline chat smoke failed: " + name)
                    data = response.json()
                    assert data["remote_model_used"] is False
                    assert data["provider"] in {"ollama", "local_tools"}
                    if name == "calculation":
                        assert "42" in data["answer"] and data["usage"]["generation_requests"] == 0
                    if name == "document":
                        assert data["citations"] and data["tool_events"]
                    if name == "memory":
                        assert any(event["tool"] == "search_memory" for event in data["tool_events"])
                        assert data["provider"] == "local_tools"
                        assert data["usage"]["generation_requests"] == 0
                        assert "Nova" in data["answer"] and "8 pages" in data["answer"]
                    report["cases"].append({"name": name, "answer": data["answer"], "provider": data["provider"], "model": data["model"],
                                            "seconds": data["latency_seconds"], "usage": data["usage"], "tool_events": [e["tool"] for e in data["tool_events"]]})
                    print(json.dumps({"name": name, "provider": data["provider"], "seconds": data["latency_seconds"], "passed": True}), flush=True)
                forbidden = client.post("/api/v5/chat", json={"message": "Bonjour", "mode": "offline", "provider": "gemini"})
                assert forbidden.status_code != 200
                report["cloud_override_refused"] = True
        finally:
            runtime.task_runner.stop(wait=True, timeout=2)
    report["passed"] = True
    _atomic_write(root / ".devkit" / "intelligence" / "offline-smoke.json", json.dumps(report, ensure_ascii=False, indent=2).encode(), 0o600)


if __name__ == "__main__":
    main()
