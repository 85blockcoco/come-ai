"""Le consentement cloud du résumé d'offre couvre exactement le prompt transmis."""

from __future__ import annotations

import hashlib  # noqa: F401  (gardé: vérification directe dans le test de digest)
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from career.service import CareerService
from come_ai_web import create_app
from consent_guard.envelope import payload_digest as canonical_payload_digest


class FakeAgent:
    def chat(self, message: str, **kwargs: Any) -> dict[str, Any]:  # pragma: no cover - unused here
        return {"answer": "", "provider": "offline", "model": "fake", "route_reason": "test",
                "tool_events": [], "citations": [], "usage": {}, "latency_seconds": 0.0,
                "remote_model_used": False}


def _client(tmp_path, **kwargs):
    career = CareerService(tmp_path, **kwargs)
    app = create_app(tmp_path, agent_override=FakeAgent(), career_override=career)
    return TestClient(app), career


def _import_offer(client) -> dict[str, Any]:
    job = client.post(
        "/api/career/jobs/import",
        json={
            "company": "Banque Exemple",
            "title": "Stagiaire M&A",
            "location": "Paris",
            "description_original": "Mission confidentielle : modélisation bancaire et due diligence approfondie.",
            "requirements": "Excel avancé, confidentialité absolue",
            "source": "manual",
        },
    )
    assert job.status_code == 201, job.text
    return job.json()


def _fake_generator(prompts):
    def generate(prompt: str) -> dict[str, Any]:
        prompts.append(prompt)
        return {"text": json.dumps({"summary": "Résumé factuel.", "missions": [], "prerequisites": [], "dates": "", "relevance": "", "official_url": ""}), "provider": "Faux fournisseur"}
    return generate


def test_consent_receipt_digest_covers_the_exact_transmitted_prompt(tmp_path: Path) -> None:
    client, career = _client(tmp_path)
    job = _import_offer(client)
    prompts: list[str] = []
    # Mode IA effectif avec générateur injecté au niveau service.
    result = career.summarize_job(
        job["id"], mode="ai", consent_external=True, ai_generator=_fake_generator(prompts)
    )
    assert result["ai_used"] is True
    assert len(prompts) == 1
    prompt = prompts[0]
    # Le contenu transmis contient bien TOUTE l'offre...
    assert "due diligence approfondie" in prompt
    assert "Excel avancé" in prompt
    # ...et le reçu consommé dans le garde-fou signe exactement ce prompt.
    guard = career.consent_guard
    envelopes = [e for e in guard.store.list_consents() if e.provider == "career"]
    assert envelopes, "un accord unique doit avoir été signé puis consommé"
    consumed = envelopes[-1]
    assert consumed.state == "used"
    assert consumed.consumed_at, "l'accord doit être marqué consommé"
    expected = canonical_payload_digest({"prompt": prompt})
    assert consumed.payload_digest == expected, "l'empreinte signée doit correspondre aux octets transmis"


def test_no_consent_keeps_everything_local(tmp_path: Path) -> None:
    client, career = _client(tmp_path)
    job = _import_offer(client)
    prompts: list[str] = []
    result = career.summarize_job(
        job["id"], mode="ai", consent_external=False, ai_generator=_fake_generator(prompts)
    )
    assert result["ai_used"] is False
    assert result["mode"] == "local"
    assert prompts == [], "aucun contenu transmis sans consentement"


def test_consent_guard_unavailable_fails_closed_sun_sent_content(tmp_path: Path) -> None:
    client, career = _client(tmp_path)
    job = _import_offer(client)
    prompts: list[str] = []
    career.consent_guard = None
    result = career.summarize_job(
        job["id"], mode="ai", consent_external=True, ai_generator=_fake_generator(prompts)
    )
    assert result["ai_used"] is False
    assert result["mode"] == "local"
    assert "Garde-fou" in (result.get("ai_error") or "")
    assert prompts == [], "sans garde-fou, rien ne doit quitter le disque"


@pytest.mark.parametrize("payload", [
    {"mode": "ai", "consent_external": False},
])
def test_summary_route_without_consent_reports_local_mode(tmp_path: Path, payload) -> None:
    client, _career = _client(tmp_path)
    job = _import_offer(client)
    response = client.post(f"/api/career/jobs/{job['id']}/summary", json=payload)
    assert response.status_code == 200
    assert response.json()["mode"] == "local"
    assert response.json()["ai_used"] is False
