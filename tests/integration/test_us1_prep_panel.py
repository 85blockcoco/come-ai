from pathlib import Path

from career.service import CareerService


def test_job_prep_contains_variant_coverage_and_provenance(tmp_path: Path) -> None:
    service = CareerService(tmp_path, curated_sources=())
    job = service.import_job(
        {
            "company": "Synthetic Bank",
            "title": "M&A Intern",
            "official_url": "https://careers.example.test/ma-intern",
            "job_family": "M&A / Investment Banking",
            "requirements": "Financial modeling and valuation required.",
            "source_status": "open",
        }
    )
    service.update_profile(
        {
            "experience": "Valued two companies using DCF at SMBC.",
            "skills": "Excel and financial modeling",
        }
    )

    prep = service.get_job_prep(job["id"])

    assert prep["recommended_variant"] == "m_a"
    assert prep["recommended_variant_label"] == "M&A / Investment Banking"
    assert prep["variant_rationale"]
    assert set(prep["variant_coverage"]) == {
        "m_a",
        "markets",
        "corporate_finance",
    }
    assert set(prep["coverage"]) == {
        "mandatory_total",
        "mandatory_covered",
        "preferred_total",
        "preferred_covered",
        "mandatory_pct",
        "preferred_pct",
    }
    assert prep["gaps"]
    assert all(gap["adapted_state"] for gap in prep["gaps"])
    assert all(gap["provenance"] or gap["current_state"] == "missing" for gap in prep["gaps"])


def test_frontend_renders_variant_coverage_diff_and_selector() -> None:
    js = (Path(__file__).resolve().parents[2] / "career_static" / "career.js").read_text(encoding="utf-8")

    assert "Variante CV recommandée" in js
    assert "Couverture obligatoire" in js
    assert "CV actuel → CV adapté" in js
    assert "variant-specific" in js
    assert "recommended_variant" in js
    assert "variant_rationale" in js
    assert "variantCoverage" in js
