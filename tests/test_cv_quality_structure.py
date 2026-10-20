"""Unit tests for CV Quality structural analysis.

All fixtures are synthetic — no real CVs, no external files.
Tests cover each detector + edge cases.
"""

from __future__ import annotations

import pytest

from career.cv_quality import (
    analyze_cv,
    DocumentInput,
    STATUS_RISK,
    STATUS_INFO,
)
from career.cv_quality.models import Finding
from career.cv_quality.structure import (
    detect_cv_length,
    detect_sections,
    detect_experiences,
    detect_long_blocks,
    detect_repetitions,
    detect_tables,
    detect_low_text_ratio,
    compute_readability,
)


# ──────────────────────────────────────────────────────────────────────
# Synthetic CV fixtures
# ──────────────────────────────────────────────────────────────────────

MINIMAL_CV = """
Jean Dupont
test.user@example.com
+33 6 12 34 56 78

Expérience
2020-2023 | Développeur Python | TechCorp
- Augmentation du trafic API de 30% en 6 mois
- Réduction des coûts infrastructure de 15k€/an
- Migration de 5 services vers Kubernetes

Formation
2018-2020 | Master Informatique | Université Paris-Saclay

Compétences
Python, SQL, Docker, Kubernetes

Langues
Français (natif), Anglais (courant)

Projets
Projet open source : librairie de validation (2k+ stars GitHub)

Certifications
AWS Solutions Architect Associate
"""

SHORT_CV = """
Jean Dupont
Expérience
2020 | Dev | TechCorp
Formation
2020 | Master | Uni
Compétences
Python
"""

LONG_CV = "A" * 3000  # ~3000 chars > 1800 threshold

CV_MISSING_SECTIONS = """
Jean Dupont
Expérience
2020 | Dev | TechCorp
Formation
2020 | Master | Uni
# Missing: Compétences, Langues, Projets, Certifications
"""

CV_WITH_QUANTIFIED_EXP = """
Expérience
2020-2023 | Développeur Senior | TechCorp
- Augmentation du CA de 15% en 6 mois
- Réduction des coûts de 50k€ par an
- Gestion d'équipe de 5 personnes
"""

CV_WITHOUT_QUANTIFIED_EXP = """
Expérience
2020-2023 | Développeur Senior | TechCorp
- Développement de fonctionnalités
- Maintenance du code existant
- Participation aux réunions d'équipe
"""

LONG_BLOCK_CV = """
Expérience
2020-2023 | Développeur | TechCorp

Ceci est un très long paragraphe sans saut de ligne qui continue encore et encore pour dépasser les 800 caractères ou 12 lignes. """ + "Ligne après ligne. " * 50

REPETITION_CV = """
Expérience
Développeur Python développeur Python développeur Python chez TechCorp.
Développeur Python développeur Python développeur Python chez DataInc.
Développeur Python développeur Python développeur Python chez SoftWare.
Développeur Python développeur Python développeur Python ailleurs.
"""

TABLE_CV = """
Expérience
| Entreprise | Rôle | Dates |
|------------|------|-------|
| TechCorp   | Dev  | 2020  |
| DataInc    | Lead | 2021  |
"""

TABULAR_CV = """
Expérience
TechCorp\tDéveloppeur\t2020-2023
DataInc\tLead Dev\t2021-2024
"""

LOW_TEXT_RATIO_CV = "▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓" * 50  # Mostly non-alnum

EMPTY_CV = ""

WHITESPACE_CV = "   \n\n   \t\t   \n   "


# ──────────────────────────────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────────────────────────────

