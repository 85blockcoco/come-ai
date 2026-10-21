"""Tests for the local ATS risk analysis (Mission 04).

Every fixture is synthetic: the PDFs are generated on the fly with reportlab,
the DOCX files with python-docx. No real CV, no personal data, no network.
"""

from __future__ import annotations

import io
import socket
import time

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from career.cv_quality import (
    ATSCheckResult,
    ATSFinding,
    DocumentInput,
    run_ats_check,
    run_ats_check_bytes,
    run_ats_check_file,
)
from career.cv_quality.ats import (
    RISK_INTERPRETATIONS,
    calculate_risk_label,
    calculate_risk_score,
    describe_risk,
)
from career.cv_quality.parser import extract_text_from_bytes

PAGE_WIDTH, PAGE_HEIGHT = A4

CLEAN_SECTIONS = ("Expérience", "Formation", "Compétences")


# ──────────────────────────────────────────────────────────────────────
# Helpers — synthetic document builders
# ──────────────────────────────────────────────────────────────────────

def _pdf(draw_pages: list) -> bytes:
    """Build a PDF where each element of `draw_pages` draws one page."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    for index, draw in enumerate(draw_pages):
        if index:
            pdf.showPage()
        draw(pdf)
    pdf.save()
    return buffer.getvalue()


def _draw_lines(pdf, lines: list[tuple[str, float]], x: float = 50.0, size: float = 11.0) -> None:
    """Draw `(text, y)` pairs, top to bottom, all at the same x."""
    for text, y in lines:
        pdf.setFont("Helvetica", size)
        pdf.drawString(x, y, text)


def _docx_bytes(build) -> bytes:
    """Build a DOCX through the given callback and return its bytes."""
    import docx

    document = docx.Document()
    build(document)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _set_columns(document, number: int) -> None:
    """Declare a number of text columns in the DOCX section properties."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    sect_pr = document.sections[0]._sectPr
    cols = sect_pr.find(qn("w:cols"))
    if cols is None:
        cols = OxmlElement("w:cols")
        sect_pr.append(cols)
    cols.set(qn("w:num"), str(number))


def _clean_pdf() -> bytes:
    """One column CV, no image, no table, no decorative glyph, no raw URL."""
    def draw(pdf):
        _draw_lines(pdf, [
            ("Jean Dupont", 770),
            ("Developpeur Python - Paris", 745),
            ("jean.dupont@example.fr", 725),
            ("Experience", 690),
            ("2020-2023 Developpeur Python - TechCorp", 668),
            ("- Croissance du trafic API de 30% en 6 mois", 648),
            ("- Migration de 5 services vers Kubernetes", 628),
            ("Formation", 590),
            ("2018-2020 Master Informatique - Universite Paris-Saclay", 568),
            ("Competences", 530),
            ("Python, SQL, Docker, Kubernetes, React, AWS", 508),
        ], size=12)

    return _pdf([draw])


def _two_columns_pdf() -> bytes:
    """CV laid out on two columns (left column then right column)."""
    def draw(pdf):
        pdf.setFont("Helvetica", 12)
        pdf.drawString(50, 770, "Jean Dupont")
        _draw_lines(pdf, [
            ("Experience", 700),
            ("2020-2023 Developpeur Python", 678),
            ("Croissance du trafic de 30%", 658),
            ("Migration de 5 services", 638),
        ], x=50)
        _draw_lines(pdf, [
            ("Formation", 700),
            ("2018-2020 Master Informatique", 678),
            ("Universite Paris-Saclay", 658),
        ], x=320)

    return _pdf([draw])


def _table_pdf() -> bytes:
    """CV with an aligned grid (3 columns x 3 rows)."""
    def draw(pdf):
        _draw_lines(pdf, [
            ("Jean Dupont", 770),
            ("Experience", 720),
        ], size=12)
        rows = [
            ("Entreprise", "Role", "Dates"),
            ("TechCorp", "Developpeur", "2020-2023"),
            ("DataInc", "Lead", "2021-2024"),
        ]
        y = 680
        for row in rows:
            for index, cell in enumerate(row):
                pdf.setFont("Helvetica", 11)
                pdf.drawString(50 + index * 150, y, cell)
            y -= 25

    return _pdf([draw])


