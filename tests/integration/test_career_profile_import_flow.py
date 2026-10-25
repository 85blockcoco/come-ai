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


def _synthetic_two_column_cv_pdf() -> bytes:
    buffer = BytesIO()
    document = canvas.Canvas(buffer, pagesize=(595, 842))
    document.setFont("Helvetica-Bold", 14)
    document.drawString(220, 810, "EXPERIENCE")
    y = 770
    for index in range(4):
        document.setFont("Helvetica", 9)
        document.drawString(30, y, f"Jan 202{index} - Jun 202{index}")
        document.setFont("Helvetica-Bold", 10)
        document.drawString(220, y, f"Analyst {index} | Synthetic Bank {index}")
        document.setFont("Helvetica", 9)
        document.drawString(
            220,
            y - 15,
            f"- Automated {100 + index}+ reports with {20 + index}% improvement",
        )
        y -= 90
    for heading, value in (
        ("EDUCATION", "MSc Finance 2026"),
        ("SKILLS", "Python, Excel, valuation"),
        ("PROJECTS", "Valuation project 500 companies"),
        ("CERTIFICATIONS", "Finance certificate 2025"),
        ("LANGUAGES", "English C1, French B2"),
    ):
        document.setFont("Helvetica-Bold", 11)
        document.drawString(30, y, heading)
        document.setFont("Helvetica", 9)
        document.drawString(220, y, value)
        y -= 35
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
        assert draft["extraction_method"] == "cv_quality_pdf"
        assert "Python" in draft["suggestions"]["values"]["skills"]
        assert "Master Finance" in draft["suggestions"]["values"]["education"]

        # Reading the file creates suggestions only; the user profile stays intact.
        assert client.get("/api/career/profile").json() == original_profile
        assert client.get("/api/files").json()["count"] == 0

        applied = client.post(
            f"/api/career/profile-imports/{draft['id']}/apply",
            json={
                "base_profile_updated_at": draft["base_profile_updated_at"],
                "updates": [{"field": "skills", "mode": "replace", "value": "Excel, Python, valuation"}],
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


def test_markdown_profile_import_remains_supported(tmp_path) -> None:
    markdown = b"""Alex Example

## Education
MSc Finance, Synthetic University

## Skills
Excel, Python, valuation
"""
    with TestClient(create_app(tmp_path)) as client:
        imported = client.post(
            "/api/career/profile-imports",
            data={"source_kind": "cv"},
            files={"document": ("synthetic-profile.md", markdown, "text/markdown")},
        )

    assert imported.status_code == 201
    draft = imported.json()
    assert draft["extraction_method"] == "embedded_text"
    assert draft["suggestions"]["values"]["education"] == "MSc Finance, Synthetic University"
    assert draft["suggestions"]["values"]["skills"] == "Excel, Python, valuation"


def test_profile_import_uses_coordinate_parser_for_canva_layout(tmp_path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        imported = client.post(
            "/api/career/profile-imports",
            data={"source_kind": "cv"},
            files={
                "document": (
                    "synthetic-two-column-cv.pdf",
                    _synthetic_two_column_cv_pdf(),
                    "application/pdf",
                )
            },
        )

    assert imported.status_code == 201
    draft = imported.json()
    assert draft["extraction_method"] == "cv_quality_pdf"
    assert draft["cv_quality"]["detected_experiences"] >= 4
