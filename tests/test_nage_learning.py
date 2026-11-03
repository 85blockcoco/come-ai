from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from career.exam import ExamEngine
from career.ingest import CorpusIndex
from career.learning_router import create_learning_router
from career.plan import build_plan
from career.quiz import QuizEngine
from career.srs import SRSStore
from career.summary import build_summary, export_summary_pdf
from career.tutor import TutorEngine


def _pdf(path: Path) -> None:
    document = canvas.Canvas(str(path), pagesize=A4)
    document.drawString(60, 780, "TOPIC 3 — Valorisation, ownership, returns")
    document.drawString(60, 750, "Post-money equals pre-money plus investment. Ownership VC equals investment divided by post-money.")
    document.drawString(60, 720, "MOIC is exit value divided by invested capital.")
    document.showPage()
    document.drawString(60, 780, "TOPIC 4 — Term sheets")
    document.drawString(60, 750, "A term sheet describes valuation, governance and liquidation preference.")
    document.save()


def test_ingestion_preserves_page_section_and_local_manifest(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _pdf(corpus / "vc-course.pdf")
    index = CorpusIndex(tmp_path / "index", corpus_root=corpus)
    report = index.ingest_directory()
    assert report.documents == 1
    assert report.pages == 2
    assert report.chunks >= 2
    assert index.manifest()["local_only"] is True
    hit = index.search("ownership post-money")
    assert hit and hit[0].page_start == 1
    assert "TOPIC 3" in hit[0].section
    index.close()


def test_tutor_refuses_outside_corpus_and_cites_answer(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _pdf(corpus / "vc-course.pdf")
    index = CorpusIndex(tmp_path / "index.sqlite3", corpus_root=corpus)
    index.ingest_directory()
    tutor = TutorEngine(index)
    answer = tutor.ask("Comment calculer ownership VC ?")
    assert not answer.refused
    assert answer.citations[0].page == 1
    assert answer.citations[0].source == "vc-course.pdf"
    refused = tutor.ask("Qui a gagné la Coupe du monde en 2030 ?")
    assert refused.refused
    assert refused.citations == []


def test_summary_srs_quiz_plan_and_exam_gate(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _pdf(corpus / "vc-course.pdf")
    index = CorpusIndex(tmp_path / "index.sqlite3", corpus_root=corpus)
    index.ingest_directory()
    summary = build_summary(index, "TOPIC 3")
    assert summary.formulas
    output = export_summary_pdf(summary, tmp_path / "summary.pdf")
    assert output.is_file()
    srs = SRSStore(tmp_path / "srs.sqlite3")
    cards = srs.generate(index, chapter="TOPIC 3")
    assert cards
    reviewed = srs.review(cards[0].card_id, 5)
    assert reviewed.interval_days == 1
    quiz = QuizEngine(index, tmp_path / "quiz.sqlite3")
    question = quiz.next_question("TOPIC 3")
    assert question is not None
    plan = build_plan(quiz)
    assert plan["sessions"]
    blocked = ExamEngine(quiz).start(size=1, chapters=["TOPIC 3"])
    assert blocked["status"] == "blocked"


def test_learning_routes_are_local_and_refuse_unknown_chapter(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _pdf(corpus / "vc-course.pdf")
    app = FastAPI()
    app.include_router(create_learning_router(tmp_path / "learning", corpus_root=corpus))
    with TestClient(app) as client:
        ingested = client.post("/career/ingest")
        assert ingested.status_code == 200
        response = client.post("/career/tutor/ask", json={"question": "What is MOIC?", "mode": "explanation"})
        assert response.status_code == 200
        assert response.json()["local_only"] is True
        assert response.json()["citations"]
        assert client.get("/career/chapters").json()["chapters"]
        assert client.get("/career/search", params={"q": "MOIC"}).json()["results"]
        missing = client.post("/career/quiz/next", json={"chapter": "TOPIC 99"})
        assert missing.status_code == 404