def _image_only_pdf() -> bytes:
    """Page made of a single image, without any extractable text."""
    from PIL import Image

    image = Image.new("RGB", (600, 800), (235, 235, 235))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    def draw(pdf):
        pdf.drawImage(ImageReader(buffer), 0, 0, width=PAGE_WIDTH, height=PAGE_HEIGHT)

    return _pdf([draw])


def _encrypted_pdf() -> bytes:
    """PDF protected by a password."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4, encrypt="secret")
    pdf.drawString(50, 700, "CONFIDENTIEL")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _reading_order_pdf() -> bytes:
    """Text flow jumping back up three times (boxed side content)."""
    def draw(pdf):
        _draw_lines(pdf, [
            ("Experience", 700),
            ("2020-2023 Developpeur", 678),
            ("Croissance de 30%", 658),
            ("Encadre lateral", 740),
            ("2018-2020 Master", 640),
            ("Universite Paris-Saclay", 620),
            ("Encadre lateral 2", 720),
            ("Competences", 600),
            ("Python, SQL, Docker", 580),
            ("Encadre lateral 3", 700),
        ], size=11)

    return _pdf([draw])


def _header_footer_pdf() -> bytes:
    """Two pages sharing the same header and the same footer."""
    def make_page(body: list[tuple[str, float]]):
        def draw(pdf):
            pdf.setFont("Helvetica", 9)
            pdf.drawString(50, 810, "CONFIDENTIEL - CV Jean Dupont")
            _draw_lines(pdf, body, size=11)
            pdf.setFont("Helvetica", 9)
            pdf.drawString(50, 30, "Page sur 2 - Jean Dupont")
        return draw

    page1 = make_page([("Experience", 700), ("2020-2023 Developpeur", 678)])
    page2 = make_page([("Formation", 700), ("2018-2020 Master", 678)])
    return _pdf([page1, page2])


def _five_pages_pdf() -> bytes:
    """Five pages of plain text (performance fixture)."""
    pages = []
    for index in range(5):
        def draw(pdf, index=index):
            _draw_lines(pdf, [(f"Experience - societe numero {index}", 700 - 20 * line) for line in range(10)], size=11)
        pages.append(draw)
    return _pdf(pages)


def _realistic_pdf() -> bytes:
    """Realistic CV: centred title, photo in the corner, bullet lists."""
    from PIL import Image

    image = Image.new("RGB", (80, 100), (200, 210, 230))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    def draw(pdf):
        pdf.drawImage(ImageReader(buffer), PAGE_WIDTH - 130, PAGE_HEIGHT - 120, width=80, height=100)
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawCentredString(PAGE_WIDTH / 2, PAGE_HEIGHT - 90, "Jean Dupont")
        pdf.setFont("Helvetica", 10)
        pdf.drawCentredString(PAGE_WIDTH / 2, PAGE_HEIGHT - 108, "jean.dupont@example.fr")
        _draw_lines(pdf, [
            ("EXPERIENCE", PAGE_HEIGHT - 170),
            ("2020 - 2023   Developpeur Python   TechCorp", PAGE_HEIGHT - 188),
            ("- Croissance du trafic API de 30% en 6 mois", PAGE_HEIGHT - 202),
            ("- Migration de 5 services vers Kubernetes", PAGE_HEIGHT - 216),
            ("FORMATION", PAGE_HEIGHT - 240),
            ("2018 - 2020   Master Informatique   Universite Paris-Saclay", PAGE_HEIGHT - 258),
            ("COMPETENCES", PAGE_HEIGHT - 282),
            ("Python, SQL, Docker, Kubernetes, React, AWS", PAGE_HEIGHT - 300),
            ("LANGUES", PAGE_HEIGHT - 324),
            ("Francais (natif), Anglais (courant)", PAGE_HEIGHT - 342),
        ])

    return _pdf([draw])


CLEAN_TXT = """Jean Dupont
jean.dupont@example.fr

Experience
2020-2023 Developpeur Python - TechCorp
- Croissance du trafic API de 30% en 6 mois

Formation
2018-2020 Master Informatique - Universite Paris-Saclay

