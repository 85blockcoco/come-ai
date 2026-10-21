"""Tests unitaires du contrôle ATS local (Mission 04).

Toutes les fixtures sont **synthétiques** (PDF générés avec reportlab, DOCX
générés avec python-docx, texte brut) : aucun CV réel, aucun appel réseau.

Couverture : les 9 détecteurs, le score pondéré, le label, les erreurs de
parsing (fichier chiffré / corrompu) et les combinaisons.
"""

from __future__ import annotations

import io
import struct
import time
import zlib

import pytest

from career.cv_quality import (
    ATSCheckResult,
    ATSFinding,
    DocumentInput,
    run_ats_check,
    run_ats_check_bytes,
    run_ats_check_file,
)
from career.cv_quality.ats import (
    RISK_WEIGHTS,
    PageContent,
    TextChunk,
    risk_interpretation,
)

reportlab = pytest.importorskip("reportlab")
docx = pytest.importorskip("docx")

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.utils import ImageReader  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402


# ──────────────────────────────────────────────────────────────────────
# Helpers — fixtures synthétiques
# ──────────────────────────────────────────────────────────────────────

CLEAN_LINES = [
    "Jean Dupont",
    "jean.dupont@email.fr",
    "+33 6 12 34 56 78",
    "Expérience",
    "2020-2023 | Développeur Python | TechCorp",
    "Migration de 5 services vers Kubernetes",
    "2018-2020 | Développeur Junior | StartupInc",
    "Formation",
    "2018-2020 | Master Informatique | Universite Paris-Saclay",
    "Compétences",
    "Python, SQL, Docker, Kubernetes, React, AWS",
    "Langues",
    "Français (natif), Anglais (courant)",
]


