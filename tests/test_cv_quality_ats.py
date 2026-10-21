"""Unit tests for the ATS risk analysis (Mission 04).

All fixtures are synthetic: the PDFs are built on the fly with ``reportlab``
and the DOCX with ``python-docx``.  No real CV, no personal data, no file
from the disk, no network access.

Coverage:
    * the 9 detectors, each with its positive and negative case;
    * the real PDF/DOCX fixtures required by the mission (single column,
      two columns, table, image only, encrypted, clean DOCX, DOCX with
      columns, DOCX with a nested table);
    * the weighted score and the interpretation labels;
    * the edge cases (empty document, determinism, performance).
"""

from __future__ import annotations

import io
import time

import pytest

from career.cv_quality import (
    ATSCheckResult,
    ATSFinding,
    ATSRiskLevel,
    DocumentInput,
    run_ats_check,
    run_ats_check_bytes,
    run_ats_check_file,
)
from career.cv_quality.ats import (
    DEFAULT_EXPECTED_SECTIONS,
    RISK_INTERPRETATIONS,
    PageContent,
    TextChunk,
    _calculate_risk_label,
    _calculate_risk_score,
    detect_decorative_chars,
    detect_headers_footers,
    detect_missing_sections,
    detect_multiple_columns,
    detect_nested_tables,
    detect_parse_errors,
    detect_reading_order,
    detect_text_in_images,
    detect_unreadable_links,
    risk_interpretation,
)
from career.cv_quality.models import ATSFinding as ATSFindingModel

reportlab = pytest.importorskip("reportlab", reason="reportlab is required to build the PDF fixtures")
docx_module = pytest.importorskip("docx", reason="python-docx is required to build the DOCX fixtures")

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402


# ──────────────────────────────────────────────────────────────────────
# Text fixtures
# ──────────────────────────────────────────────────────────────────────

# Clean single-column CV text
CLEAN_CV = """
Jean Dupont
jean.dupont@email.fr
+33 6 12 34 56 78

Expérience
2020-2023 | Développeur Python | TechCorp
- Augmentation du trafic API de 30% en 6 mois
- Réduction des coûts infrastructure de 15k€/an
- Migration de 5 services vers Kubernetes

2018-2020 | Développeur Junior | StartupInc
- Développement features React
- Tests unitaires couverture 80%

Formation
2018-2020 | Master Informatique | Université Paris-Saclay
2015-2018 | Licence Informatique | Université Paris-Diderot

Compétences
Python, SQL, Docker, Kubernetes, React, AWS

Langues
Français (natif), Anglais (courant)
"""

# Two-column layout simulation (short lines side by side)
TWO_COLUMN_CV = """
Jean Dupont          jean.dupont@email.fr
+33 6 12 34 56 78    LinkedIn: linkedin.com/in/jd

Expérience           Formation
2020-2023 Dev        2018-2020 Master
TechCorp             Paris-Saclay
- API 30%            2015-2018 Licence
- Infra 15k€         Paris-Diderot
- K8s 5 services

Compétences          Langues
Python, SQL          Français (natif)
Docker, K8s          Anglais (courant)
"""

# CV with a markdown table
TABLE_CV = """
Jean Dupont
Expérience
| Entreprise | Rôle | Dates |
|------------|------|-------|
| TechCorp   | Dev  | 2020  |
| DataInc    | Lead | 2021  |
Formation
| École | Diplôme | Année |
|-------|---------|-------|
| Uni   | Master  | 2020  |
"""

# CV with tab-separated columns (simulating a table)
TABULAR_CV = """
Jean Dupont
Expérience
TechCorp\tDéveloppeur\t2020-2023
DataInc\tLead Dev\t2021-2024
StartupInc\tJunior\t2018-2020
Formation
Paris-Saclay\tMaster\t2020
Paris-Diderot\tLicence\t2018
"""

# CV with decorative characters / ligatures
DECORATIVE_CV = """
Jean Dupont
Expérience
2020-2023 ﬁ Développeur Python ﬂ TechCorp
• Augmentation du trafic de 30%
• Réduction des coûts de 15k€
◆ Migration vers Kubernetes
► Gestion équipe 5 personnes
Formation
2018-2020 Master Informatique
"""

# CV with raw URLs
URL_CV = """
Jean Dupont
Expérience
2020-2023 | Développeur | TechCorp
- Voir mon GitHub: https://github.com/jeandupont/project
- Portfolio: https://www.jeandupont.fr/portfolio/projects
- LinkedIn: https://linkedin.com/in/jeandupont/details
Formation
2018-2020 | Master | Université Paris-Saclay
"""

# CV missing expected sections
MISSING_SECTIONS_CV = """
Jean Dupont
Expérience
2020-2023 | Développeur | TechCorp
Formation
2018-2020 | Master | Université Paris-Saclay
"""

# Repeated header/footer, one block per page
HEADER_FOOTER_PAGE_1 = """CONFIDENTIEL - CV Jean Dupont
Jean Dupont
Expérience
2020-2023 | Développeur | TechCorp
- Augmentation trafic 30%
CONFIDENTIEL - CV Jean Dupont"""

HEADER_FOOTER_PAGE_2 = """CONFIDENTIEL - CV Jean Dupont
Formation
2018-2020 | Master | Université Paris-Saclay
CONFIDENTIEL - CV Jean Dupont"""

HEADER_FOOTER_PAGE_3 = """CONFIDENTIEL - CV Jean Dupont
Compétences
Python, SQL, Docker
CONFIDENTIEL - CV Jean Dupont"""


# ──────────────────────────────────────────────────────────────────────
# Hand-built page fixtures (unit level)
# ──────────────────────────────────────────────────────────────────────

def make_chunk(text: str, x: float, y: float, size: float = 12.0) -> TextChunk:
    """Build a positioned text run."""
    width = 0.5 * size * len(text)
    return TextChunk(text=text, x0=x, y0=y, x1=x + width, y1=y + size)


