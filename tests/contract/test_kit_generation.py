from dataclasses import replace
from pathlib import Path

from docx import Document

from career.application_studio import generate_application_kit
from career.cv_fit import CoverageResult, FitGap
from career.cv_quality import DocumentInput, analyze_cv
from career.cv_variants import MA_VARIANT, MARKETS_VARIANT


def _profile() -> dict:
    return {
        "display_name": "Côme Delavenne",
        "contact_email": "come@example.test",
        "experience": "SMBC — Automated 500+ files with Python, reducing processing time by 80%.",
        "education": "EDHEC — MSc Financial Engineering — Graduation December 2026",
        "skills": "Python, Excel, financial modeling, valuation",
        "languages": "French native; English C1",
        "eligibility": "EU citizen",
    }


def _coverage(variant=MA_VARIANT) -> CoverageResult:
    gap = FitGap(
        requirement="deal rationale",
        requirement_type="mandatory",
        current_state="missing",
        adapted_state="Add a cited deal-rationale example.",
        provenance=None,
        variant_specific=True,
    )
    return CoverageResult(4, 3, 7, 4, 75.0, 57.1, [gap], variant, "Exact family match")


def _job() -> dict:
    return {
        "id": "jpm-2027-iba",
        "company": "JPMorgan",
        "title": "Investment Banking Analyst Intern",
        "requirements": "Financial modeling, valuation and deal rationale.",
        "official_url": "https://careers.example.test/jpm-2027-iba",
        "updated_at": "2026-10-21T14:30:00Z",
        "qualification": {
            "provenance": {
                "start_date": {
                    "source": "offer.requirements",
                    "quote": "Starting January 2027",
                    "offset": 0,
                }
            }
        },
    }


def _analysis():
    return analyze_cv(
        DocumentInput(
            text="EXPERIENCE\nSMBC — Automated 500+ files with Python.",
            filename="current-cv.txt",
            filetype="txt",
        )
    )


def test_ma_kit_contains_variant_structure_placeholders_and_provenance(tmp_path: Path) -> None:
    result = generate_application_kit(_job(), _profile(), MA_VARIANT, _coverage(), _analysis(), tmp_path)

    assert result.cv_path.exists()
    assert result.cover_letter_path.exists()
    assert result.prep_sheet_path.exists()
    cv = Document(result.cv_path)
    headings = [paragraph.text for paragraph in cv.paragraphs if paragraph.style.name.startswith("Heading")]
    assert headings[:3] == [
        "Professional Summary",
        "Professional Experience",
        "Transaction Experience",
    ]
    cv_text = "\n".join(paragraph.text for paragraph in cv.paragraphs)
    assert "modelling" in cv_text
    assert "Available for a 6-month international internship" in cv_text
    assert "[AJOUTER PREUVE CHIFFRÉE]" in cv_text
    assert result.variant is MA_VARIANT
    assert result.provenance_map
    assert all(citation.get("source") for citation in result.provenance_map.values())
    prep = result.prep_sheet_path.read_text(encoding="utf-8")
    assert "## 1. Offer Facts to Verify" in prep
    assert "## 2. Profile Evidence Gaps" in prep
    assert "## 3. Variant-Specific Interview Talking Points" in prep
    assert "## 4. Before You Submit Checklist" in prep
    assert "## 5. Provenance Index" in prep
    assert "Aucun envoi automatique" in prep


def test_markets_kit_uses_us_locale_and_quant_sections(tmp_path: Path) -> None:
    coverage = replace(_coverage(), recommended_variant=MARKETS_VARIANT)
    result = generate_application_kit(_job(), _profile(), MARKETS_VARIANT, coverage, _analysis(), tmp_path)

    cv = Document(result.cv_path)
    text = "\n".join(paragraph.text for paragraph in cv.paragraphs)
    headings = [paragraph.text for paragraph in cv.paragraphs if paragraph.style.name.startswith("Heading")]
    assert "modeling" in text
    assert headings[:3] == [
        "Professional Summary",
        "Technical Skills",
        "Quantitative Projects",
    ]


def test_kit_generation_is_byte_for_byte_idempotent(tmp_path: Path) -> None:
    first = generate_application_kit(_job(), _profile(), MA_VARIANT, _coverage(), _analysis(), tmp_path / "one")
    second = generate_application_kit(_job(), _profile(), MA_VARIANT, _coverage(), _analysis(), tmp_path / "two")

    assert first.cv_path.read_bytes() == second.cv_path.read_bytes()
    assert first.cover_letter_path.read_bytes() == second.cover_letter_path.read_bytes()
    assert first.prep_sheet_path.read_bytes() == second.prep_sheet_path.read_bytes()
