"""Serve a disposable Career demo with synthetic offers and blocked outbound network.

Run from the repository root: python -m scripts.criteria_browser_demo --port 8916
No private database or real source is opened. The normal application and HTTP
routes run against temporary storage; the public-feed transport uses fixtures.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import tempfile

import uvicorn

from career.discovery import GreenhouseJobBoardConnector
from career.service import CareerService
from come_ai_web import create_app


def demo_app():
    base = Path(tempfile.mkdtemp(prefix="come-criteria-synthetic-"))
    os.environ["COME_AI_MEMORY_DIR"] = str(base / "memory_data")
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY"):
        os.environ.pop(key, None)
    rows = []
    for identifier, (contract, month) in enumerate([
        ("Internship", "January"), ("Internship", "February"), ("Internship", "March"),
        ("Internship", "April"), ("CDD", "February"), ("CDI", "March"), ("VIE", "January"),
    ], 1):
        description = f"Synthetic finance role. Starts in {month} 2027."
        if contract == "Internship":
            description += " This internship lasts six months."
        description += " Requirements: Bachelor degree or Master 1 degree accepted."
        rows.append({"id": str(identifier), "title": f"Synthetic Finance {contract} {month}",
                     "absolute_url": f"https://careers.example.test/synthetic-{identifier}",
                     "content": description, "location": {"name": "Paris, France"},
                     "metadata": [{"name": "Employment Type", "value": contract}]})

    class FixtureFeed:
        def get_json(self, *_args, **_kwargs):
            return {"jobs": rows}

    source = {"id": "synthetic-fixture", "company": "Synthetic Finance", "provider": "greenhouse",
              "board_token": "synthetic-fixture", "public_url": "https://boards.greenhouse.io/synthetic-fixture",
              "provenance_url": "https://careers.example.test/synthetic", "verified_at": "2026-10-18T00:00:00Z"}
    career = CareerService(base, discovery_connector=GreenhouseJobBoardConnector(FixtureFeed()),
                           curated_sources=(source,))
    app = create_app(base_dir=base, career_override=career)
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_dns = socket.getaddrinfo

    def ensure_local(address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError("Outbound network blocked in synthetic browser demo")

    def local_connect(sock, address):
        ensure_local(address)
        return original_connect(sock, address)

    def local_connect_ex(sock, address):
        ensure_local(address)
        return original_connect_ex(sock, address)

    def local_dns(host, *args, **kwargs):
        if host not in {"127.0.0.1", "localhost", "::1", None}:
            raise RuntimeError("External DNS blocked in synthetic browser demo")
        return original_dns(host, *args, **kwargs)

    socket.socket.connect = local_connect
    socket.socket.connect_ex = local_connect_ex
    socket.getaddrinfo = local_dns
    print(f"SYNTHETIC DEMO ONLY — temporary storage: {base}", flush=True)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8916)
    args = parser.parse_args()
    uvicorn.run(demo_app(), host="127.0.0.1", port=args.port, access_log=False, log_level="warning")