def make_page(
    text: str,
    *,
    page_num: int = 1,
    chunks: list[TextChunk] | None = None,
    images: list[tuple[float, float, float, float]] | None = None,
    tables: list[tuple[float, float, float, float]] | None = None,
    width: float = 595.0,
    height: float = 842.0,
    header_text: str = "",
    footer_text: str = "",
    columns: int = 1,
    table_count: int = 0,
    nested_table_count: int = 0,
) -> PageContent:
    """Build a page fixture."""
    return PageContent(
        page_num=page_num,
        text=text,
        chunks=chunks or [],
        images=images or [],
        tables=tables or [],
        width=width,
        height=height,
        header_text=header_text,
        footer_text=footer_text,
        columns=columns,
        table_count=table_count,
        nested_table_count=nested_table_count,
    )


# Page with reading order issues (simulated via real coordinates).
# PDF coordinates: Y increases upward, reading goes top-to-bottom.
READING_ORDER_PAGE = make_page(
    text="Col1\nCol2\nCol1\nCol2\nCol1\nCol2",
    chunks=[
        make_chunk("Top", 50, 800), make_chunk("Top", 350, 800),
        make_chunk("Mid", 50, 700), make_chunk("Mid", 350, 700),
        make_chunk("Jump", 50, 800), make_chunk("Jump", 350, 800),
        make_chunk("Mid", 50, 700), make_chunk("Mid", 350, 700),
        make_chunk("Jump", 50, 800), make_chunk("Jump", 350, 800),
        make_chunk("Mid", 50, 700), make_chunk("Mid", 350, 700),
        make_chunk("Jump", 50, 800), make_chunk("Jump", 350, 800),
    ],
)

# Image-only page simulation (no text, one dominant image)
IMAGE_ONLY_PAGE = make_page(
    text=" ",
    images=[(0, 0, 595, 842)],
)

# Page with an explicit table object
TABLE_PAGE = make_page(
    text="Expérience\n| A | B |\n|---|---|\n| 1 | 2 |",
    tables=[(50, 100, 500, 200)],
)

# Multi-column page (two narrow clusters of left edges)
MULTI_COL_PAGE = make_page(
    text="Left column text\nRight column text",
    chunks=[
        *[make_chunk(c, 50 + i * 10, 100) for i, c in enumerate("Leftcolumntext")],
        *[make_chunk(c, 350 + i * 10, 100) for i, c in enumerate("Rightcolumntext")],
    ],
)


# ──────────────────────────────────────────────────────────────────────
# Synthetic PDF fixtures (real files, built on the fly)
# ──────────────────────────────────────────────────────────────────────

PAGE_WIDTH, PAGE_HEIGHT = A4


