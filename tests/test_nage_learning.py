from __future__ import annotations

from pathlib import Path
import json
from datetime import date, datetime, timezone
from concurrent.futures import ThreadPoolExecutor

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
from career.summary import build_summary, export_plan_pdf, export_summary_pdf
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
    assert "Ownership VC equals investment divided by post-money." in answer.answer
    refused = tutor.ask("Qui a gagné la Coupe du monde en 2030 ?")
    assert refused.refused
    assert refused.citations == []


def test_tutor_search_is_limited_to_selected_chapter(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _pdf(corpus / "Topic_3_course.pdf")
    other = canvas.Canvas(str(corpus / "Topic_4_notes.pdf"), pagesize=A4)
    other.drawString(60, 780, "TOPIC 4 — TERM SHEET OWNERSHIP")
    other.drawString(60, 750, "Post-money valuation and ownership depend on investment amount and shares issued.")
    other.save()
    index = CorpusIndex(tmp_path / "index.sqlite3", corpus_root=corpus)
    index.ingest_directory()
    answer = TutorEngine(index).ask(
        "Comment calculer la valorisation post-money à partir du montant investi et du pourcentage obtenu ?",
        section="TOPIC 3",
    )
    assert not answer.refused
    assert answer.citations
    assert all(citation.source == "Topic_3_course.pdf" for citation in answer.citations)
    assert "Post-money equals pre-money plus investment." in answer.answer


def test_beginner_tutor_explains_split_post_money_formula_from_course(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "Topic_3_formula.pdf.txt").write_text(
        "=== PAGE 2 ===\nTOPIC 3 — VALUATION\nInvestment amount I is cash invested.\n"
        "Ownership fraction FINV is the percentage of equity obtained.\n"
        "Post-money valuation: VPOST = I / FINV\nPre-money valuation: VPRE = VPOST - I",
        encoding="utf-8",
    )
    index = CorpusIndex(tmp_path / "index.sqlite3", corpus_root=corpus)
    index.ingest_directory()
    answer = TutorEngine(index).ask(
        "Comment calculer la valorisation post-money à partir du montant investi et du pourcentage obtenu ?",
        mode="beginner",
        section="TOPIC 3",
    )
    assert "I ÷ F_INV" in answer.answer
    assert "VPOST = I / FINV" in answer.citations[0].excerpt
    assert answer.citations[0].page == 2
    assert len(answer.citations) == 1


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
    assert all(len(card.answer) >= 35 and not card.answer.isupper() for card in cards)
    assert cards[0].answer == cards[0].source["excerpt"]
    assert "Ownership VC" in cards[0].answer
    due_at = cards[0].due_at
    srs._conn.execute("UPDATE flashcards SET answer = ? WHERE card_id = ?", ("legacy fragment", cards[0].card_id))
    srs._conn.commit()
    refreshed = srs.generate(index, chapter="TOPIC 3")
    refreshed_card = next(card for card in refreshed if card.card_id == cards[0].card_id)
    assert refreshed_card.answer == cards[0].source["excerpt"]
    assert refreshed_card.due_at == due_at
    reviewed = srs.review(cards[0].card_id, 5)
    assert reviewed.interval_days == 1
    regenerated = srs.generate(index, chapter="TOPIC 3")
    preserved = next(card for card in regenerated if card.card_id == cards[0].card_id)
    assert preserved.last_quality == 5 and preserved.repetitions == 1
    quiz = QuizEngine(index, tmp_path / "quiz.sqlite3")
    question = quiz.next_question("TOPIC 3")
    assert question is not None
    plan = build_plan(quiz)
    assert plan["sessions"]
    blocked = ExamEngine(quiz).start(size=1, chapters=["TOPIC 3"])
    assert blocked["status"] == "blocked"


def test_quiz_exposes_unique_cited_options_and_answer_feedback(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _pdf(corpus / "vc-course.pdf")
    index = CorpusIndex(tmp_path / "index.sqlite3", corpus_root=corpus)
    index.ingest_directory()
    quiz = QuizEngine(index, tmp_path / "quiz.sqlite3")
    question = quiz.next_question("TOPIC 3")
    assert question is not None
    assert len(question.options) == len(set(question.options)) == 4
    assert "correct_index" not in question.public()
    assert question.citation["source"] == "vc-course.pdf"
    result = quiz.answer(question.question_id, question.correct_index)
    assert result["correct"] is True
    assert result["mastery"]["mastered"] is False
    assert result["mastery"]["attempts_required"] == 7
    assert result["correct_answer"] == question.options[question.correct_index]
    assert result["explanation"]
    quiz.close()
    index.close()


def test_concurrent_dashboard_and_plan_reads_are_serialized(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _pdf(corpus / "vc-course.pdf")
    index = CorpusIndex(tmp_path / "index.sqlite3", corpus_root=corpus)
    index.ingest_directory()
    quiz = QuizEngine(index, tmp_path / "quiz.sqlite3")
    operations = [
        (quiz.dashboard, ( ["TOPIC 3"], )),
        (build_plan, (quiz,)),
    ] * 12
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda call: call[0](*call[1]), operations))
    assert len(results) == 24
    assert all(result for result in results)
    quiz.close()
    index.close()


def test_coverage_joins_private_manifest_without_returning_private_path(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    mirror = corpus / "Topic_1_Intro.pdf.txt"
    mirror.write_text("=== PAGE 1 ===\nVenture capital finances startups.\n=== PAGE 2 ===\nStaged financing follows milestones.", encoding="utf-8")
    (corpus / "manifest.json").write_text(json.dumps({"files": [{
        "name": "Topic_1_Intro.pdf", "kind": "pdf", "pages": 2,
        "nonempty_pages": 2, "text_file": mirror.name,
    }]}), encoding="utf-8")
    index = CorpusIndex(tmp_path / "index.sqlite3", corpus_root=corpus)
    index.ingest_directory()
    coverage = index.coverage()
    assert coverage["expected_sources"] == coverage["indexed_sources"] == 1
    assert coverage["expected_content_units"] == coverage["covered_content_units"] == 2
    assert coverage["source_coverage"] == coverage["content_coverage"] == 1.0
    assert str(corpus) not in json.dumps(coverage)
    index.close()


def test_srs_ratings_include_again_and_sm2_scheduling(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _pdf(corpus / "vc-course.pdf")
    index = CorpusIndex(tmp_path / "index.sqlite3", corpus_root=corpus)
    index.ingest_directory()
    srs = SRSStore(tmp_path / "srs.sqlite3")
    card = srs.generate(index, chapter="TOPIC 3")[0]
    assert SRSStore.rating_quality("again") == 0
    reviewed = srs.review(card.card_id, SRSStore.rating_quality("again"))
    remaining = datetime.fromisoformat(reviewed.due_at) - datetime.now(timezone.utc)
    assert reviewed.repetitions == 0
    assert 9 * 60 <= remaining.total_seconds() <= 11 * 60
    assert srs.stats(chapter="TOPIC 3")["due"] == 0
    srs.close()
    index.close()


def test_exam_saves_answers_enforces_membership_and_returns_idempotent_correction(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _pdf(corpus / "vc-course.pdf")
    (corpus / "Topic_3_calculations.pdf.txt").write_text(
        "=== PAGE 1 ===\nVC method post-money valuation ownership. A 13.8x CCM over five years implies an IRR of about 69 percent. A 40 percent hurdle rate uses 1.4 to the power of five.",
        encoding="utf-8",
    )
    index = CorpusIndex(tmp_path / "index.sqlite3", corpus_root=corpus)
    index.ingest_directory()
    quiz = QuizEngine(index, tmp_path / "quiz.sqlite3")
    engine = ExamEngine(quiz)
    for attempt in range(7):
        practice = quiz.next_question("TOPIC 3", sequence=attempt)
        assert practice is not None
        quiz.answer(practice.question_id, practice.correct_index)
    exam = engine.start(size=1, chapters=["TOPIC 3"], duration_minutes=5)
    assert exam["status"] == "ready"
    question = exam["questions"][0]
    try:
        engine.answer(exam["exam_id"], "outside-session-question", 0)
    except ValueError:
        pass
    else:
        raise AssertionError("An exam session must reject unrelated question IDs")
    saved = engine.answer(exam["exam_id"], question["question_id"], quiz._conn.execute("SELECT correct_index FROM quiz_questions WHERE question_id=?", (question["question_id"],)).fetchone()[0])
    assert saved["saved"] is True
    assert engine.submit(exam["exam_id"])["score"] == 1.0
    assert engine.stats()["completed"] == 1
    assert engine.stats()["last_score"] == 1.0
    repeated = engine.submit(exam["exam_id"])
    assert repeated["score"] == 1.0
    assert repeated["corrections"][0]["citation"]["source"] in {"vc-course.pdf", "Topic_3_calculations.pdf"}
    expired = engine.start(size=1, chapters=["TOPIC 3"], duration_minutes=5)
    expired_question = expired["questions"][0]
    quiz._conn.execute("UPDATE exam_sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE exam_id=?", (expired["exam_id"],))
    quiz._conn.commit()
    try:
        engine.answer(expired["exam_id"], expired_question["question_id"], 0)
    except ValueError as error:
        assert "temps" in str(error).lower()
    else:
        raise AssertionError("Expired exams must reject new answers")
    assert engine.submit(expired["exam_id"])["status"] == "timed_out"
    quiz.close()
    index.close()


def test_plan_pdf_contains_a_valid_pdf_artifact(tmp_path: Path) -> None:
    plan = {"start": "2026-11-03", "until": "2026-11-06", "sessions": [{
        "date": "2026-11-03", "chapter": "TOPIC 3 — Valorisation", "phase": "guided_learning",
        "activities": ["Fiche sourcée", "Quiz progressif"],
    }]}
    target = export_plan_pdf(plan, tmp_path / "plan.pdf")
    assert target.read_bytes().startswith(b"%PDF")


def test_revision_plan_covers_all_chapters_and_gates_exam_day(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _pdf(corpus / "vc-course.pdf")
    index = CorpusIndex(tmp_path / "index.sqlite3", corpus_root=corpus)
    index.ingest_directory()
    quiz = QuizEngine(index, tmp_path / "quiz.sqlite3")
    plan = build_plan(quiz, today=date(2026, 11, 3), until=date(2026, 11, 6))
    assert {item["chapter"].split(" — ")[0] for item in plan["sessions"]} == {"TOPIC 1", "TOPIC 2", "TOPIC 3", "TOPIC 4", "TOPIC 5"}
    last_day = [item for item in plan["sessions"] if item["date"] == "2026-11-06"]
    assert last_day
    assert all("uniquement quand tous les chapitres atteignent les critères" in item["activities"][-1] for item in last_day)


def test_learning_routes_are_local_and_refuse_unknown_chapter(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _pdf(corpus / "vc-course.pdf")
    app = FastAPI()
    app.include_router(create_learning_router(tmp_path / "learning", corpus_root=corpus))
    with TestClient(app) as client:
        ingested = client.post("/career/ingest")
        assert ingested.status_code == 200
        response = client.post("/career/tutor/ask", json={"question": "What is MOIC?", "mode": "explanation", "section": "TOPIC 3"})
        assert response.status_code == 200
        assert response.json()["local_only"] is True
        assert response.json()["citations"]
        assert client.get("/career/chapters").json()["chapters"]
        assert client.get("/career/search", params={"q": "MOIC"}).json()["results"]
        assert client.get("/career/coverage").status_code == 200
        assert client.get("/career/plan/pdf").headers["content-type"] == "application/pdf"
        due_cards = client.post("/career/srs/generate", params={"chapter": "TOPIC 3", "limit": 10}).json()["cards"]
        assert due_cards
        review = client.post("/career/srs/review", json={"card_id": due_cards[0]["card_id"], "rating": "good"})
        assert review.status_code == 200
        assert review.json()["card"]["last_quality"] == 4
        dashboard = client.get("/career/learning/dashboard").json()
        assert dashboard["notions"] and "due" in dashboard["notions"][0]
        blocked_exam = client.post("/career/exam/start", json={"size": 1, "chapters": ["TOPIC 3"]})
        assert blocked_exam.status_code == 200
        assert blocked_exam.json()["status"] == "blocked"
        chapter_question = client.post("/career/quiz/next", json={"chapter": "TOPIC 3"})
        assert chapter_question.status_code == 200
        assert chapter_question.json()["question"]["chapter"] == "TOPIC 3"
        missing = client.post("/career/quiz/next", json={"chapter": "TOPIC 99"})
        assert missing.status_code == 404