Competences
Python, SQL, Docker, Kubernetes
"""


# ──────────────────────────────────────────────────────────────────────
# Helpers — assertions
# ──────────────────────────────────────────────────────────────────────

def _findings(result: ATSCheckResult, code: str) -> list[ATSFinding]:
    return [finding for finding in result.findings if finding.code == code]


def _has(result: ATSCheckResult, code: str, level: str | None = None) -> bool:
    return any(
        finding.code == code and (level is None or finding.risk_level == level)
        for finding in result.findings
    )


def _pdf_document(data: bytes) -> DocumentInput:
    return extract_text_from_bytes(data, "pdf", filename="cv.pdf")


# ──────────────────────────────────────────────────────────────────────
# Detector 1 — reading order
# ──────────────────────────────────────────────────────────────────────

def test_reading_order_detected_on_non_linear_flow():
    result = run_ats_check(_pdf_document(_reading_order_pdf()))
    findings = _findings(result, "READING_ORDER")
    assert findings, "un flux non linéaire doit être signalé"
    assert findings[0].risk_level == "MEDIUM"
    assert findings[0].page == 1
    assert "sauts" in findings[0].evidence_excerpt


def test_reading_order_quiet_on_linear_flow():
    result = run_ats_check(_pdf_document(_clean_pdf()))
    assert not _has(result, "READING_ORDER")


# ──────────────────────────────────────────────────────────────────────
# Detector 2 — text stored as images
# ──────────────────────────────────────────────────────────────────────

def test_text_in_images_detected_on_image_only_pdf():
    result = run_ats_check(_pdf_document(_image_only_pdf()))
    findings = _findings(result, "TEXT_IN_IMAGES")
    assert findings, "une page image-only doit être signalée"
    assert findings[0].risk_level == "HIGH"
    assert findings[0].page == 1


def test_image_only_pdf_does_not_duplicate_the_missing_sections():
    """Sans texte extractible, le détecteur de sections n'apporte rien de plus."""
    result = run_ats_check(_pdf_document(_image_only_pdf()))
    assert not _has(result, "MISSING_SECTION")
    assert result.risk_label == "HIGH"


def test_text_in_images_quiet_on_text_pdf():
    result = run_ats_check(_pdf_document(_clean_pdf()))
    assert not _has(result, "TEXT_IN_IMAGES")


def test_photo_with_enough_text_is_not_an_ats_risk():
    """A photo next to a real text is not a "text in images" risk."""
    result = run_ats_check(_pdf_document(_realistic_pdf()))
    assert not _has(result, "TEXT_IN_IMAGES")


def test_realistic_cv_with_centred_title_is_not_flagged():
    """A centred title or a photo must not create a false positive."""
    result = run_ats_check(_pdf_document(_realistic_pdf()))
    assert result.findings == [], [finding.message for finding in result.findings]
    assert result.risk_score == 0
    assert result.risk_label == "LOW"


def test_text_in_images_detected_on_docx_with_picture():
    from PIL import Image

    image = Image.new("RGB", (40, 40), (200, 200, 200))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    def build(document):
        document.add_picture(buffer, width=1000000)
        document.add_paragraph("Contact")

    data = _docx_bytes(build)
    result = run_ats_check_bytes(data, "docx")
    assert _has(result, "TEXT_IN_IMAGES", "HIGH")


# ──────────────────────────────────────────────────────────────────────
# Detector 3 — tabular structures
# ──────────────────────────────────────────────────────────────────────

def test_nested_table_detected_on_pdf_grid():
    result = run_ats_check(_pdf_document(_table_pdf()))
    findings = _findings(result, "NESTED_TABLE")
    assert findings, "une grille alignée doit être signalée"
    assert findings[0].risk_level == "MEDIUM"
    assert findings[0].evidence_excerpt


def test_nested_table_detected_on_docx_nested_table():
    def build(document):
        document.add_paragraph("Experience")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Cellule"
        inner = table.cell(0, 0).add_table(rows=1, cols=2)
        inner.cell(0, 0).text = "Imbrique"

    data = _docx_bytes(build)
    result = run_ats_check_bytes(data, "docx")
    findings = _findings(result, "NESTED_TABLE")
    assert findings, "un tableau imbriqué doit être signalé"
    assert "imbriqué" in findings[0].message.lower()