def _pdf_canvas() -> tuple[canvas.Canvas, io.BytesIO]:
    """Return a reportlab canvas writing into an in-memory buffer."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    return pdf, buffer


def pdf_single_column() -> bytes:
    """A clean one-column CV."""
    pdf, buffer = _pdf_canvas()
    pdf.setFont("Helvetica", 11)
    y = PAGE_HEIGHT - 80
    for line in [
        "Jean Dupont",
        "jean.dupont@email.fr",
        "",
        "Experience",
        "2020-2023 | Developpeur Python | TechCorp",
        "Formation",
        "2018-2020 | Master Informatique | Paris-Saclay",
        "Competences",
        "Python, SQL, Docker, Kubernetes",
    ]:
        if line:
            pdf.drawString(54, y, line)
        y -= 16
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def pdf_two_columns() -> bytes:
    """A CV laid out on two columns."""
    pdf, buffer = _pdf_canvas()
    pdf.setFont("Helvetica", 10)
    left = [
        "Experience",
        "2020-2023 Developpeur Python",
        "TechCorp",
        "Augmentation du trafic de 30%",
        "Migration de 5 services",
        "2018-2020 Developpeur Junior",
        "StartupInc",
    ]
    right = [
        "Formation",
        "2018-2020 Master Informatique",
        "Paris-Saclay",
        "2015-2018 Licence Informatique",
        "Paris-Diderot",
        "Competences",
        "Python SQL Docker",
    ]
    y = PAGE_HEIGHT - 80
    for left_line, right_line in zip(left, right):
        pdf.drawString(54, y, left_line)
        pdf.drawString(320, y, right_line)
        y -= 15
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def pdf_with_table() -> bytes:
    """A CV holding a real drawn table."""
    from reportlab.platypus import SimpleDocTemplate

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )
    document.build([_reportlab_paragraph("Experience"), _reportlab_table()])
    return buffer.getvalue()


def _reportlab_paragraph(text: str):
    """Build a reportlab paragraph."""
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph

    return Paragraph(text, getSampleStyleSheet()["Normal"])


def _reportlab_table():
    """Build a reportlab table with visible rules."""
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    data = [
        ["Entreprise", "Role", "Dates"],
        ["TechCorp", "Dev", "2020"],
        ["DataInc", "Lead", "2021"],
    ]
    table = Table(data, colWidths=[150, 120, 100])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
    ]))
    return table


def pdf_image_only() -> bytes:
    """A scanned-looking page: a single full-page image, no text."""
    from PIL import Image
    from reportlab.lib.utils import ImageReader

    image = Image.new("RGB", (60, 80), (235, 235, 235))
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    image_buffer.seek(0)

    pdf, buffer = _pdf_canvas()
    pdf.drawImage(ImageReader(image_buffer), 0, 0, width=PAGE_WIDTH, height=PAGE_HEIGHT)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def pdf_with_photo_and_text() -> bytes:
    """A CV with a small photo next to a normal text: no image risk."""
    from PIL import Image
    from reportlab.lib.utils import ImageReader

    image = Image.new("RGB", (40, 40), (120, 160, 220))
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    image_buffer.seek(0)

    pdf, buffer = _pdf_canvas()
    pdf.setFont("Helvetica", 11)
    y = PAGE_HEIGHT - 80
    for line in [
        "Jean Dupont",
        "jean.dupont@email.fr",
        "Experience",
        "2020-2023 Developpeur Python TechCorp",
        "Formation",
        "2018-2020 Master Informatique Paris-Saclay",
        "Competences",
        "Python SQL Docker Kubernetes React AWS",
    ]:
        pdf.drawString(54, y, line)
        y -= 16
    pdf.drawImage(ImageReader(image_buffer), 480, PAGE_HEIGHT - 140, width=60, height=60)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def pdf_encrypted() -> bytes:
    """A password protected PDF."""
    import pypdf

    pdf, buffer = _pdf_canvas()
    pdf.setFont("Helvetica", 11)
    pdf.drawString(54, PAGE_HEIGHT - 80, "Confidentiel")
    pdf.showPage()
    pdf.save()

    writer = pypdf.PdfWriter(clone_from=io.BytesIO(buffer.getvalue()))
    writer.encrypt("mot-de-passe")
    encrypted = io.BytesIO()
    writer.write(encrypted)
    return encrypted.getvalue()


def pdf_corrupt() -> bytes:
    """Bytes that look like a PDF but cannot be parsed."""
    return b"%PDF-1.7\n" + b"\x00\x01\x02not a real pdf body\xff" * 12


def pdf_decorative() -> bytes:
    """A CV using decorative characters (bullet, dashes, curly quotes)."""
    pdf, buffer = _pdf_canvas()
    pdf.setFont("Helvetica", 11)
    y = PAGE_HEIGHT - 80
    for line in [
        "Jean Dupont",
        "Experience",
        "2020-2023 – Développeur Python — TechCorp",
        "• Augmentation du trafic de 30%",
        "• Réduction des coûts de 15k€",
        "Formation",
        "2018-2020 Master Informatique",
        "« Diplôme » 2015-2018 Licence",
    ]:
        pdf.drawString(54, y, line)
        y -= 16
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def pdf_repeated_header() -> bytes:
    """Three pages sharing the same header and footer."""
    pdf, buffer = _pdf_canvas()
    pdf.setFont("Helvetica", 11)
    bodies = [
        ["Experience", "2020-2023 Developpeur Python TechCorp"],
        ["Formation", "2018-2020 Master Informatique Paris-Saclay"],
        ["Competences", "Python SQL Docker Kubernetes"],
    ]
    for body in bodies:
        pdf.drawString(54, PAGE_HEIGHT - 60, "CONFIDENTIEL - CV Jean Dupont")
        y = PAGE_HEIGHT - 90
        for line in body:
            pdf.drawString(54, y, line)
            y -= 16
        pdf.drawString(54, 40, "CONFIDENTIEL - CV Jean Dupont")
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def pdf_non_linear_blocks() -> bytes:
    """A CV whose callout boxes are painted after the body (non-linear order)."""
    pdf, buffer = _pdf_canvas()
    pdf.setFont("Helvetica", 11)

    y = PAGE_HEIGHT - 100
    for line in [
        "Jean Dupont",
        "Experience",
        "2020-2023 Developpeur Python TechCorp",
        "Formation",
        "2018-2020 Master Informatique Paris-Saclay",
        "Competences",
        "Python SQL Docker Kubernetes React AWS",
    ]:
        pdf.drawString(54, y, line)
        y -= 16

    # Three callout boxes painted *after* the body: the extraction order
    # goes back up the page three times.
    for index, box_y in enumerate((PAGE_HEIGHT - 160, PAGE_HEIGHT - 130, PAGE_HEIGHT - 100)):
        pdf.setFont("Helvetica", 9)
        pdf.drawString(320, box_y, f"Encadre {index + 1} - info complementaire")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def pdf_missing_sections() -> bytes:
    """A CV without the Compétences / Langues / Projets sections."""
    pdf, buffer = _pdf_canvas()
    pdf.setFont("Helvetica", 11)
    y = PAGE_HEIGHT - 80
    for line in [
        "Jean Dupont",
        "Experience",
        "2020-2023 Developpeur Python TechCorp",
        "Formation",
        "2018-2020 Master Informatique Paris-Saclay",
    ]:
        pdf.drawString(54, y, line)
        y -= 16
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


# ──────────────────────────────────────────────────────────────────────
# Synthetic DOCX fixtures (real files, built on the fly)
# ──────────────────────────────────────────────────────────────────────

def _docx_bytes(document) -> bytes:
    """Serialize a python-docx document into bytes."""
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def docx_clean() -> bytes:
    """A clean one-column DOCX CV."""
    document = docx_module.Document()
    for line in [
        "Jean Dupont",
        "jean.dupont@email.fr",
        "Experience",
        "2020-2023 | Developpeur Python | TechCorp",
        "Formation",
        "2018-2020 | Master Informatique | Paris-Saclay",
        "Competences",
        "Python, SQL, Docker, Kubernetes",
    ]:
        document.add_paragraph(line)
    return _docx_bytes(document)


def docx_two_columns() -> bytes:
    """A DOCX whose section declares two columns."""
    from docx.oxml.ns import qn

    document = docx_module.Document()
    for line in [
        "Jean Dupont",
        "Experience",
        "2020-2023 Developpeur Python TechCorp",
        "Formation",
        "2018-2020 Master Informatique Paris-Saclay",
        "Competences",
        "Python SQL Docker Kubernetes",
    ]:
        document.add_paragraph(line)

    cols = document.sections[0]._sectPr.find(qn("w:cols"))
    if cols is None:
        from docx.oxml import OxmlElement

        cols = OxmlElement("w:cols")
        document.sections[0]._sectPr.append(cols)
    cols.set(qn("w:num"), "2")
    return _docx_bytes(document)


def docx_nested_table() -> bytes:
    """A DOCX holding a table inside a table cell."""
    document = docx_module.Document()
    document.add_paragraph("Jean Dupont")
    document.add_paragraph("Experience")

    outer = document.add_table(rows=2, cols=2)
    outer.cell(0, 0).text = "TechCorp"
    outer.cell(0, 1).text = "Developpeur"
    outer.cell(1, 0).text = "DataInc"
    outer.cell(1, 1).text = "Lead"

    inner = outer.cell(0, 0).add_table(rows=1, cols=1)
    inner.cell(0, 0).text = "Detail poste"

    document.add_paragraph("Formation")
    document.add_paragraph("2018-2020 Master Informatique Paris-Saclay")
    document.add_paragraph("Competences")
    document.add_paragraph("Python SQL Docker")
    return _docx_bytes(document)


def docx_decorative() -> bytes:
    """A DOCX using ligatures and decorative glyphs."""
    document = docx_module.Document()
    for line in [
        "Jean Dupont",
        "Experience",
        "2020-2023 ﬁ Développeur Python ﬂ TechCorp",
        "• Augmentation du trafic de 30%",
        "◆ Migration vers Kubernetes",
        "► Gestion équipe 5 personnes",
        "Formation",
        "2018-2020 Master Informatique",
    ]:
        document.add_paragraph(line)
    return _docx_bytes(document)


def docx_with_header() -> bytes:
    """A DOCX repeating a header on every page (two pages)."""
    from docx.enum.text import WD_BREAK

    document = docx_module.Document()
    header = document.sections[0].header
    header.paragraphs[0].text = "CONFIDENTIEL - CV Jean Dupont"
    for line in [
        "Jean Dupont",
        "Experience",
        "2020-2023 Developpeur Python TechCorp",
        "Formation",
        "2018-2020 Master Informatique Paris-Saclay",
        "Competences",
        "Python SQL Docker Kubernetes",
    ]:
        document.add_paragraph(line)

    # An explicit page break: the header is then repeated on two pages.
    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    for line in [
        "Projets",
        "Librairie open source validation",
        "Langues",
        "Francais natif, Anglais courant",
    ]:
        document.add_paragraph(line)
    return _docx_bytes(document)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def make_doc(text: str, filetype: str = "txt", page_count: int | None = None) -> DocumentInput:
    """Build a DocumentInput from raw text."""
    if page_count is None:
        page_count = max(1, (len(text) // 3000) + 1)
    return DocumentInput(
        text=text,
        filename=f"test.{filetype}",
        filetype=filetype,
        page_count=page_count,
    )


def find_findings(result: ATSCheckResult, code: str) -> list[ATSFinding]:
    """Return the findings matching a code."""
    return [f for f in result.findings if f.code == code]


def has_finding(result: ATSCheckResult, code: str, risk_level: ATSRiskLevel | None = None) -> bool:
    """Tell whether a finding (optionally with a given level) is present."""
    return any(
        f.code == code and (risk_level is None or f.risk_level == risk_level)
        for f in result.findings
    )


# ──────────────────────────────────────────────────────────────────────
# Detector 1: Reading Order
# ──────────────────────────────────────────────────────────────────────

def test_detect_reading_order_with_coordinates():
    """Non-monotonic Y positions => MEDIUM risk."""
    findings = detect_reading_order([READING_ORDER_PAGE])
    assert len(findings) >= 1
    assert findings[0].code == "READING_ORDER"
    assert findings[0].risk_level == "MEDIUM"
    assert findings[0].page == 1


def test_detect_reading_order_text_fallback():
    """Text-only fallback on a two-column pattern."""
    findings = detect_reading_order([make_page(TWO_COLUMN_CV)])
    assert len(findings) >= 1
    assert findings[0].code == "READING_ORDER"


def test_no_reading_order_clean():
    """A clean single-column CV does not trigger the reading order."""
    assert detect_reading_order([make_page(CLEAN_CV)]) == []


def test_pdf_with_non_linear_blocks_is_flagged():
    """A real PDF whose boxes are painted after the body is flagged."""
    result = run_ats_check_bytes(pdf_non_linear_blocks(), "pdf", filename="cv.pdf")
    assert has_finding(result, "READING_ORDER", "MEDIUM")


# ──────────────────────────────────────────────────────────────────────
# Detector 2: Text in Images
# ──────────────────────────────────────────────────────────────────────

def test_detect_text_in_images_high_risk():
    """An image-only page with no usable text => HIGH risk."""
    findings = detect_text_in_images([IMAGE_ONLY_PAGE])
    assert len(findings) >= 1
    assert findings[0].code == "TEXT_IN_IMAGES"
    assert findings[0].risk_level == "HIGH"
    assert "scanné" in findings[0].message or "OCR" in findings[0].message


def test_detect_text_in_images_with_some_text():
    """A page with images but almost no text => HIGH risk."""
    page = make_page(text="A" * 30, images=[(0, 0, 595, 842)])
    findings = detect_text_in_images([page])
    assert len(findings) >= 1
    assert findings[0].risk_level == "HIGH"


def test_no_text_in_images_normal():
    """A normal text page without image is not flagged."""
    assert detect_text_in_images([make_page(CLEAN_CV)]) == []


def test_small_photo_next_to_text_is_not_flagged():
    """A small picture that hides no text is not a risk."""
    page = make_page(text=CLEAN_CV, images=[(480, 700, 540, 760)])
    assert detect_text_in_images([page]) == []


def test_pdf_image_only_is_high_risk():
    """A real scanned PDF => HIGH risk and no bogus missing-section noise."""
    result = run_ats_check_bytes(pdf_image_only(), "pdf", filename="scan.pdf")
    assert has_finding(result, "TEXT_IN_IMAGES", "HIGH")
    assert find_findings(result, "MISSING_SECTION") == []


def test_pdf_with_photo_and_text_is_not_flagged():
    """A real PDF with a photo and a normal text is not flagged."""
    result = run_ats_check_bytes(pdf_with_photo_and_text(), "pdf", filename="cv.pdf")
    assert not has_finding(result, "TEXT_IN_IMAGES")


# ──────────────────────────────────────────────────────────────────────
# Detector 3: Tabular structures
# ──────────────────────────────────────────────────────────────────────

def test_detect_markdown_table():
    """Markdown table pattern => MEDIUM risk."""
    findings = detect_nested_tables([make_page(TABLE_CV)])
    assert len(findings) >= 1
    assert findings[0].code == "NESTED_TABLE"
    assert findings[0].risk_level == "MEDIUM"


def test_detect_tabular_alignment():
    """Tab-separated columns => MEDIUM risk."""
    findings = detect_nested_tables([make_page(TABULAR_CV)])
    assert len(findings) >= 1
    assert findings[0].code == "NESTED_TABLE"
    assert findings[0].risk_level == "MEDIUM"


def test_detect_native_table_object():
    """An explicit table object => MEDIUM risk with a bbox."""
    findings = detect_nested_tables([TABLE_PAGE])
    assert len(findings) >= 1
    assert findings[0].code == "NESTED_TABLE"
    assert findings[0].risk_level == "MEDIUM"
    assert any(f.bbox is not None for f in findings)


def test_no_table_linear_text():
    """A linear text does not trigger the table detection."""
    assert detect_nested_tables([make_page(CLEAN_CV)]) == []


def test_pdf_with_drawn_table_is_flagged():
    """A real PDF holding a drawn table => MEDIUM risk."""
    result = run_ats_check_bytes(pdf_with_table(), "pdf", filename="cv.pdf")
    assert has_finding(result, "NESTED_TABLE", "MEDIUM")


def test_docx_with_nested_table_is_flagged():
    """A real DOCX holding a nested table => MEDIUM risk."""
    result = run_ats_check_bytes(docx_nested_table(), "docx", filename="cv.docx")
    assert has_finding(result, "NESTED_TABLE", "MEDIUM")
    assert any("imbriqué" in f.message for f in find_findings(result, "NESTED_TABLE"))


# ──────────────────────────────────────────────────────────────────────
# Detector 4: Multiple Columns
# ──────────────────────────────────────────────────────────────────────

def test_detect_multiple_columns_explicit():
    """Two narrow clusters of left edges => MEDIUM risk."""
    findings = detect_multiple_columns([MULTI_COL_PAGE])
    assert len(findings) >= 1
    assert findings[0].code == "MULTIPLE_COLUMNS"
    assert findings[0].risk_level == "MEDIUM"


def test_detect_multiple_columns_text_heuristic():
    """Text heuristic for a two-column layout."""
    findings = detect_multiple_columns([make_page(TWO_COLUMN_CV)])
    assert len(findings) >= 1
    assert findings[0].code == "MULTIPLE_COLUMNS"


def test_no_multiple_columns_clean():
    """A single column clean CV does not trigger."""
    assert detect_multiple_columns([make_page(CLEAN_CV)]) == []


def test_pdf_two_columns_is_flagged():
    """A real two-column PDF => MEDIUM risk."""
    result = run_ats_check_bytes(pdf_two_columns(), "pdf", filename="cv.pdf")
    assert has_finding(result, "MULTIPLE_COLUMNS", "MEDIUM")


def test_pdf_single_column_is_not_flagged():
    """A real one-column PDF does not trigger the column detection."""
    result = run_ats_check_bytes(pdf_single_column(), "pdf", filename="cv.pdf")
    assert not has_finding(result, "MULTIPLE_COLUMNS")
    assert not has_finding(result, "READING_ORDER")


def test_docx_two_columns_is_flagged():
    """A DOCX declaring two columns => MEDIUM risk."""
    result = run_ats_check_bytes(docx_two_columns(), "docx", filename="cv.docx")
    assert has_finding(result, "MULTIPLE_COLUMNS", "MEDIUM")


def test_docx_clean_is_not_flagged():
    """A clean DOCX does not trigger the column detection."""
    result = run_ats_check_bytes(docx_clean(), "docx", filename="cv.docx")
    assert not has_finding(result, "MULTIPLE_COLUMNS")


# ──────────────────────────────────────────────────────────────────────
# Detector 5: Headers / Footers
# ──────────────────────────────────────────────────────────────────────

def test_detect_repeated_header():
    """A repeated header across the pages => LOW risk."""
    pages = [
        make_page(HEADER_FOOTER_PAGE_1, page_num=1),
        make_page(HEADER_FOOTER_PAGE_2, page_num=2),
        make_page(HEADER_FOOTER_PAGE_3, page_num=3),
    ]
    findings = detect_headers_footers(pages)
    assert len(findings) >= 1
    assert findings[0].code == "HEADER_FOOTER"
    assert findings[0].risk_level == "LOW"
    assert "En-tête" in findings[0].message or "Pied" in findings[0].message


def test_no_header_footer_single_page():
    """A single page does not trigger the header/footer detection."""
    assert detect_headers_footers([make_page(CLEAN_CV)]) == []


def test_pdf_with_repeated_header_is_flagged():
    """A real PDF repeating a header => LOW risk."""
    result = run_ats_check_bytes(pdf_repeated_header(), "pdf", filename="cv.pdf")
    assert has_finding(result, "HEADER_FOOTER", "LOW")


def test_docx_with_header_is_flagged():
    """A DOCX repeating a header => LOW risk."""
    result = run_ats_check_bytes(docx_with_header(), "docx", filename="cv.docx")
    assert has_finding(result, "HEADER_FOOTER", "LOW")


# ──────────────────────────────────────────────────────────────────────
# Detector 6: Decorative Characters
# ──────────────────────────────────────────────────────────────────────

def test_detect_decorative_chars():
    """Ligatures and decorative characters => LOW risk."""
    findings = detect_decorative_chars([make_page(DECORATIVE_CV)])
    assert len(findings) >= 1
    assert findings[0].code == "DECORATIVE_CHARS"
    assert findings[0].risk_level == "LOW"
    assert "ligatures" in findings[0].message or "décoratifs" in findings[0].message


def test_no_decorative_chars_clean():
    """A clean ASCII text does not trigger."""
    assert detect_decorative_chars([make_page(CLEAN_CV)]) == []


def test_docx_with_ligatures_is_flagged():
    """A real DOCX using ligatures => LOW risk."""
    result = run_ats_check_bytes(docx_decorative(), "docx", filename="cv.docx")
    assert has_finding(result, "DECORATIVE_CHARS", "LOW")


def test_pdf_with_decorative_chars_is_flagged():
    """A real PDF using bullets and dashes => LOW risk."""
    result = run_ats_check_bytes(pdf_decorative(), "pdf", filename="cv.pdf")
    assert has_finding(result, "DECORATIVE_CHARS", "LOW")


# ──────────────────────────────────────────────────────────────────────
# Detector 7: Unreadable Links
# ──────────────────────────────────────────────────────────────────────

def test_detect_unreadable_links_multiple():
    """Several raw URLs => LOW risk."""
    findings = detect_unreadable_links([make_page(URL_CV)])
    assert len(findings) >= 1
    assert findings[0].code == "UNREADABLE_LINKS"
    assert findings[0].risk_level == "LOW"


def test_detect_unreadable_links_long():
    """A single very long URL => LOW risk."""
    long_url = "https://example.com/very/long/url/path/that/exceeds/sixty/characters/easily"
    findings = detect_unreadable_links([make_page(f"Voir {long_url}")])
    assert len(findings) >= 1
    assert findings[0].code == "UNREADABLE_LINKS"


def test_no_unreadable_links_clean():
    """A short domain alone does not trigger."""
    findings = detect_unreadable_links([make_page("Site: example.com")])
    assert len(findings) == 0 or findings[0].risk_level == "LOW"


# ──────────────────────────────────────────────────────────────────────
# Detector 8: Missing Sections
# ──────────────────────────────────────────────────────────────────────

def test_detect_missing_sections_default():
    """The default expected sections are checked."""
    findings = detect_missing_sections([make_page(MISSING_SECTIONS_CV)], expected_sections=None)
    assert "MISSING_SECTION" in {f.code for f in findings}
    competences = [f for f in findings if "Compétences" in f.message]
    assert len(competences) >= 1
    assert competences[0].risk_level == "HIGH"


def test_detect_missing_sections_custom():
    """The expected sections can be customised."""
    findings = detect_missing_sections(
        [make_page(MISSING_SECTIONS_CV)],
        expected_sections=["Expérience", "Formation", "Compétences", "Projets"],
    )
    missing = {f.message.split("«")[1].split("»")[0].strip() for f in findings if f.code == "MISSING_SECTION"}
    assert "Compétences" in missing
    assert "Projets" in missing
    assert "Expérience" not in missing
    assert "Formation" not in missing


def test_no_missing_sections_complete():
    """A complete CV does not trigger the section detection."""
    findings = detect_missing_sections(
        [make_page(CLEAN_CV)],
        expected_sections=["Expérience", "Formation", "Compétences"],
    )
    assert findings == []


def test_pdf_missing_sections_is_flagged():
    """A real PDF without the expected sections => HIGH risk."""
    result = run_ats_check_bytes(
        pdf_missing_sections(),
        "pdf",
        filename="cv.pdf",
        expected_sections=["Expérience", "Formation", "Compétences", "Langues"],
    )
    missing = find_findings(result, "MISSING_SECTION")
    assert len(missing) >= 2
    assert all(f.risk_level == "HIGH" for f in missing)


def test_default_expected_sections_are_documented():
    """The default expected sections are Expérience, Formation, Compétences."""
    assert DEFAULT_EXPECTED_SECTIONS == ["Expérience", "Formation", "Compétences"]


# ──────────────────────────────────────────────────────────────────────
# Detector 9: Parse Errors
# ──────────────────────────────────────────────────────────────────────

def test_detect_parse_error_encrypted():
    """An encrypted PDF error => HIGH risk."""
    findings = detect_parse_errors(["PDF is encrypted/password-protected"])
    assert len(findings) == 1
    assert findings[0].code == "PARSE_ERROR"
    assert findings[0].risk_level == "HIGH"
    assert findings[0].error == "PARSE_ERROR"
    assert "chiffré" in findings[0].message or "mot de passe" in findings[0].message


def test_detect_parse_error_corrupt():
    """A corrupt file error => HIGH risk."""
    findings = detect_parse_errors(["DOCX parsing failed: corrupt file"])
    assert len(findings) == 1
    assert findings[0].code == "PARSE_ERROR"
    assert findings[0].risk_level == "HIGH"
    assert "corrompu" in findings[0].message or "malformé" in findings[0].message


def test_detect_parse_error_generic():
    """A generic parse error => HIGH risk."""
    findings = detect_parse_errors(["PDF parsing failed: unknown error"])
    assert len(findings) == 1
    assert findings[0].code == "PARSE_ERROR"


def test_encrypted_pdf_gives_a_parse_error_only():
    """A real encrypted PDF => HIGH risk, no other (meaningless) finding."""
    result = run_ats_check_bytes(pdf_encrypted(), "pdf", filename="cv.pdf")
    assert result.parse_errors
    assert len(find_findings(result, "PARSE_ERROR")) == 1
    assert result.findings[0].risk_level == "HIGH"
    assert result.pages_analyzed == 0
    # No bogus "missing section" noise on an unreadable document.
    assert find_findings(result, "MISSING_SECTION") == []


def test_corrupt_pdf_gives_a_parse_error_only():
    """A real corrupt PDF => HIGH risk, no crash."""
    result = run_ats_check_bytes(pdf_corrupt(), "pdf", filename="cv.pdf")
    assert result.parse_errors
    assert len(find_findings(result, "PARSE_ERROR")) == 1
    assert result.findings[0].risk_level == "HIGH"
    assert find_findings(result, "MISSING_SECTION") == []


def test_corrupt_docx_gives_a_parse_error():
    """A corrupt DOCX => HIGH risk, no crash."""
    result = run_ats_check_bytes(b"PK\x03\x04broken docx body", "docx", filename="cv.docx")
    assert result.parse_errors
    assert has_finding(result, "PARSE_ERROR", "HIGH")


# ──────────────────────────────────────────────────────────────────────
# Scoring, labels and interpretation
# ──────────────────────────────────────────────────────────────────────

def test_risk_score_calculation():
    """The weighted score sums the weights of the findings."""
    findings = [
        ATSFindingModel(code="A", risk_level="LOW", message="", page=1, bbox=None, evidence_excerpt=""),
        ATSFindingModel(code="B", risk_level="LOW", message="", page=1, bbox=None, evidence_excerpt=""),
        ATSFindingModel(code="C", risk_level="MEDIUM", message="", page=1, bbox=None, evidence_excerpt=""),
        ATSFindingModel(code="D", risk_level="HIGH", message="", page=1, bbox=None, evidence_excerpt=""),
    ]
    # LOW=5*2=10, MEDIUM=20, HIGH=50 -> 80
    assert _calculate_risk_score(findings) == 80


def test_risk_score_cap_at_100():
    """The score is capped at 100."""
    findings = [
        ATSFindingModel(code=f"H{i}", risk_level="HIGH", message="", page=1, bbox=None, evidence_excerpt="")
        for i in range(5)
    ]
    assert _calculate_risk_score(findings) == 100


def test_risk_label_low():
    """A score below 20 => LOW."""
    assert _calculate_risk_label(0) == "LOW"
    assert _calculate_risk_label(5) == "LOW"
    assert _calculate_risk_label(15) == "LOW"


def test_risk_label_medium():
    """A score between 20 and 49 => MEDIUM."""
    assert _calculate_risk_label(20) == "MEDIUM"
    assert _calculate_risk_label(40) == "MEDIUM"
    assert _calculate_risk_label(49) == "MEDIUM"


def test_risk_label_high():
    """A score of 50 or more => HIGH (one HIGH finding is enough)."""
    assert _calculate_risk_label(50) == "HIGH"
    assert _calculate_risk_label(80) == "HIGH"
    assert _calculate_risk_label(100) == "HIGH"


def test_risk_interpretations_are_prudent():
    """The labels are translated into a prudent interpretation."""
    assert risk_interpretation("LOW") == "Faible risque"
    assert risk_interpretation("MEDIUM") == "Risque modéré — relecture conseillée"
    assert risk_interpretation("HIGH") == "Risque élevé — restructuration recommandée"
    assert set(RISK_INTERPRETATIONS) == {"LOW", "MEDIUM", "HIGH"}
    # The wording never promises a rejection.
    for text in RISK_INTERPRETATIONS.values():
        assert "rejet" not in text.lower()


def test_result_carries_the_interpretation():
    """The result exposes the interpretation of its label."""
    result = run_ats_check(make_doc(CLEAN_CV, filetype="pdf"))
    assert result.risk_interpretation == RISK_INTERPRETATIONS[result.risk_label]


# ──────────────────────────────────────────────────────────────────────
# Integration: run_ats_check
# ──────────────────────────────────────────────────────────────────────

def test_run_ats_check_clean_cv():
    """A clean CV => a low score and a LOW label."""
    result = run_ats_check(make_doc(CLEAN_CV, filetype="pdf"))
    assert isinstance(result, ATSCheckResult)
    assert result.risk_score <= 15
    assert result.risk_label == "LOW"
    assert result.pages_analyzed >= 1
    assert result.parse_errors == []


def test_run_ats_check_two_column_pdf():
    """A two-column CV => MEDIUM or HIGH."""
    result = run_ats_check(make_doc(TWO_COLUMN_CV, filetype="pdf"))
    assert result.risk_score > 15
    assert result.risk_label in ("MEDIUM", "HIGH")
    codes = {f.code for f in result.findings}
    assert "READING_ORDER" in codes or "MULTIPLE_COLUMNS" in codes


def test_run_ats_check_table_pdf():
    """A CV with a table => a MEDIUM finding."""
    result = run_ats_check(make_doc(TABLE_CV, filetype="pdf"))
    assert has_finding(result, "NESTED_TABLE", "MEDIUM")


def test_run_ats_check_decorative_chars():
    """A CV with ligatures => a LOW finding."""
    result = run_ats_check(make_doc(DECORATIVE_CV, filetype="pdf"))
    assert has_finding(result, "DECORATIVE_CHARS", "LOW")


def test_run_ats_check_unreadable_links():
    """A CV with raw URLs => a LOW finding."""
    result = run_ats_check(make_doc(URL_CV, filetype="pdf"))
    assert has_finding(result, "UNREADABLE_LINKS", "LOW")


def test_run_ats_check_missing_sections():
    """A CV missing sections => HIGH findings."""
    result = run_ats_check(
        make_doc(MISSING_SECTIONS_CV, filetype="pdf"),
        expected_sections=["Expérience", "Formation", "Compétences", "Langues"],
    )
    missing = find_findings(result, "MISSING_SECTION")
    assert len(missing) >= 2
    assert all(f.risk_level == "HIGH" for f in missing)
    assert result.risk_label == "HIGH"


def test_run_ats_check_docx():
    """The DOCX file type is handled."""
    result = run_ats_check(make_doc(CLEAN_CV, filetype="docx"))
    assert isinstance(result, ATSCheckResult)
    assert result.pages_analyzed >= 1


def test_run_ats_check_txt():
    """The TXT file type is handled."""
    result = run_ats_check(make_doc(CLEAN_CV, filetype="txt"))
    assert isinstance(result, ATSCheckResult)
    assert result.pages_analyzed >= 1


def test_run_ats_check_combined_issues():
    """A CV with several issues => a combined HIGH score."""
    combined = TABLE_CV + "\n" + DECORATIVE_CV + "\n" + URL_CV + "\n" + MISSING_SECTIONS_CV
    result = run_ats_check(
        make_doc(combined, filetype="pdf"),
        expected_sections=["Expérience", "Formation", "Compétences", "Langues", "Projets"],
    )
    codes = {f.code for f in result.findings}
    assert "NESTED_TABLE" in codes
    assert "DECORATIVE_CHARS" in codes
    assert "UNREADABLE_LINKS" in codes
    assert "MISSING_SECTION" in codes
    assert result.risk_label == "HIGH"
    assert result.risk_score > 60


def test_run_ats_check_uses_the_raw_bytes_of_the_document():
    """The raw bytes carried by the DocumentInput enable the structural analysis."""
    document = DocumentInput(
        text="",
        filename="cv.pdf",
        filetype="pdf",
        page_count=1,
        raw_bytes=pdf_two_columns(),
    )
    result = run_ats_check(document)
    assert has_finding(result, "MULTIPLE_COLUMNS", "MEDIUM")


def test_run_ats_check_file(tmp_path):
    """The file helper reads the document from the disk."""
    path = tmp_path / "cv.pdf"
    path.write_bytes(pdf_two_columns())
    result = run_ats_check_file(str(path))
    assert has_finding(result, "MULTIPLE_COLUMNS", "MEDIUM")


def test_run_ats_check_file_rejects_unknown_extension(tmp_path):
    """An unsupported extension is refused."""
    path = tmp_path / "cv.rtf"
    path.write_bytes(b"whatever")
    with pytest.raises(ValueError):
        run_ats_check_file(str(path))


def test_run_ats_check_file_missing(tmp_path):
    """A missing file is refused."""
    with pytest.raises(FileNotFoundError):
        run_ats_check_file(str(tmp_path / "absent.pdf"))


def test_ats_finding_fields():
    """Every ATSFinding carries the required fields."""
    result = run_ats_check(make_doc(CLEAN_CV, filetype="pdf"))
    for finding in result.findings:
        assert finding.code
        assert finding.risk_level in ("LOW", "MEDIUM", "HIGH")
        assert finding.message
        assert finding.page >= 0
        assert finding.evidence_excerpt
        assert len(finding.evidence_excerpt) <= 120


def test_ats_check_result_fields():
    """The ATSCheckResult carries the required fields."""
    result = run_ats_check(make_doc(CLEAN_CV, filetype="pdf"))
    assert isinstance(result.findings, list)
    assert isinstance(result.risk_score, int)
    assert 0 <= result.risk_score <= 100
    assert result.risk_label in ("LOW", "MEDIUM", "HIGH")
    assert isinstance(result.pages_analyzed, int)
    assert result.pages_analyzed >= 1
    assert isinstance(result.parse_errors, list)
    assert isinstance(result.risk_interpretation, str)
    assert result.risk_interpretation


# ──────────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────────

def test_empty_document():
    """An empty document => HIGH risk."""
    result = run_ats_check(make_doc("", filetype="txt"), expected_sections=["Expérience", "Formation"])
    assert result.risk_label == "HIGH"
    assert len(find_findings(result, "MISSING_SECTION")) == 2


def test_whitespace_only():
    """A whitespace-only document => a HIGH finding."""
    result = run_ats_check(make_doc("   \n\n   \t\t   \n   ", filetype="txt"), expected_sections=["Expérience"])
    assert has_finding(result, "MISSING_SECTION", "HIGH")
    assert result.risk_label == "HIGH"


def test_deterministic_results():
    """The same input always produces the same result."""
    document = make_doc(CLEAN_CV, filetype="pdf")
    first = run_ats_check(document)
    second = run_ats_check(document)
    assert first.risk_score == second.risk_score
    assert first.risk_label == second.risk_label
    assert len(first.findings) == len(second.findings)
    for one, two in zip(first.findings, second.findings):
        assert one.code == two.code
        assert one.risk_level == two.risk_level
        assert one.page == two.page


def test_deterministic_results_on_real_pdf():
    """The analysis of a real PDF is deterministic."""
    data = pdf_two_columns()
    first = run_ats_check_bytes(data, "pdf", filename="cv.pdf")
    second = run_ats_check_bytes(data, "pdf", filename="cv.pdf")
    assert first.risk_score == second.risk_score
    assert [f.code for f in first.findings] == [f.code for f in second.findings]


def test_no_network_access():
    """The analysis never opens a socket."""
    import socket

    original = socket.socket

    class Guarded(original):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            raise AssertionError("the ATS analysis must not open a socket")

    socket.socket = Guarded  # type: ignore[misc]
    try:
        result = run_ats_check_bytes(pdf_single_column(), "pdf", filename="cv.pdf")
    finally:
        socket.socket = original  # type: ignore[misc]
    assert isinstance(result, ATSCheckResult)


def test_performance_under_3_seconds():
    """The analysis stays under 3 s for a five-page PDF."""
    data = pdf_repeated_header()
    start = time.perf_counter()
    result = run_ats_check_bytes(data, "pdf", filename="cv.pdf")
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0, f"the ATS check took {elapsed:.2f}s, expected < 3s"
    assert result.pages_analyzed >= 1


def test_performance_text_under_3_seconds():
    """The analysis stays under 3 s on a three-page text."""
    document = make_doc(CLEAN_CV * 3, filetype="pdf")
    start = time.perf_counter()
    result = run_ats_check(document)
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0, f"the ATS check took {elapsed:.2f}s, expected < 3s"
    assert result.pages_analyzed >= 1