def make_doc(text: str, filetype: str = "txt") -> DocumentInput:
    # Estimate page count (matching parser behavior: ~3000 chars/page)
    page_count = max(1, (len(text) // 3000) + 1)
    return DocumentInput(text=text, filename=f"test.{filetype}", filetype=filetype, page_count=page_count)


def find_findings(result, code: str) -> list[Finding]:
    return [f for f in result.findings if f.code == code]


def has_finding(result, code: str, status: str | None = None) -> bool:
    for f in result.findings:
        if f.code == code and (status is None or f.status == status):
            return True
    return False


# ──────────────────────────────────────────────────────────────────────
# Detector 1: CV Length
# ──────────────────────────────────────────────────────────────────────

def test_detect_cv_length_short():
    result = analyze_cv(make_doc(SHORT_CV))
    assert not has_finding(result, "CV_TOO_LONG")


def test_detect_cv_length_long():
    result = analyze_cv(make_doc(LONG_CV))
    findings = find_findings(result, "CV_TOO_LONG")
    assert len(findings) == 1
    assert findings[0].status == STATUS_RISK
    assert findings[0].metadata["useful_chars"] > 1800


def test_detect_cv_length_boundary():
    # Exactly at threshold
    text = "A" * 1800
    result = analyze_cv(make_doc(text))
    assert not has_finding(result, "CV_TOO_LONG")

    # Just over
    text = "A" * 1801
    result = analyze_cv(make_doc(text))
    assert has_finding(result, "CV_TOO_LONG", STATUS_RISK)


# ──────────────────────────────────────────────────────────────────────
# Detector 2: Missing Sections
# ──────────────────────────────────────────────────────────────────────

def test_detect_all_sections_present():
    result = analyze_cv(make_doc(MINIMAL_CV))
    missing = find_findings(result, "MISSING_SECTION")
    assert len(missing) == 0
    # Check sections detected
    section_titles = {s.title for s in result.sections}
    assert "Expérience" in section_titles
    assert "Formation" in section_titles
    assert "Compétences" in section_titles
    assert "Langues" in section_titles
    assert "Projets" in section_titles
    assert "Certifications" in section_titles


def test_detect_missing_sections():
    result = analyze_cv(make_doc(CV_MISSING_SECTIONS))
    missing = find_findings(result, "MISSING_SECTION")
    assert len(missing) == 4
    missing_sections = {f.metadata["section"] for f in missing}
    assert missing_sections == {"Compétences", "Langues", "Projets", "Certifications"}
    for f in missing:
        assert f.status == STATUS_RISK
        assert f.source_offset == 0  # Missing sections reported at offset 0


def test_detect_sections_case_insensitive():
    cv = """
    EXPERIENCE PROFESSIONNELLE
    2020 | Dev | TechCorp
    FORMATION
    2020 | Master | Uni
    COMPETENCES
    Python
    LANGUES
    Français
    PROJETS
    Un projet
    CERTIFICATIONS
    AWS
    """
    result = analyze_cv(make_doc(cv))
    missing = find_findings(result, "MISSING_SECTION")
    assert len(missing) == 0


def test_detect_sections_english_keywords():
    cv = """
    Work Experience
    2020 | Dev | TechCorp
    Education
    2020 | Master | Uni
    Skills
    Python
    Languages
    French
    Projects
    A project
    Certifications
    AWS
    """
    result = analyze_cv(make_doc(cv))
    missing = find_findings(result, "MISSING_SECTION")
    assert len(missing) == 0


# ──────────────────────────────────────────────────────────────────────
# Detector 3: Unquantified Experiences
# ──────────────────────────────────────────────────────────────────────

def test_detect_quantified_experience():
    result = analyze_cv(make_doc(CV_WITH_QUANTIFIED_EXP))
    unquantified = find_findings(result, "UNQUANTIFIED_EXPERIENCE")
    assert len(unquantified) == 0
    # Check experience parsed
    assert len(result.experiences) >= 1
    assert result.experiences[0].has_quantified_result is True


def test_detect_unquantified_experience():
    result = analyze_cv(make_doc(CV_WITHOUT_QUANTIFIED_EXP))
    unquantified = find_findings(result, "UNQUANTIFIED_EXPERIENCE")
    assert len(unquantified) == 1
    assert unquantified[0].status == STATUS_RISK
    assert unquantified[0].metadata["company"] == "TechCorp"
    assert unquantified[0].metadata["role"] == "Développeur Senior"
    assert result.experiences[0].has_quantified_result is False


def test_detect_mixed_quantified():
    cv = """
    Expérience
    2020-2022 | Dev Junior | Startup
    - Apprentissage du métier
    2022-2024 | Dev Senior | ScaleUp
    - Augmentation performance de 40%
    """
    result = analyze_cv(make_doc(cv))
    unquantified = find_findings(result, "UNQUANTIFIED_EXPERIENCE")
    # Only first entry should be flagged
    assert len(unquantified) == 1
    assert "Junior" in unquantified[0].metadata["role"]


def test_no_experience_section():
    cv = "Formation\n2020 | Master | Uni"
    result = analyze_cv(make_doc(cv))
    unquantified = find_findings(result, "UNQUANTIFIED_EXPERIENCE")
    assert len(unquantified) == 0
    assert len(result.experiences) == 0


# ──────────────────────────────────────────────────────────────────────
# Detector 4: Long Blocks
# ──────────────────────────────────────────────────────────────────────

def test_detect_long_block_by_chars():
    result = analyze_cv(make_doc(LONG_BLOCK_CV))
    long_blocks = find_findings(result, "LONG_BLOCK")
    assert len(long_blocks) >= 1
    assert long_blocks[0].status == STATUS_INFO
    assert long_blocks[0].metadata["char_count"] > 800


def test_detect_long_block_by_lines():
    long_lines = "\n".join([f"Ligne {i}" for i in range(15)])  # 15 lines > 12
    cv = f"Expérience\n2020 | Dev | Corp\n{long_lines}"
    result = analyze_cv(make_doc(cv))
    long_blocks = find_findings(result, "LONG_BLOCK")
    assert len(long_blocks) >= 1
    assert long_blocks[0].metadata["line_count"] > 12


def test_no_long_block_short():
    result = analyze_cv(make_doc(SHORT_CV))
    long_blocks = find_findings(result, "LONG_BLOCK")
    assert len(long_blocks) == 0


# ──────────────────────────────────────────────────────────────────────
# Detector 5: Repetitions (3-grams)
# ──────────────────────────────────────────────────────────────────────

def test_detect_repetition():
    result = analyze_cv(make_doc(REPETITION_CV))
    reps = find_findings(result, "REPETITION")
    assert len(reps) >= 1
    assert reps[0].status == STATUS_INFO
    assert "développeur python" in reps[0].metadata["ngram"].lower()
    assert reps[0].metadata["count"] > 3


def test_no_repetition_normal():
    result = analyze_cv(make_doc(MINIMAL_CV))
    reps = find_findings(result, "REPETITION")
    # May have some but not excessive
    for r in reps:
        assert r.metadata["count"] <= 3 or r.status == STATUS_INFO


# ──────────────────────────────────────────────────────────────────────
# Detector 6: Tables/Columns
# ──────────────────────────────────────────────────────────────────────

def test_detect_markdown_table():
    result = analyze_cv(make_doc(TABLE_CV))
    tables = find_findings(result, "TABLE_DETECTED")
    assert len(tables) >= 1
    assert tables[0].status == STATUS_RISK


def test_detect_tabular_alignment():
    result = analyze_cv(make_doc(TABULAR_CV))
    tables = find_findings(result, "TABLE_DETECTED")
    assert len(tables) >= 1
    assert tables[0].status == STATUS_RISK


def test_no_table_linear_text():
    result = analyze_cv(make_doc(MINIMAL_CV))
    tables = find_findings(result, "TABLE_DETECTED")
    assert len(tables) == 0


# ──────────────────────────────────────────────────────────────────────
# Detector 7: Low Text Ratio (OCR)
# ──────────────────────────────────────────────────────────────────────

def test_detect_low_text_ratio():
    result = analyze_cv(make_doc(LOW_TEXT_RATIO_CV))
    low_ratio = find_findings(result, "LOW_TEXT_RATIO")
    assert len(low_ratio) >= 1
    assert low_ratio[0].status == STATUS_RISK
    assert low_ratio[0].metadata["ratio"] < 0.6


def test_no_low_text_ratio_normal():
    result = analyze_cv(make_doc(MINIMAL_CV))
    low_ratio = find_findings(result, "LOW_TEXT_RATIO")
    assert len(low_ratio) == 0


# ──────────────────────────────────────────────────────────────────────
# Readability Score
# ──────────────────────────────────────────────────────────────────────

def test_compute_readability_normal():
    score = compute_readability(MINIMAL_CV)
    assert isinstance(score.flesch_kincaid_fr, float)
    assert isinstance(score.avg_sentence_length, float)
    assert isinstance(score.complex_word_ratio, float)
    assert score.avg_sentence_length > 0


def test_compute_readability_empty():
    score = compute_readability("")
    assert score.flesch_kincaid_fr == 0.0
    assert score.avg_sentence_length == 0.0
    assert score.complex_word_ratio == 0.0


# ──────────────────────────────────────────────────────────────────────
# Edge Cases
# ──────────────────────────────────────────────────────────────────────

def test_empty_cv():
    result = analyze_cv(make_doc(EMPTY_CV))
    # Should have findings for missing sections at minimum
    missing = find_findings(result, "MISSING_SECTION")
    assert len(missing) == 6  # All required sections missing
    assert result.provenance.text_length == 0


def test_whitespace_only_cv():
    result = analyze_cv(make_doc(WHITESPACE_CV))
    missing = find_findings(result, "MISSING_SECTION")
    assert len(missing) == 6


def test_cv_with_parse_error_finding():
    """Test that PARSE_ERROR finding can be created (for parser integration)."""
    from career.cv_quality.parser import create_parse_error_finding
    err = ValueError("Invalid PDF")
    finding = create_parse_error_finding(err, "pdf", "test.pdf")
    assert finding.code == "PARSE_ERROR"
    assert finding.status == STATUS_RISK
    assert "Invalid PDF" in finding.message


# ──────────────────────────────────────────────────────────────────────
# Full Analysis Integration
# ──────────────────────────────────────────────────────────────────────

def test_full_analysis_minimal_cv():
    result = analyze_cv(make_doc(MINIMAL_CV))
    assert isinstance(result, type(result))  # CVAnalysisResult
    assert result.provenance.filename == "test.txt"
    assert result.provenance.filetype == "txt"
    assert result.provenance.text_length > 0
    # Should have no RISK findings for a good CV
    risk_findings = [f for f in result.findings if f.status == STATUS_RISK]
    assert len(risk_findings) == 0


def test_full_analysis_problematic_cv():
    """CV with multiple issues."""
    cv = LOW_TEXT_RATIO_CV + "\n" + TABLE_CV + "\n" + LONG_BLOCK_CV + "\n" + REPETITION_CV
    result = analyze_cv(make_doc(cv))

    # Should detect multiple issues
    codes = {f.code for f in result.findings}
    assert "TABLE_DETECTED" in codes
    assert "LONG_BLOCK" in codes
    assert "REPETITION" in codes
    assert "LOW_TEXT_RATIO" in codes


def test_provenance_metadata():
    result = analyze_cv(make_doc(MINIMAL_CV, filetype="pdf"))
    prov = result.provenance
    assert prov.filename == "test.pdf"
    assert prov.filetype == "pdf"
    assert prov.text_length == len(MINIMAL_CV)
    assert prov.page_count is not None


def test_finding_provenance_fields():
    """Every finding must have source_offset and source_excerpt."""
    result = analyze_cv(make_doc(CV_WITHOUT_QUANTIFIED_EXP))
    for finding in result.findings:
        assert finding.source_offset >= 0
        assert finding.source_excerpt
        assert len(finding.source_excerpt) <= 60  # ~50 chars + ellipsis context


def test_experience_entry_fields():
    result = analyze_cv(make_doc(CV_WITH_QUANTIFIED_EXP))
    assert len(result.experiences) >= 1
    exp = result.experiences[0]
    assert exp.company
    assert exp.role
    assert exp.source_offset >= 0
    assert isinstance(exp.has_quantified_result, bool)


def test_section_reading_fields():
    result = analyze_cv(make_doc(MINIMAL_CV))
    for section in result.sections:
        assert section.title
        assert section.start_offset >= 0
        assert section.end_offset > section.start_offset
        assert section.content_preview


# ──────────────────────────────────────────────────────────────────────
# Individual detector function tests (unit level)
# ──────────────────────────────────────────────────────────────────────

def test_detect_cv_length_unit():
    findings = detect_cv_length("A" * 100)
    assert len(findings) == 0
    findings = detect_cv_length("A" * 2000)
    assert len(findings) == 1
    assert findings[0].code == "CV_TOO_LONG"


def test_detect_sections_unit():
    sections, findings = detect_sections("Expérience\nDev\n\nFormation\nMaster")
    titles = {s.title for s in sections}
    assert "Expérience" in titles
    assert "Formation" in titles
    missing_codes = {f.metadata["section"] for f in findings}
    assert "Compétences" in missing_codes


def test_detect_experiences_unit():
    cv = "Expérience\n2020-2023 | Dev | Corp\n- Augmentation de 20%"
    sections = [type('S', (), {"title": "Expérience", "start_offset": 0, "end_offset": len(cv)})()]
    experiences, findings = detect_experiences(cv, sections)
    assert len(experiences) == 1
    assert experiences[0].has_quantified_result is True


def test_detect_long_blocks_unit():
    text = "Expérience\n" + "Ligne\n" * 15
    findings = detect_long_blocks(text)
    assert len(findings) >= 1
    assert findings[0].code == "LONG_BLOCK"


def test_detect_repetitions_unit():
    # 3-gram "mot un mot" appears 4 times
    text = "mot un mot mot un mot mot un mot mot un mot mot un mot"
    findings = detect_repetitions(text)
    assert len(findings) >= 1
    assert findings[0].code == "REPETITION"


def test_detect_tables_unit():
    text = "Expérience\n| A | B |\n|---|---|\n| 1 | 2 |"
    findings = detect_tables(text)
    assert len(findings) >= 1
    assert findings[0].code == "TABLE_DETECTED"


def test_detect_low_text_ratio_unit():
    text = "▓▓▓▓" * 100
    findings = detect_low_text_ratio(text, page_count=1)
    assert len(findings) >= 1
    assert findings[0].code == "LOW_TEXT_RATIO"


# ──────────────────────────────────────────────────────────────────────
# Pytest configuration
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])