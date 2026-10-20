"""Serve a disposable Career demo for the CV plan browser journey.

Run from the repository root: python -m scripts.cv_plan_browser_demo --port 8917
No private database, no real CV and no real source is opened. Storage is
temporary, the profile and the offer are synthetic and every outbound
connection is refused apart from the local loopback.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import tempfile

import uvicorn

from career.service import CareerService
from come_ai_web import create_app


def demo_app():
    base = Path(tempfile.mkdtemp(prefix="come-cvplan-synthetic-"))
    os.environ["COME_AI_MEMORY_DIR"] = str(base / "memory_data")
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY"):
        os.environ.pop(key, None)

    career = CareerService(base)
    career.update_profile({
        "display_name": "Compte synthétique",
        "skills": "Advanced Excel modelling, PowerPoint, SQL de base.",
        "experience": "Projet académique : construction d'un modèle financier à trois états sur un trimestre.",
        "education": "Master 1 Finance, analyse financière et valorisation.",
        "languages": "Français natif, English C1.",
        "eligibility": "compatible",
    })
    career.import_job({
        "company": "Fixture Bank",
        "title": "Synthetic M&A Intern",
        "job_family": "À préciser",
        "city": "Paris",
        "country": "France",
        "source_status": "open",
        "language": "en",
        "official_url": "https://careers.example.test/jobs/synthetic-ma-intern",
        "source_id": "fixture-ma-001",
        "requirements": (
            "Advanced Excel modelling is required.\n"
            "Bloomberg Terminal proficiency is required.\n"
            "Fluent English is required.\n"
            "Construction d’un modèle financier à trois états requise."
        ),
        "description_original": (
            "Requirements:\n"
            "Advanced Excel modelling is required.\n"
            "Bloomberg Terminal proficiency is required.\n"
            "Fluent English is required.\n"
            "Construction d’un modèle financier à trois états requise.\n"
            "Benefits:\nFree coffee."
        ),
    })

    app = create_app(base_dir=base, career_override=career)
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_dns = socket.getaddrinfo

    def ensure_local(address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError("Outbound network blocked in synthetic CV-plan browser demo")

    def local_connect(sock, address):
        ensure_local(address)
        return original_connect(sock, address)

    def local_connect_ex(sock, address):
        ensure_local(address)
        return original_connect_ex(sock, address)

    def local_dns(host, *args, **kwargs):
        if host not in {"127.0.0.1", "localhost", "::1", None}:
            raise RuntimeError("External DNS blocked in synthetic CV-plan browser demo")
        return original_dns(host, *args, **kwargs)

    socket.socket.connect = local_connect
    socket.socket.connect_ex = local_connect_ex
    socket.getaddrinfo = local_dns
    print(f"SYNTHETIC DEMO ONLY — temporary storage: {base}", flush=True)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8917)
    args = parser.parse_args()
    uvicorn.run(demo_app(), host="127.0.0.1", port=args.port, access_log=False, log_level="warning")