def _pdf_bytes(draw) -> bytes:
    """Build a PDF from a drawing callback."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    draw(pdf)
    pdf.save()
    return buffer.getvalue()


def _png_bytes(width: int = 8, height: int = 8) -> bytes:
    """Minimal solid grey PNG built without any image library."""
    raw = b"".join(b"\x00" + bytes((200, 200, 200)) * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        payload = kind + data
        return (
            struct.pack(">I", len(data))
            + payload
            + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _clean_pdf() -> bytes:
    def draw(pdf: canvas.Canvas) -> None:
        y = 780.0
        pdf.setFont("Helvetica", 14)
        pdf.drawString(60, y, "Jean Dupont")
        y -= 30
        pdf.setFont("Helvetica", 11)
        for line in CLEAN_LINES:
            pdf.drawString(60, y, line)
            y -= 16

    return _pdf_bytes(draw)


def _two_column_pdf() -> bytes:
    def draw(pdf: canvas.Canvas) -> None:
        pdf.setFont("Helvetica", 10)
        for index in range(8):
            pdf.drawString(60, 760 - index * 18, f"Experience line {index}")
            pdf.drawString(330, 751 - index * 18, f"Formation line {index}")
        pdf.drawString(60, 600, "Competences line")

    return _pdf_bytes(draw)


def _table_pdf() -> bytes:
    def draw(pdf: canvas.Canvas) -> None:
        pdf.setFont("Helvetica", 10)
        for row in range(4):
            for col in range(3):
                pdf.drawString(60 + col * 150, 700 - row * 20, f"Cell {row}{col}")

    return _pdf_bytes(draw)


def _image_only_pdf() -> bytes:
    def draw(pdf: canvas.Canvas) -> None:
        pdf.drawImage(ImageReader(io.BytesIO(_png_bytes())), 0, 0, width=A4[0], height=A4[1])

    return _pdf_bytes(draw)


def _header_footer_pdf() -> bytes:
    def draw(pdf: canvas.Canvas) -> None:
        for _ in range(2):
            pdf.setFont("Helvetica", 9)
            pdf.drawString(60, 800, "CV - Jean Dupont")
            pdf.drawString(60, 42, "Document confidentiel")
            pdf.setFont("Helvetica", 11)
            pdf.drawString(60, 700, "Experience")
            pdf.drawString(60, 660, "Formation")
            pdf.drawString(60, 620, "Competences")
            pdf.showPage()

    return _pdf_bytes(draw)


def _multi_page_pdf(pages: int = 5) -> bytes:
    def draw(pdf: canvas.Canvas) -> None:
        for _ in range(pages):
            pdf.setFont("Helvetica", 11)
            for index in range(20):
                pdf.drawString(60, 760 - index * 18, f"Experience line {index}")
            pdf.showPage()

    return _pdf_bytes(draw)


def _encrypted_pdf() -> bytes:
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(_clean_pdf()))
    for algorithm in ("AES-256", "AES-128", "RC4-128", "RC4-40"):
        writer = pypdf.PdfWriter()
        writer.clone_document_from_reader(reader)
        try:
            writer.encrypt("motdepasse", algorithm=algorithm)
        except Exception:
            continue
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()
    raise RuntimeError("pypdf ne sait pas chiffrer la fixture PDF")


def _docx_bytes(build) -> bytes:
    document = docx.Document()
    build(document)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _clean_docx() -> bytes:
    def build(document) -> None:
        document.add_paragraph("Jean Dupont")
        document.add_paragraph("jean.dupont@email.fr")
        document.add_paragraph("Expérience")
        document.add_paragraph("2020-2023 | Développeur Python | TechCorp")
        document.add_paragraph("Formation")
        document.add_paragraph("2018-2020 | Master Informatique | Université Paris-Saclay")
        document.add_paragraph("Compétences")
        document.add_paragraph("Python, SQL, Docker, Kubernetes")

    return _docx_bytes(build)


def _two_column_docx() -> bytes:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    def build(document) -> None:
        section = document.sections[0]
        cols = OxmlElement("w:cols")
        cols.set(qn("w:num"), "2")
        section._sectPr.append(cols)  # noqa: SLF001 - no public accessor
        document.add_paragraph("Jean Dupont")
        document.add_paragraph("Expérience")
        document.add_paragraph("Formation")
        document.add_paragraph("Compétences")

    return _docx_bytes(build)


def _nested_table_docx() -> bytes:
    def build(document) -> None:
        document.add_paragraph("Jean Dupont")
        document.add_paragraph("Expérience")
        document.add_paragraph("Formation")
        document.add_paragraph("Compétences")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Poste"
        table.cell(0, 1).text = "Entreprise"
        table.cell(1, 0).text = "Details"
        nested = table.cell(1, 1).add_table(rows=1, cols=2)
        nested.cell(0, 0).text = "Python"
        nested.cell(0, 1).text = "SQL"

    return _docx_bytes(build)


def _header_docx() -> bytes:
    def build(document) -> None:
        section = document.sections[0]
        section.header.paragraphs[0].text = "Jean Dupont - CV confidentiel"
        document.add_paragraph("Jean Dupont")
        document.add_paragraph("Expérience")
        document.add_paragraph("Formation")
        document.add_paragraph("Compétences")

    return _docx_bytes(build)


def _decorative_docx() -> bytes:
    def build(document) -> None:
        document.add_paragraph("Jean Dupont")
        document.add_paragraph("Expérience")
        document.add_paragraph("● Développeur Python ﬁ TechCorp")
        document.add_paragraph("Formation")
        document.add_paragraph("Compétences")

    return _docx_bytes(build)


def _url_docx() -> bytes:
    def build(document) -> None:
        document.add_paragraph("Jean Dupont")
        document.add_paragraph("Expérience")
        document.add_paragraph("https://github.com/jeandupont/projet")
        document.add_paragraph("Formation")
        document.add_paragraph("Compétences")

    return _docx_bytes(build)


def _missing_section_docx() -> bytes:
    def build(document) -> None:
        document.add_paragraph("Jean Dupont")
        document.add_paragraph("Expérience")
        document.add_paragraph("Technicien de maintenance")

    return _docx_bytes(build)


CLEAN_TXT = """Jean Dupont
jean.dupont@email.fr