def test_nested_table_quiet_on_plain_cv():
    result = run_ats_check(_pdf_document(_clean_pdf()))
    assert not _has(result, "NESTED_TABLE")


# ──────────────────────────────────────────────────────────────────────
# Detector 4 — multiple columns
# ──────────────────────────────────────────────────────────────────────

def test_multiple_columns_detected_on_two_column_pdf():
    result = run_ats_check(_pdf_document(_two_columns_pdf()))
    findings = _findings(result, "MULTIPLE_COLUMNS")
    assert findings, "une mise en page deux colonnes doit être signalée"
    assert findings[0].risk_level == "MEDIUM"
    assert findings[0].evidence_excerpt


def test_multiple_columns_detected_on_docx_columns():
    def build(document):
        document.add_paragraph("Experience")
        document.add_paragraph("2020-2023 Developpeur Python")
        _set_columns(document, 2)

    data = _docx_bytes(build)
    result = run_ats_check_bytes(data, "docx")
    findings = _findings(result, "MULTIPLE_COLUMNS")
    assert findings, "des colonnes déclarées doivent être signalées"
    assert findings[0].risk_level == "MEDIUM"


def test_multiple_columns_quiet_on_single_column_pdf():
    result = run_ats_check(_pdf_document(_clean_pdf()))
    assert not _has(result, "MULTIPLE_COLUMNS")


# ──────────────────────────────────────────────────────────────────────
# Detector 5 — headers / footers
# ──────────────────────────────────────────────────────────────────────

def test_header_footer_detected_on_repeated_bands():
    result = run_ats_check(_pdf_document(_header_footer_pdf()))
    findings = _findings(result, "HEADER_FOOTER")
    assert findings, "un en-tête / pied de page répété doit être signalé"
    assert findings[0].risk_level == "LOW"
    assert findings[0].page == 1


def test_header_footer_quiet_on_single_page():
    result = run_ats_check(_pdf_document(_clean_pdf()))
    assert not _has(result, "HEADER_FOOTER")


# ──────────────────────────────────────────────────────────────────────
# Detector 6 — decorative characters
# ──────────────────────────────────────────────────────────────────────

def test_decorative_chars_detected_on_ligatures():
    text = "Jean Dupont\nExperience\n2020-2023 ﬁ Developpeur ﬂ TechCorp\nFormation\n2018-2020 Master\n"
    document = DocumentInput(text=text, filename="cv.txt", filetype="txt")
    result = run_ats_check(document)
    findings = _findings(result, "DECORATIVE_CHARS")
    assert findings, "des ligatures doivent être signalées"
    assert findings[0].risk_level == "LOW"
    assert "ﬁ" in findings[0].evidence_excerpt


def test_decorative_chars_quiet_on_plain_text():
    document = DocumentInput(text=CLEAN_TXT, filename="cv.txt", filetype="txt")
    result = run_ats_check(document)
    assert not _has(result, "DECORATIVE_CHARS")


def test_accents_are_not_reported_as_decorative():
    text = "Jean Dupont\nExpérience\n2020-2023 Développeur — Études à Paris\n"
    document = DocumentInput(text=text, filename="cv.txt", filetype="txt")
    result = run_ats_check(document)
    assert not _has(result, "DECORATIVE_CHARS")


# ──────────────────────────────────────────────────────────────────────
# Detector 7 — raw URLs
# ──────────────────────────────────────────────────────────────────────

def test_unreadable_links_detected_on_raw_urls():
    text = (
        "Jean Dupont\nExperience\n2020-2023 Developpeur\n"
        "- Portfolio : https://github.com/jeandupont/portfolio\n"
        "- Site : www.jeandupont.fr\n"
    )
    document = DocumentInput(text=text, filename="cv.txt", filetype="txt")
    result = run_ats_check(document)
    findings = _findings(result, "UNREADABLE_LINKS")
    assert findings, "des URL brutes doivent être signalées"
    assert findings[0].risk_level == "LOW"


def test_email_is_not_reported_as_a_raw_link():
    text = "Jean Dupont\njean.dupont@example.fr\nExperience\n2020-2023 Developpeur\n"
    document = DocumentInput(text=text, filename="cv.txt", filetype="txt")
    result = run_ats_check(document)
    assert not _has(result, "UNREADABLE_LINKS")


