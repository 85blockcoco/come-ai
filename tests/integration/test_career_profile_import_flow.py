"""Synthetic CV upload remains private and requires an explicit field review."""

from io import BytesIO

from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from come_ai_web import create_app


def _synthetic_cv_pdf() -> bytes:
    buffer = BytesIO()
    document = canvas.Canvas(buffer)
    lines = (
        "Jane Synthetic",
        "jane.synthetic@example.test",
        "FORMATION",
        "Master Finance - Synthetic University",
        "EXPERIENCE PROFESSIONNELLE",
        "Analyst Intern - Synthetic Bank",
        "Built valuation models for 12 companies",
        "COMPETENCES",
        "Excel, Python, valuation",
        "LANGUES",
        "English C1",
    )
    for index, line in enumerate(lines):
        document.drawString(48, 790 - index * 30, line)
    document.save()
    return buffer.getvalue()


def test_synthetic_cv_upload_previews_privately_and_applies_only_approved_fields(
    tmp_path,
) -> None:
    with TestClient(create_app(tmp_path)) as client:
        original = client.get("/api/career/profile")
        assert original.status_code == 200
        original_profile = original.json()

        imported = client.post(
            "/api/career/profile-imports",
            data={"source_kind": "cv"},
            files={"document": ("synthetic-cv.pdf", _synthetic_cv_pdf(), "application/pdf")},
        )
        assert imported.status_code == 201
        draft = imported.json()
        assert draft["status"] == "pending"
        assert draft["has_local_file"] is True
        assert "Python" in draft["suggestions"]["values"]["skills"]
        assert "Master Finance" in draft["suggestions"]["values"]["education"]

        # Reading the file creates suggestions only; the user profile stays intact.
        assert client.get("/api/career/profile").json() == original_profile
        assert client.get("/api/files").json()["count"] == 0

        applied = client.post(
            f"/api/career/profile-imports/{draft['id']}/apply",
            json={
                "base_profile_updated_at": draft["base_profile_updated_at"],
                "updates": [
                    {"field": "skills", "mode": "replace", "value": "Excel, Python, valuation"}
                ],
            },
        )
        assert applied.status_code == 200
        profile = applied.json()["profile"]
        assert profile["skills"] == "Excel, Python, valuation"
        assert profile["education"] == original_profile["education"]
        assert profile["contact_email"] == original_profile["contact_email"]
        assert applied.json()["profile_import"]["status"] == "applied"

        deleted = client.delete(f"/api/career/profile-imports/{draft['id']}")
        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": True}
