"""Focused ingestion contract tests required by the NAGe learning mission."""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from career.ingest import CorpusIndex


def test_pdf_ingest_exposes_page_and_section_provenance(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    path = corpus / "topic-3.pdf"
    document = canvas.Canvas(str(path), pagesize=A4)
    document.drawString(60, 780, "TOPIC 3 — VALUATION")
    document.drawString(60, 750, "Post-money equals pre-money plus investment.")
    document.save()
    index = CorpusIndex(tmp_path / "index.sqlite3", corpus_root=corpus)
    report = index.ingest_directory()
    hit = index.search("post-money investment")[0]
    assert report.documents == 1
    assert hit.page_start == 1
    assert "TOPIC 3" in hit.section
    assert hit.citation()["source"] == "topic-3.pdf"