# ──────────────────────────────────────────────────────────────────────
# Detector 8 — missing sections
# ──────────────────────────────────────────────────────────────────────

def test_missing_section_detected_on_txt_without_sections():
    text = "Jean Dupont\nContact\njean.dupont@example.fr\n"
    document = DocumentInput(text=text, filename="cv.txt", filetype="txt")
    result = run_ats_check(document)
    findings = _findings(result, "MISSING_SECTION")
    assert findings, "les sections absentes doivent être signalées"
    assert all(finding.risk_level == "HIGH" for finding in findings)
    assert any("Formation" in finding.message for finding in findings)


def test_missing_section_quiet_on_complete_cv():
    document = DocumentInput(text=CLEAN_TXT, filename="cv.txt", filetype="txt")
    result = run_ats_check(document)
    assert not _has(result, "MISSING_SECTION")


def test_expected_sections_are_configurable():
    text = "Jean Dupont\nExperience\n2020-2023 Developpeur\n"
    document = DocumentInput(text=text, filename="cv.txt", filetype="txt")
    result = run_ats_check(document, expected_sections=["Langues"])
    findings = _findings(result, "MISSING_SECTION")
    assert len(findings) == 1
    assert "Langues" in findings[0].message


def test_expected_sections_present_are_not_reported():
    text = "Jean Dupont\nLangues\nFrancais, Anglais\n"
    document = DocumentInput(text=text, filename="cv.txt", filetype="txt")
    result = run_ats_check(document, expected_sections=["Langues"])
    assert not _has(result, "MISSING_SECTION")


# ──────────────────────────────────────────────────────────────────────
# Detector 9 — parse errors
# ──────────────────────────────────────────────────────────────────────

def test_encrypted_pdf_reports_parse_error():
    result = run_ats_check_bytes(_encrypted_pdf(), "pdf")
    findings = _findings(result, "PARSE_ERROR")
    assert findings, "un PDF chiffré doit produire une erreur d'extraction"
    assert findings[0].risk_level == "HIGH"
    assert findings[0].error == "PARSE_ERROR"
    assert result.parse_errors
    assert result.pages_analyzed == 0
    assert result.risk_label == "HIGH"


def test_corrupted_docx_reports_parse_error():
    result = run_ats_check_bytes(b"ceci n'est pas un docx", "docx")
    findings = _findings(result, "PARSE_ERROR")
    assert findings, "un DOCX corrompu doit produire une erreur d'extraction"
    assert findings[0].risk_level == "HIGH"
    assert findings[0].error == "PARSE_ERROR"


def test_corrupted_pdf_reports_parse_error():
    result = run_ats_check_bytes(b"%PDF-1.7 pas un vrai pdf", "pdf")
    assert _has(result, "PARSE_ERROR", "HIGH")


def test_unsupported_filetype_reports_parse_error():
    result = run_ats_check_bytes(b"whatever", "rtf")
    assert _has(result, "PARSE_ERROR", "HIGH")


# ──────────────────────────────────────────────────────────────────────
# Scoring, labels and vocabulary
# ──────────────────────────────────────────────────────────────────────

def test_score_is_weighted_by_risk_level():
    findings = [
        ATSFinding(code="A", risk_level="LOW", message="m", page=1, bbox=None, evidence_excerpt="x"),
        ATSFinding(code="B", risk_level="MEDIUM", message="m", page=1, bbox=None, evidence_excerpt="x"),
        ATSFinding(code="C", risk_level="HIGH", message="m", page=1, bbox=None, evidence_excerpt="x"),
    ]
    assert calculate_risk_score(findings) == 75


def test_score_is_capped_at_100():
    findings = [
        ATSFinding(code="A", risk_level="HIGH", message="m", page=1, bbox=None, evidence_excerpt="x")
        for _ in range(5)
    ]
    assert calculate_risk_score(findings) == 100


@pytest.mark.parametrize(
    ("score", "label"),
    [(0, "LOW"), (5, "LOW"), (19, "LOW"), (20, "MEDIUM"), (49, "MEDIUM"), (50, "HIGH"), (100, "HIGH")],
)
def test_label_thresholds(score, label):
    assert calculate_risk_label(score) == label