Expérience
2020-2023 | Développeur Python | TechCorp
Formation
2018-2020 | Master Informatique | Universite Paris-Saclay
Compétences
Python, SQL, Docker
"""


def _codes(result: ATSCheckResult) -> set[str]:
    return {finding.code for finding in result.findings}


def _findings(result: ATSCheckResult, code: str) -> list[ATSFinding]:
    return [finding for finding in result.findings if finding.code == code]


# ──────────────────────────────────────────────────────────────────────
# 1. PDF une colonne propre
# ──────────────────────────────────────────────────────────────────────

def test_clean_pdf_has_no_high_risk():
    result = run_ats_check_bytes(_clean_pdf(), "pdf")
    high = [f for f in result.findings if f.risk_level == "HIGH"]
    assert high == [], high
    assert result.risk_label in ("LOW", "MEDIUM")
    assert result.pages_analyzed == 1
    assert result.parse_errors == []


def test_clean_pdf_sections_are_detected():
    result = run_ats_check_bytes(_clean_pdf(), "pdf")
    assert "MISSING_SECTION" not in _codes(result)


def test_clean_pdf_reading_order_is_linear():
    result = run_ats_check_bytes(_clean_pdf(), "pdf")
    assert "READING_ORDER" not in _codes(result)


def test_clean_pdf_is_not_multi_column():
    result = run_ats_check_bytes(_clean_pdf(), "pdf")
    assert "MULTIPLE_COLUMNS" not in _codes(result)


# ──────────────────────────────────────────────────────────────────────
# 2. PDF deux colonnes
# ──────────────────────────────────────────────────────────────────────

def test_two_column_pdf_detected():
    result = run_ats_check_bytes(_two_column_pdf(), "pdf")
    findings = _findings(result, "MULTIPLE_COLUMNS")
    assert findings, _codes(result)
    assert findings[0].risk_level == "MEDIUM"
    assert findings[0].page == 1
    assert findings[0].evidence_excerpt


def test_two_column_pdf_is_not_reported_as_a_table():
    result = run_ats_check_bytes(_two_column_pdf(), "pdf")
    assert "NESTED_TABLE" not in _codes(result)


# ──────────────────────────────────────────────────────────────────────
# 3. PDF avec tableau
# ──────────────────────────────────────────────────────────────────────

def test_table_pdf_detected():
    result = run_ats_check_bytes(_table_pdf(), "pdf")
    findings = _findings(result, "NESTED_TABLE")
    assert findings, _codes(result)
    assert findings[0].risk_level == "MEDIUM"
    assert "lignes" in findings[0].evidence_excerpt or "colonnes" in findings[0].evidence_excerpt


def test_table_pdf_breaks_reading_order():
    result = run_ats_check_bytes(_table_pdf(), "pdf")
    assert "READING_ORDER" in _codes(result)


# ──────────────────────────────────────────────────────────────────────
# 4. PDF image seule
# ──────────────────────────────────────────────────────────────────────

def test_image_only_pdf_detected():
    result = run_ats_check_bytes(_image_only_pdf(), "pdf")
    findings = _findings(result, "TEXT_IN_IMAGES")
    assert findings, _codes(result)
    assert findings[0].risk_level == "HIGH"
    assert findings[0].bbox is not None


def test_image_only_pdf_is_high_risk():
    result = run_ats_check_bytes(_image_only_pdf(), "pdf")
    assert result.risk_label == "HIGH"
    assert result.risk_interpretation == "Risque élevé — restructuration recommandée"


# ──────────────────────────────────────────────────────────────────────
# 5. PDF chiffré + PDF corrompu
# ──────────────────────────────────────────────────────────────────────

def test_encrypted_pdf_reports_parse_error():
    result = run_ats_check_bytes(_encrypted_pdf(), "pdf")
    findings = _findings(result, "PARSE_ERROR")
    assert findings, _codes(result)
    assert findings[0].risk_level == "HIGH"
    assert findings[0].error == "PARSE_ERROR"
    assert result.parse_errors
    assert result.risk_label == "HIGH"


def test_corrupt_pdf_reports_parse_error():
    result = run_ats_check_bytes(b"%PDF-1.4 ceci n'est pas un pdf", "pdf")
    findings = _findings(result, "PARSE_ERROR")
    assert findings, _codes(result)
    assert findings[0].risk_level == "HIGH"
    assert findings[0].error == "PARSE_ERROR"


# ──────────────────────────────────────────────────────────────────────
# 6. DOCX propre
# ──────────────────────────────────────────────────────────────────────

def test_clean_docx_has_no_high_risk():
    result = run_ats_check_bytes(_clean_docx(), "docx")
    high = [f for f in result.findings if f.risk_level == "HIGH"]
    assert high == [], high
    assert result.pages_analyzed == 1


def test_clean_docx_sections_are_detected():
    result = run_ats_check_bytes(_clean_docx(), "docx")
    assert "MISSING_SECTION" not in _codes(result)


# ──────────────────────────────────────────────────────────────────────
# 7. DOCX avec colonnes
# ──────────────────────────────────────────────────────────────────────

def test_two_column_docx_detected():
    result = run_ats_check_bytes(_two_column_docx(), "docx")
    findings = _findings(result, "MULTIPLE_COLUMNS")
    assert findings, _codes(result)
    assert findings[0].risk_level == "MEDIUM"
    assert "2 colonnes" in findings[0].message


# ──────────────────────────────────────────────────────────────────────
# 8. DOCX avec tableau imbriqué
# ──────────────────────────────────────────────────────────────────────

def test_nested_table_docx_detected():
    result = run_ats_check_bytes(_nested_table_docx(), "docx")
    findings = _findings(result, "NESTED_TABLE")
    assert findings, _codes(result)
    assert findings[0].risk_level == "MEDIUM"
    assert "imbriqué" in findings[0].message


# ──────────────────────────────────────────────────────────────────────
# 9. DOCX corrompu
# ──────────────────────────────────────────────────────────────────────

def test_corrupt_docx_reports_parse_error():
    result = run_ats_check_bytes(b"PK\x03\x04 ceci n'est pas un docx", "docx")
    findings = _findings(result, "PARSE_ERROR")
    assert findings, _codes(result)
    assert findings[0].risk_level == "HIGH"
    assert findings[0].error == "PARSE_ERROR"


# ──────────────────────────────────────────────────────────────────────
# 10. En-têtes / pieds de page
# ──────────────────────────────────────────────────────────────────────

def test_repeated_header_and_footer_pdf_detected():
    result = run_ats_check_bytes(_header_footer_pdf(), "pdf")
    findings = _findings(result, "HEADER_FOOTER")
    assert len(findings) >= 2, _codes(result)
    assert all(f.risk_level == "LOW" for f in findings)
    assert result.pages_analyzed == 2


def test_docx_header_detected():
    result = run_ats_check_bytes(_header_docx(), "docx")
    findings = _findings(result, "HEADER_FOOTER")
    assert findings, _codes(result)
    assert findings[0].risk_level == "LOW"


def test_clean_pdf_has_no_header_footer_finding():
    result = run_ats_check_bytes(_clean_pdf(), "pdf")
    assert "HEADER_FOOTER" not in _codes(result)


# ──────────────────────────────────────────────────────────────────────
# 11. Caractères décoratifs
# ──────────────────────────────────────────────────────────────────────

def test_decorative_chars_detected():
    result = run_ats_check_bytes(_decorative_docx(), "docx")
    findings = _findings(result, "DECORATIVE_CHARS")
    assert findings, _codes(result)
    assert findings[0].risk_level == "LOW"
    assert "●" in findings[0].evidence_excerpt


def test_clean_docx_has_no_decorative_chars():
    result = run_ats_check_bytes(_clean_docx(), "docx")
    assert "DECORATIVE_CHARS" not in _codes(result)


# ──────────────────────────────────────────────────────────────────────
# 12. Liens peu lisibles
# ──────────────────────────────────────────────────────────────────────

def test_raw_url_detected():
    result = run_ats_check_bytes(_url_docx(), "docx")
    findings = _findings(result, "UNREADABLE_LINKS")
    assert findings, _codes(result)
    assert findings[0].risk_level == "LOW"
    assert "github.com" in findings[0].evidence_excerpt


def test_clean_docx_has_no_unreadable_links():
    result = run_ats_check_bytes(_clean_docx(), "docx")
    assert "UNREADABLE_LINKS" not in _codes(result)


# ──────────────────────────────────────────────────────────────────────
# 13. Sections introuvables
# ──────────────────────────────────────────────────────────────────────

def test_missing_section_detected():
    result = run_ats_check_bytes(_missing_section_docx(), "docx")
    findings = _findings(result, "MISSING_SECTION")
    assert findings, _codes(result)
    assert findings[0].risk_level == "HIGH"
    assert "Formation" in findings[0].message


def test_custom_expected_sections():
    result = run_ats_check_bytes(_clean_docx(), "docx", expected_sections=["Projets"])
    findings = _findings(result, "MISSING_SECTION")
    assert findings, _codes(result)
    assert "Projets" in findings[0].message


def test_keyword_search_does_not_match_inside_a_word():
    """'information' must not be read as the section 'formation'."""
    text = "Informations complementaires\nRencontre annuelle"
    result = run_ats_check(DocumentInput(text=text, filename="cv.txt", filetype="txt"))
    findings = _findings(result, "MISSING_SECTION")
    messages = " ".join(f.message for f in findings)
    assert "Formation" in messages


# ──────────────────────────────────────────────────────────────────────
# 14. Score, label, interprétation
# ──────────────────────────────────────────────────────────────────────

def test_risk_weights():
    assert RISK_WEIGHTS == {"LOW": 5, "MEDIUM": 20, "HIGH": 50}


def test_score_is_weighted_and_capped():
    result = run_ats_check_bytes(_image_only_pdf(), "pdf")
    expected = min(100, sum(RISK_WEIGHTS[f.risk_level] for f in result.findings))
    assert result.risk_score == expected
    assert 0 <= result.risk_score <= 100


def test_risk_interpretations():
    assert risk_interpretation("LOW") == "Faible risque"
    assert risk_interpretation("MEDIUM") == "Risque modéré — relecture conseillée"
    assert risk_interpretation("HIGH") == "Risque élevé — restructuration recommandée"


def test_result_exposes_its_interpretation():
    result = run_ats_check_bytes(_clean_pdf(), "pdf")
    assert result.risk_interpretation == risk_interpretation(result.risk_label)


# ──────────────────────────────────────────────────────────────────────
# 15. Contrat de l'API
# ──────────────────────────────────────────────────────────────────────

def test_every_finding_is_complete():
    result = run_ats_check_bytes(_table_pdf(), "pdf")
    assert result.findings
    for finding in result.findings:
        assert finding.code
        assert finding.risk_level in ("LOW", "MEDIUM", "HIGH")
        assert finding.message
        assert isinstance(finding.page, int)
        assert finding.evidence_excerpt
        if finding.bbox is not None:
            assert len(finding.bbox) == 4


def test_run_ats_check_accepts_a_document_input():
    document = DocumentInput(text=CLEAN_TXT, filename="cv.txt", filetype="txt", page_count=1)
    result = run_ats_check(document)
    assert result.pages_analyzed == 1
    assert "MISSING_SECTION" not in _codes(result)


def test_run_ats_check_uses_the_bytes_kept_by_the_parser(tmp_path):
    """The parser keeps the raw bytes: the real layout is then inspected."""
    from career.cv_quality.parser import extract_text_from_file

    path = tmp_path / "cv.pdf"
    path.write_bytes(_two_column_pdf())
    document = extract_text_from_file(path)
    result = run_ats_check(document)
    assert "MULTIPLE_COLUMNS" in _codes(result)


def test_run_ats_check_file(tmp_path):
    path = tmp_path / "cv.pdf"
    path.write_bytes(_clean_pdf())
    result = run_ats_check_file(path)
    assert result.pages_analyzed == 1
    assert result.parse_errors == []


def test_run_ats_check_file_rejects_unknown_extension(tmp_path):
    path = tmp_path / "cv.rtf"
    path.write_bytes(b"rtf")
    with pytest.raises(ValueError):
        run_ats_check_file(path)


def test_results_are_deterministic():
    data = _two_column_pdf()
    first = run_ats_check_bytes(data, "pdf")
    second = run_ats_check_bytes(data, "pdf")
    assert first == second


def test_analysis_is_local_only():
    """No socket is opened during the analysis."""
    import socket

    original = socket.socket

    def forbidden(*args, **kwargs):
        raise AssertionError("le contrôle ATS ne doit pas ouvrir de connexion réseau")

    socket.socket = forbidden  # type: ignore[assignment]
    try:
        run_ats_check_bytes(_clean_pdf(), "pdf")
        run_ats_check_bytes(_clean_docx(), "docx")
    finally:
        socket.socket = original  # type: ignore[assignment]


def test_performance_under_three_seconds():
    data = _multi_page_pdf(5)
    start = time.perf_counter()
    result = run_ats_check_bytes(data, "pdf")
    duration = time.perf_counter() - start
    assert result.pages_analyzed == 5
    assert duration < 3.0, f"{duration:.2f}s"


# ──────────────────────────────────────────────────────────────────────
# 16. Détecteurs unitaires (PageContent synthétiques)
# ──────────────────────────────────────────────────────────────────────

def _page(**kwargs) -> PageContent:
    base = {"page_num": 1, "text": ""}
    base.update(kwargs)
    return PageContent(**base)


def test_detect_reading_order_on_positioned_chunks():
    from career.cv_quality.ats import detect_reading_order

    chunks = [
        TextChunk(text="ligne 1", x=50, y=800, size=10),
        TextChunk(text="ligne 2", x=350, y=700, size=10),
        TextChunk(text="ligne 3", x=50, y=800, size=10),
        TextChunk(text="ligne 4", x=350, y=700, size=10),
        TextChunk(text="ligne 5", x=50, y=800, size=10),
        TextChunk(text="ligne 6", x=350, y=700, size=10),
        TextChunk(text="ligne 7", x=50, y=800, size=10),
    ]
    findings = detect_reading_order([_page(chunks=tuple(chunks))])
    assert findings
    assert findings[0].code == "READING_ORDER"


def test_detect_text_in_images_needs_an_image():
    from career.cv_quality.ats import detect_text_in_images

    assert detect_text_in_images([_page(text=" beaucoup de texte " * 10)]) == []
    findings = detect_text_in_images([_page(text="", images=((0.0, 0.0, 595.0, 842.0),))])
    assert findings
    assert findings[0].risk_level == "HIGH"


def test_detect_decorative_chars_is_sorted_and_stable():
    from career.cv_quality.ats import detect_decorative_chars

    findings = detect_decorative_chars([_page(text="● ◆ ﬁ")])
    assert len(findings) == 1
    # The excerpt is sorted by code point so that the output stays deterministic.
    assert findings[0].evidence_excerpt == "◆ ● ﬁ"


def test_detect_parse_errors_flags_the_error_code():
    from career.cv_quality.ats import detect_parse_errors

    findings = detect_parse_errors(["PARSE_ERROR: PDF chiffré — extraction impossible"])
    assert findings[0].error == "PARSE_ERROR"
    assert findings[0].risk_level == "HIGH"
