from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from career.case_practice import CasePracticeEngine
from career.ingest import CorpusIndex
from career.learning_router import create_learning_router


_EXAM_TEXT = """
Q16 Palooka Products receives 5 million today, exit 50 million in five years, hurdle 40 percent.
CCM 1.4^5 = 5.378. Post money 50 / 5.378 = 9.297. VC ownership 54 percent.
Q17 founders 5,000,000 shares, VC invests 2 million at 8 million post-money, pool 20 percent.
Founders 55 percent, options pool 20 percent and 1,818,182 shares, VC 25 percent and 2,272,727 shares.
Total shares 9,090,909.
Q18 Miller 5 million investment, 1 million convertible preferred shares, two common shares each,
15 million shares after conversion, 3 million IPO shares, 11 percent ownership. Stock price 25 dollars,
exit value 50 million, CCM 10x, IRR 33 percent over eight years.
Q19 strategic acquisition 6 billion in seven years, seed 1 million at 8x, Series A 25 million at 5x,
Series B 50 million at 4x, Series C 200 million at 3x. Post-money valuations 6.875, 80, 450 and 2,000 million.
Fully diluted ownership founders 47 percent, Seed 8 percent, Series A 25 percent, Series B 10 percent,
Series C 10 percent at exit.
"""

_COURSE_TEXT = """
TOPIC 3 Venture capital method. The cash-on-cash multiple is (1 + hurdle rate) raised to the number
of years. Post-money valuation equals exit value divided by the required multiple. Investor ownership
equals the required proceeds divided by exit value. Fully diluted capitalization includes options.
Post-money is pre-money plus the new investment. Ownership for a round is investment divided by
post-money valuation. Later financing rounds dilute earlier investors and founders proportionally.
Cash-on-cash multiple equals exit proceeds divided by initial investment. IRR is multiple to the power
of one divided by holding years, minus one.
"""


def _index(tmp_path: Path) -> CorpusIndex:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "VC final exam 2025 solutions.pdf.txt").write_text(_EXAM_TEXT, encoding="utf-8")
    (corpus / "Topic_3_course.pdf.txt").write_text(_COURSE_TEXT, encoding="utf-8")
    index = CorpusIndex(tmp_path / "corpus.sqlite3", corpus_root=corpus)
    index.ingest_directory()
    return index


def test_public_cases_hide_answers_and_include_local_citations(tmp_path: Path) -> None:
    index = _index(tmp_path)
    practice = CasePracticeEngine(index, tmp_path / "practice.sqlite3")
    result = practice.list_cases()

    assert len(result["cases"]) == 4
    for case in result["cases"]:
        assert "expected" not in str(case["steps"]).lower()
        assert case["citations"]
        assert all("excerpt" not in item for item in case["citations"])
        assert any("VC final exam 2025 solutions" in item["source"] for item in case["citations"])
        assert case["rubric"].startswith("Barème pédagogique")
    assert "5.378" not in str(result["cases"][0])
    practice.close()
    index.close()


def test_q16_accepts_french_numeric_input_and_awards_full_pedagogical_credit(tmp_path: Path) -> None:
    index = _index(tmp_path)
    practice = CasePracticeEngine(index, tmp_path / "practice.sqlite3")

    result = practice.submit("VC25-Q16", {"ccm": "5,378x", "proceeds": "$26,89 M$", "ownership": 0.538})

    assert result["score"] == 3.0
    assert result["max_score"] == 3.0
    assert result["percent"] == 100
    assert all(item["correct"] for item in result["steps"])
    assert result["steps"][2]["entered"] == 53.8
    assert all(item.get("excerpt") for item in result["citations"])
    assert "indicatif" in result["rubric"]
    assert result["local_only"] is True
    practice.close()
    index.close()


def test_q17_q18_and_q19_score_calculation_steps_separately(tmp_path: Path) -> None:
    index = _index(tmp_path)
    practice = CasePracticeEngine(index, tmp_path / "practice.sqlite3")

    q17 = practice.submit("VC25-Q17", {
        "vc_ownership": 25, "founder_ownership": 55, "total_shares": 9.090909,
        "pool_shares": 1.818182, "vc_shares": 2.272727,
    })
    q18 = practice.submit("VC25-Q18", {
        "converted_shares": 2, "ipo_total": 18, "ownership": 11.1,
        "exit_value": 50, "ccm": 10, "irr": 33.4,
    })
    q19 = practice.submit("VC25-Q19", {
        "series_c_post": 2000, "series_b_post": 450, "series_a_post": 80, "seed_post": "6,875",
        "seed_round_pct": 14.55, "series_a_round_pct": 31.25, "series_b_round_pct": 11.11,
        "series_c_round_pct": 10, "founder_exit_pct": 47, "seed_exit_pct": 8,
        "series_a_exit_pct": 25, "series_b_exit_pct": 10, "series_c_exit_pct": 10,
    })

    assert q17["score"] == 3.0 and q17["max_score"] == 3.0
    assert q18["score"] == 4.0 and q18["max_score"] == 4.0
    assert q19["score"] == 5.0 and q19["max_score"] == 5.0
    practice.close()
    index.close()


def test_partial_credit_bad_values_and_attempts_persist_locally(tmp_path: Path) -> None:
    index = _index(tmp_path)
    db_path = tmp_path / "practice.sqlite3"
    practice = CasePracticeEngine(index, db_path)

    result = practice.submit("VC25-Q16", {"ccm": "not a number", "proceeds": 26.89})
    assert result["score"] == 1.0
    assert result["steps"][0]["valid_number"] is False
    assert result["steps"][1]["correct"] is True
    try:
        practice.submit("VC25-Q16", {"ccm": 5.378, "unexpected": 1})
    except ValueError as error:
        assert "aucun champ" in str(error)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Unknown answer fields must be rejected.")
    practice.close()

    reopened = CasePracticeEngine(index, db_path)
    stats = next(item["stats"] for item in reopened.list_cases()["cases"] if item["case_id"] == "VC25-Q16")
    assert stats["attempts"] == 1
    assert stats["best_score"] == 1.0
    assert stats["max_score"] == 3.0
    assert stats["local_only"] is True
    assert stats["latest_result"]["steps"][1]["correct"] is True
    reopened.close()
    index.close()


def test_practice_routes_return_cases_submit_and_reject_unknown_case(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "VC final exam 2025 solutions.pdf.txt").write_text(_EXAM_TEXT, encoding="utf-8")
    (corpus / "Topic_3_course.pdf.txt").write_text(_COURSE_TEXT, encoding="utf-8")
    app = FastAPI()
    app.include_router(create_learning_router(tmp_path / "learning", corpus_root=corpus))

    with TestClient(app) as client:
        assert client.post("/career/ingest").status_code == 200
        cases = client.get("/career/practice/cases")
        assert cases.status_code == 200
        assert len(cases.json()["cases"]) == 4
        assert "expected" not in str(cases.json()["cases"][0]["steps"]).lower()
        submitted = client.post("/career/practice/cases/VC25-Q16/submit", json={"answers": {"ccm": 5.378, "proceeds": 26.89, "ownership": 53.8}})
        assert submitted.status_code == 200
        assert submitted.json()["score"] == 3.0
        refreshed = client.get("/career/practice/cases").json()
        q16 = next(item for item in refreshed["cases"] if item["case_id"] == "VC25-Q16")
        assert q16["stats"]["latest_result"]["score"] == 3.0
        assert client.post("/career/practice/cases/unknown/submit", json={"answers": {}}).status_code == 404
        assert client.post("/api/career/practice/cases/VC25-Q16/submit", json={"answers": {"unknown": 3}}).status_code == 400