def test_risk_interpretation_is_provided():
    assert describe_risk("LOW") == "Faible risque"
    assert "modéré" in describe_risk("MEDIUM")
    assert "restructuration" in describe_risk("HIGH")
    assert set(RISK_INTERPRETATIONS) == {"LOW", "MEDIUM", "HIGH"}


def test_result_carries_the_interpretation():
    result = run_ats_check(_pdf_document(_clean_pdf()))
    assert result.risk_interpretation == describe_risk(result.risk_label)


def test_clean_pdf_is_a_low_risk_document():
    result = run_ats_check(_pdf_document(_clean_pdf()))
    assert result.risk_score == 0
    assert result.risk_label == "LOW"
    assert result.risk_interpretation == "Faible risque"
    assert result.pages_analyzed == 1
    assert result.parse_errors == []


def test_every_finding_is_complete_and_verifiable():
    result = run_ats_check(_pdf_document(_table_pdf()))
    assert result.findings
    for finding in result.findings:
        assert finding.code
        assert finding.risk_level in {"LOW", "MEDIUM", "HIGH"}
        assert finding.page >= 1
        assert finding.message.strip()
        assert finding.evidence_excerpt.strip()
        assert len(finding.evidence_excerpt) <= 120


def test_findings_never_claim_a_certain_rejection():
    result = run_ats_check(_pdf_document(_image_only_pdf()))
    for finding in result.findings:
        lowered = finding.message.lower()
        assert "rejet" not in lowered
        assert "refus" not in lowered
        assert "échec certain" not in lowered


# ──────────────────────────────────────────────────────────────────────
# API behaviour
# ──────────────────────────────────────────────────────────────────────

def test_run_ats_check_is_deterministic():
    data = _two_columns_pdf()
    first = run_ats_check(_pdf_document(data))
    second = run_ats_check(_pdf_document(data))
    assert first == second


def test_run_ats_check_uses_the_raw_bytes_carried_by_the_document():
    document = extract_text_from_bytes(_two_columns_pdf(), "pdf", filename="cv.pdf")
    assert document.raw_bytes, "le parseur doit conserver les octets du fichier"
    result = run_ats_check(document)
    assert _has(result, "MULTIPLE_COLUMNS"), "l'analyse doit utiliser la structure réelle du PDF"


def test_run_ats_check_file_reads_a_pdf(tmp_path):
    path = tmp_path / "cv.pdf"
    path.write_bytes(_two_columns_pdf())
    result = run_ats_check_file(str(path))
    assert result.pages_analyzed == 1
    assert _has(result, "MULTIPLE_COLUMNS")


def test_run_ats_check_file_reads_a_docx(tmp_path):
    def build(document):
        document.add_paragraph("Experience")
        document.add_paragraph("2020-2023 Developpeur Python")

    path = tmp_path / "cv.docx"
    path.write_bytes(_docx_bytes(build))
    result = run_ats_check_file(str(path))
    assert result.pages_analyzed >= 1
    assert result.parse_errors == []


def test_run_ats_check_does_not_use_the_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("aucun appel réseau ne doit être effectué")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    result = run_ats_check(_pdf_document(_clean_pdf()))
    assert result.risk_label == "LOW"


def test_analysis_is_fast_enough_on_five_pages():
    data = _five_pages_pdf()
    started = time.perf_counter()
    result = run_ats_check(_pdf_document(data))
    duration = time.perf_counter() - started
    assert result.pages_analyzed == 5
    assert duration < 3.0, f"analyse trop lente : {duration:.2f}s"


def test_sections_are_found_in_a_pdf_export():
    result = run_ats_check(_pdf_document(_clean_pdf()))
    assert not _has(result, "MISSING_SECTION")


def test_docx_without_sections_reports_the_missing_ones():
    def build(document):
        document.add_paragraph("Jean Dupont")
        document.add_paragraph("Contact")

    data = _docx_bytes(build)
    result = run_ats_check_bytes(data, "docx")
    findings = _findings(result, "MISSING_SECTION")
    assert {finding.message for finding in findings}
    assert all(finding.risk_level == "HIGH" for finding in findings)
