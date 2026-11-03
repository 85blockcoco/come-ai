from __future__ import annotations

import json
from pathlib import Path

import pytest

from academics.vc.storage import VcStore
from nage import main


def invoke(capsys, *args: str) -> tuple[int, str, str]:
    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_review_start_reveal_grade_and_finish(tmp_path: Path, capsys) -> None:
    home = str(tmp_path / "vc")
    code, out, _ = invoke(
        capsys,
        "vc",
        "review",
        "--minutes",
        "10",
        "--today",
        "2026-11-02",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    payload = json.loads(out)
    session_id = payload["session_id"]
    assert payload["current"] is not None
    assert payload["summary"] is None
    assert payload["total"] > 0

    code, out, _ = invoke(
        capsys,
        "vc",
        "review",
        "--session",
        session_id,
        "--reveal",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    revealed = json.loads(out)
    assert "answer" in revealed["current"]
    assert "explanation" in revealed["current"]

    code, out, _ = invoke(
        capsys,
        "vc",
        "review",
        "--session",
        session_id,
        "--grade",
        "good",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    graded = json.loads(out)
    assert graded["last_result"]["grade"] == "good"
    assert graded["done"] == 1

    while graded["current"] is not None:
        code, out, _ = invoke(
            capsys,
            "vc",
            "review",
            "--session",
            session_id,
            "--grade",
            "good",
            "--json",
            "--home",
            home,
        )
        assert code == 0
        graded = json.loads(out)
    assert graded["summary"]["seen"] == graded["total"]


def test_review_resumes_the_active_session(tmp_path: Path, capsys) -> None:
    home = str(tmp_path / "vc")
    code, out, _ = invoke(
        capsys,
        "vc",
        "review",
        "--minutes",
        "10",
        "--today",
        "2026-11-02",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    started = json.loads(out)
    session_id = started["session_id"]

    code, out, _ = invoke(
        capsys,
        "vc",
        "review",
        "--session",
        session_id,
        "--grade",
        "good",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    assert json.loads(out)["done"] == 1

    code, out, _ = invoke(
        capsys,
        "vc",
        "review",
        "--minutes",
        "10",
        "--today",
        "2026-11-02",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    resumed = json.loads(out)
    assert resumed["session_id"] == session_id
    assert resumed["done"] == 1


def test_invalid_grade_exits_two(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "vc",
                "review",
                "--session",
                "ses-unknown",
                "--grade",
                "perfect",
                "--home",
                str(tmp_path / "vc"),
            ]
        )
    assert exc.value.code == 2


def test_unknown_session_exits_two(tmp_path: Path, capsys) -> None:
    code, _, err = invoke(
        capsys,
        "vc",
        "review",
        "--session",
        "ses-unknown",
        "--json",
        "--home",
        str(tmp_path / "vc"),
    )
    assert code == 2
    assert "Active session not found" in err


def test_drill_list_run_random_and_diagnostics(tmp_path: Path, capsys) -> None:
    home = str(tmp_path / "vc")
    code, out, _ = invoke(
        capsys, "vc", "drill", "list", "--topic", "VC04", "--json", "--home", home
    )
    assert code == 0
    drills = json.loads(out)["drills"]
    assert drills
    assert all(item["topic_id"] == "VC04" for item in drills)
    assert "answer" not in drills[0]

    code, out, _ = invoke(
        capsys,
        "vc",
        "drill",
        "run",
        "VC04-D001",
        "--answer",
        "10 M€",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    result = json.loads(out)
    assert result["accepted"] is True
    assert result["expected"] == 10

    code, out, _ = invoke(
        capsys,
        "vc",
        "drill",
        "run",
        "VC04-D001",
        "--answer",
        "8",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    wrong = json.loads(out)
    assert wrong["accepted"] is False
    assert wrong["diagnostic"] == "formula"

    code, out, _ = invoke(
        capsys,
        "vc",
        "drill",
        "run",
        "VC04-D001",
        "--answer",
        "beaucoup",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    assert json.loads(out)["diagnostic"] == "unit"

    code, out, _ = invoke(
        capsys,
        "vc",
        "drill",
        "random",
        "--topic",
        "VC04",
        "--seed",
        "7",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    assert json.loads(out)["topic_id"] == "VC04"


def test_case_list_show_grade_and_errors(tmp_path: Path, capsys) -> None:
    home = str(tmp_path / "vc")
    code, out, _ = invoke(capsys, "vc", "case", "list", "--json", "--home", home)
    assert code == 0
    cases = json.loads(out)["cases"]
    assert len(cases) >= 4

    code, out, _ = invoke(
        capsys, "vc", "case", "show", "VC03-CASE01", "--json", "--home", home
    )
    assert code == 0
    shown = json.loads(out)
    assert "model_answer" not in shown
    assert shown["case_id"] == "VC03-CASE01"

    answers_path = tmp_path / "answers.json"
    answers_path.write_text(
        json.dumps(
            {
                "q1": "Post-money 10 M€, investor 20%.",
                "q2": "2 million new shares.",
                "q3": "The runway shortens and a bridge may dilute further.",
            }
        ),
        encoding="utf-8",
    )
    code, out, _ = invoke(
        capsys,
        "vc",
        "case",
        "grade",
        "VC03-CASE01",
        "--answers",
        str(answers_path),
        "--json",
        "--home",
        home,
    )
    assert code == 0
    result = json.loads(out)
    assert result["score"] == pytest.approx(1.0)
    assert result["model_answer"]
    assert "not a human grade" in result["notice"]

    malformed = tmp_path / "malformed.json"
    malformed.write_text("not json", encoding="utf-8")
    code, _, err = invoke(
        capsys,
        "vc",
        "case",
        "grade",
        "VC03-CASE01",
        "--answers",
        str(malformed),
        "--json",
        "--home",
        home,
    )
    assert code == 2
    assert "Invalid answers JSON" in err

    code, _, err = invoke(
        capsys,
        "vc",
        "case",
        "grade",
        "VC03-CASE01",
        "--answers",
        str(tmp_path / "missing.json"),
        "--json",
        "--home",
        home,
    )
    assert code == 2
    assert "not found" in err


def test_radar_plan_and_report(tmp_path: Path, capsys) -> None:
    home = str(tmp_path / "vc")
    code, out, _ = invoke(
        capsys,
        "vc",
        "review",
        "--minutes",
        "10",
        "--today",
        "2026-11-02",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    payload = json.loads(out)
    session_id = payload["session_id"]
    code, _, _ = invoke(
        capsys,
        "vc",
        "review",
        "--session",
        session_id,
        "--grade",
        "again",
        "--json",
        "--home",
        home,
    )
    assert code == 0

    code, out, _ = invoke(capsys, "vc", "radar", "--today", "2026-11-02", "--json", "--home", home)
    assert code == 0
    radar = json.loads(out)
    assert len(radar["topics"]) == 20
    assert len(radar["untested"]) < 20

    code, out, _ = invoke(
        capsys,
        "vc",
        "plan",
        "--minutes",
        "30",
        "--today",
        "2026-11-02",
        "--exam-date",
        "2026-11-15",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    plan = json.loads(out)
    assert plan["total_minutes"] <= 30
    assert all(item["reason"] for item in plan["activities"])

    code, out, _ = invoke(
        capsys, "vc", "report", "--days", "30", "--today", "2026-11-02", "--json", "--home", home
    )
    assert code == 0
    report = json.loads(out)
    path = Path(report["markdown_path"])
    assert path.exists()
    assert path.parent == Path(home) / "reports"
    assert "Rapport de progression" in path.read_text(encoding="utf-8")


def test_glossary_search_and_term_sheet_decode(tmp_path: Path, capsys) -> None:
    home = str(tmp_path / "vc")
    code, out, _ = invoke(
        capsys,
        "vc",
        "glossary",
        "search",
        "liquidation preference",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    matches = json.loads(out)["matches"]
    assert matches
    assert any(entry["term_en"] == "Liquidation preference" for entry in matches)

    code, out, _ = invoke(
        capsys, "vc", "glossary", "search", "zzz-inconnu", "--json", "--home", home
    )
    assert code == 0
    assert json.loads(out)["notice"] == "not documented"

    term_sheet = tmp_path / "term_sheet.txt"
    term_sheet.write_text(
        "Liquidation preference 1x non participating\nClause inconnue\n",
        encoding="utf-8",
    )
    code, out, _ = invoke(
        capsys,
        "vc",
        "term-sheet",
        "decode",
        str(term_sheet),
        "--json",
        "--home",
        home,
    )
    assert code == 0
    decoded = json.loads(out)
    assert decoded["clauses"][0]["clause"] == "liquidation"
    assert decoded["clauses"][0]["participating"] is False
    assert decoded["unknown_clauses"] == ["Clause inconnue"]

    binary = tmp_path / "binary.txt"
    binary.write_bytes(b"\xff\xfe\x00\x00")
    code, _, err = invoke(
        capsys, "vc", "term-sheet", "decode", str(binary), "--json", "--home", home
    )
    assert code == 2
    assert "UTF-8" in err


def test_plan_uses_exam_date_from_settings_and_cli_overrides_it(tmp_path: Path, capsys) -> None:
    home = tmp_path / "vc"
    store = VcStore(home)
    store.save_settings({"exam_date": "2026-11-15"})

    code, out, _ = invoke(
        capsys,
        "vc",
        "plan",
        "--minutes",
        "30",
        "--today",
        "2026-11-02",
        "--json",
        "--home",
        str(home),
    )
    assert code == 0
    assert json.loads(out)["exam_date"] == "2026-11-15"

    code, out, _ = invoke(
        capsys,
        "vc",
        "plan",
        "--minutes",
        "30",
        "--today",
        "2026-11-02",
        "--exam-date",
        "2026-12-01",
        "--json",
        "--home",
        str(home),
    )
    assert code == 0
    assert json.loads(out)["exam_date"] == "2026-12-01"


def test_plan_uses_the_default_exam_date_from_settings(tmp_path: Path, capsys) -> None:
    home = tmp_path / "vc"
    code, out, _ = invoke(
        capsys,
        "vc",
        "plan",
        "--minutes",
        "30",
        "--today",
        "2026-11-03",
        "--json",
        "--home",
        str(home),
    )
    assert code == 0
    assert json.loads(out)["exam_date"] == "2026-11-06"


def test_exam_date_command_shows_and_persists_the_slot(tmp_path: Path, capsys) -> None:
    home = tmp_path / "vc"
    code, out, _ = invoke(capsys, "vc", "exam-date", "--json", "--home", str(home))
    assert code == 0
    assert json.loads(out) == {
        "exam_date": "2026-11-06",
        "exam_time": "16:00",
        "exam_duration_minutes": 90,
        "source": "settings",
    }

    code, out, _ = invoke(
        capsys,
        "vc",
        "exam-date",
        "2026-12-01",
        "--time",
        "09:30",
        "--duration",
        "120",
        "--json",
        "--home",
        str(home),
    )
    assert code == 0
    assert json.loads(out)["saved"] is True

    code, out, _ = invoke(
        capsys,
        "vc",
        "plan",
        "--minutes",
        "30",
        "--today",
        "2026-11-03",
        "--json",
        "--home",
        str(home),
    )
    assert code == 0
    assert json.loads(out)["exam_date"] == "2026-12-01"

    code, _, err = invoke(
        capsys,
        "vc",
        "exam-date",
        "06/11/2026",
        "--json",
        "--home",
        str(home),
    )
    assert code == 2
    assert "AAAA-MM-JJ" in err


def test_delete_requires_phrase_and_removes_only_vc_home(tmp_path: Path, capsys) -> None:
    home = Path(tmp_path / "vc")
    other = tmp_path / "career"
    other.mkdir()
    code, _, _ = invoke(
        capsys,
        "vc",
        "review",
        "--minutes",
        "10",
        "--today",
        "2026-11-02",
        "--json",
        "--home",
        str(home),
    )
    assert code == 0

    code, _, err = invoke(
        capsys, "vc", "delete", "--confirm", "supprimer", "--json", "--home", str(home)
    )
    assert code == 2
    assert "confirmation" in err
    assert home.exists()

    code, out, _ = invoke(
        capsys,
        "vc",
        "delete",
        "--confirm",
        "SUPPRIMER MES DONNEES VC",
        "--json",
        "--home",
        str(home),
    )
    assert code == 0
    assert json.loads(out)["deleted"] is True
    assert not home.exists()
    assert other.exists()


def test_exam_start_resume_submit_and_oral(tmp_path: Path, capsys) -> None:
    from academics.vc.content import load_content

    home = str(tmp_path / "vc")
    code, out, _ = invoke(
        capsys,
        "vc",
        "exam",
        "start",
        "--questions",
        "4",
        "--minutes",
        "30",
        "--seed",
        "7",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    started = json.loads(out)
    exam_id = started["exam_id"]
    assert started["resumed"] is False
    assert started["total_questions"] == 4
    assert started["total_points"] == 100
    assert all("answer" not in item for item in started["questions"])
    assert all("expected_answer" not in item for item in started["questions"])

    code, out, _ = invoke(
        capsys,
        "vc",
        "exam",
        "start",
        "--questions",
        "4",
        "--minutes",
        "30",
        "--seed",
        "7",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    resumed = json.loads(out)
    assert resumed["resumed"] is True
    assert resumed["exam_id"] == exam_id

    content = load_content()
    answers = {
        item["question_id"]: content.exam_question(item["question_id"]).answer
        for item in started["questions"]
    }
    answers_path = tmp_path / "exam_answers.json"
    answers_path.write_text(json.dumps(answers), encoding="utf-8")
    code, out, _ = invoke(
        capsys,
        "vc",
        "exam",
        "submit",
        exam_id,
        "--answers",
        str(answers_path),
        "--json",
        "--home",
        home,
    )
    assert code == 0
    result = json.loads(out)
    assert result["score"] == pytest.approx(1.0)
    assert result["status"] == "submitted"
    assert result["points_total"] == 100
    assert result["per_topic"]
    assert result["notice"].startswith("Deterministic grading")
    assert not (Path(home) / "exams" / "active.json").exists()
    history = (Path(home) / "exams" / "history.jsonl").read_text(encoding="utf-8")
    assert exam_id in history

    code, out, _ = invoke(
        capsys,
        "vc",
        "oral",
        "VC07",
        "--count",
        "3",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    oral = json.loads(out)
    assert oral["count"] == 3
    assert all(item["follow_ups"] for item in oral["questions"])
    assert "answer" not in json.dumps(oral)


def test_exam_submit_marks_an_expired_exam(tmp_path: Path, capsys) -> None:
    home = str(tmp_path / "vc")
    code, out, _ = invoke(
        capsys,
        "vc",
        "exam",
        "start",
        "--questions",
        "1",
        "--minutes",
        "1",
        "--seed",
        "2",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    started = json.loads(out)
    answers_path = tmp_path / "expired_answers.json"
    answers_path.write_text(
        json.dumps({started["questions"][0]["question_id"]: "réponse conservée"}),
        encoding="utf-8",
    )
    code, out, _ = invoke(
        capsys,
        "vc",
        "exam",
        "submit",
        started["exam_id"],
        "--answers",
        str(answers_path),
        "--now",
        "2030-01-01T00:00:00",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    result = json.loads(out)
    assert result["expired"] is True
    assert result["status"] == "expired"
    assert result["answered"] == 1
    history = (Path(home) / "exams" / "history.jsonl").read_text(encoding="utf-8")
    assert '"status": "expired"' in history


def test_exam_and_oral_errors_exit_two(tmp_path: Path, capsys) -> None:
    home = str(tmp_path / "vc")
    code, _, err = invoke(
        capsys,
        "vc",
        "exam",
        "start",
        "--questions",
        "21",
        "--json",
        "--home",
        home,
    )
    assert code == 2
    assert "Not enough" in err

    code, _, err = invoke(
        capsys,
        "vc",
        "exam",
        "submit",
        "exam-inconnu",
        "--answers",
        str(tmp_path / "missing.json"),
        "--json",
        "--home",
        home,
    )
    assert code == 2
    assert "not found" in err

    code, out, _ = invoke(
        capsys,
        "vc",
        "exam",
        "start",
        "--questions",
        "1",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    exam_id = json.loads(out)["exam_id"]
    malformed = tmp_path / "malformed_exam.json"
    malformed.write_text("not json", encoding="utf-8")
    code, _, err = invoke(
        capsys,
        "vc",
        "exam",
        "submit",
        exam_id,
        "--answers",
        str(malformed),
        "--json",
        "--home",
        home,
    )
    assert code == 2
    assert "Invalid answers JSON" in err

    code, _, err = invoke(
        capsys, "vc", "oral", "VC99", "--json", "--home", home
    )
    assert code == 2
    assert "Unknown topic" in err


NOTES_FIXTURES = Path(__file__).parent / "fixtures" / "vc_notes"


def test_notes_ingest_list_approve_and_reject(tmp_path: Path, capsys) -> None:
    home = str(tmp_path / "vc")
    fixture = NOTES_FIXTURES / "definitions.md"

    code, out, _ = invoke(
        capsys,
        "vc",
        "notes",
        "ingest",
        str(fixture),
        "--topic",
        "VC04",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    ingested = json.loads(out)
    assert ingested["created"] >= 4
    assert ingested["source"]["kind"] == "md"
    assert all(item["citation"]["quote"] for item in ingested["proposals"])

    code, out, _ = invoke(capsys, "vc", "notes", "list", "--json", "--home", home)
    assert code == 0
    listed = json.loads(out)
    assert listed["counts"]["proposed"] >= 4
    assert listed["sources"][0]["filename"] == "definitions.md"

    proposed = [
        item for item in ingested["proposals"] if item["status"] == "proposed"
    ]
    code, out, _ = invoke(
        capsys,
        "vc",
        "notes",
        "approve",
        proposed[0]["proposal_id"],
        "--json",
        "--home",
        home,
    )
    assert code == 0
    approved = json.loads(out)
    assert approved["approved"] is True
    assert approved["card"]["source_type"] == "user_note"
    assert approved["card"]["status"] == "active"
    assert approved["card"]["citation"] == proposed[0]["citation"]
    assert (Path(home) / "deck.json").exists()

    code, out, _ = invoke(
        capsys,
        "vc",
        "notes",
        "reject",
        proposed[1]["proposal_id"],
        "--json",
        "--home",
        home,
    )
    assert code == 0
    assert json.loads(out)["rejected"] is True

    code, out, _ = invoke(
        capsys,
        "vc",
        "notes",
        "ingest",
        str(fixture),
        "--topic",
        "VC04",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    again = json.loads(out)
    assert again["created"] == 0
    assert again["rejected_skipped"] >= 1


def test_notes_a_completer_requires_an_explicit_answer(tmp_path: Path, capsys) -> None:
    home = str(tmp_path / "vc")
    fixture = NOTES_FIXTURES / "questions.txt"
    code, out, _ = invoke(
        capsys,
        "vc",
        "notes",
        "ingest",
        str(fixture),
        "--topic",
        "VC07",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    proposals = json.loads(out)["proposals"]
    missing = next(item for item in proposals if item["status"] == "a_completer")
    assert missing["answer"] is None

    code, _, err = invoke(
        capsys,
        "vc",
        "notes",
        "approve",
        missing["proposal_id"],
        "--json",
        "--home",
        home,
    )
    assert code == 2
    assert "to be completed" in err

    code, out, _ = invoke(
        capsys,
        "vc",
        "notes",
        "approve",
        missing["proposal_id"],
        "--answer",
        "Une préférence qui participe au résidu après remboursement.",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    card = json.loads(out)["card"]
    assert card["answer"].startswith("Une préférence")
    assert card["status"] == "active"


def test_notes_changed_source_requires_replace(tmp_path: Path, capsys) -> None:
    home = str(tmp_path / "vc")
    path = tmp_path / "cours.md"
    path.write_text(
        "Post-money : définition initiale du post-money après le cash.\n",
        encoding="utf-8",
    )
    code, _, _ = invoke(
        capsys,
        "vc",
        "notes",
        "ingest",
        str(path),
        "--topic",
        "VC04",
        "--json",
        "--home",
        home,
    )
    assert code == 0

    path.write_text(
        "Pre-money : définition remplacée du pre-money avant le cash.\n",
        encoding="utf-8",
    )
    code, _, err = invoke(
        capsys,
        "vc",
        "notes",
        "ingest",
        str(path),
        "--topic",
        "VC04",
        "--json",
        "--home",
        home,
    )
    assert code == 2
    assert "has changed" in err

    code, out, _ = invoke(
        capsys,
        "vc",
        "notes",
        "ingest",
        str(path),
        "--topic",
        "VC04",
        "--replace",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    replaced = json.loads(out)
    assert replaced["source"]["kind"] == "md"
    assert replaced["created"] == 1


def test_notes_errors_exit_two_and_do_not_echo_note_text(
    tmp_path: Path, capsys
) -> None:
    home = str(tmp_path / "vc")
    missing = tmp_path / "missing.md"
    code, _, err = invoke(
        capsys,
        "vc",
        "notes",
        "ingest",
        str(missing),
        "--topic",
        "VC04",
        "--json",
        "--home",
        home,
    )
    assert code == 2
    assert "not found" in err

    fixture = NOTES_FIXTURES / "definitions.md"
    code, _, err = invoke(
        capsys,
        "vc",
        "notes",
        "ingest",
        str(fixture),
        "--topic",
        "VC99",
        "--json",
        "--home",
        home,
    )
    assert code == 2
    assert "Unknown topic" in err

    code, _, err = invoke(
        capsys,
        "vc",
        "notes",
        "approve",
        "prop-inconnu",
        "--json",
        "--home",
        home,
    )
    assert code == 2
    assert "not found" in err

    code, out, _ = invoke(
        capsys,
        "vc",
        "notes",
        "ingest",
        str(fixture),
        "--topic",
        "VC04",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    proposal = next(
        item for item in json.loads(out)["proposals"] if item["status"] == "proposed"
    )
    code, _, _ = invoke(
        capsys,
        "vc",
        "notes",
        "approve",
        proposal["proposal_id"],
        "--json",
        "--home",
        home,
    )
    assert code == 0
    code, _, err = invoke(
        capsys,
        "vc",
        "notes",
        "reject",
        proposal["proposal_id"],
        "--json",
        "--home",
        home,
    )
    assert code == 2
    assert "already approved" in err


def test_approved_note_card_is_available_to_review(tmp_path: Path, capsys) -> None:
    from academics.vc.content import load_content

    home = str(tmp_path / "vc")
    fixture = NOTES_FIXTURES / "definitions.md"
    code, out, _ = invoke(
        capsys,
        "vc",
        "notes",
        "ingest",
        str(fixture),
        "--topic",
        "VC04",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    proposal = next(
        item for item in json.loads(out)["proposals"] if item["status"] == "proposed"
    )
    code, _, _ = invoke(
        capsys,
        "vc",
        "notes",
        "approve",
        proposal["proposal_id"],
        "--json",
        "--home",
        home,
    )
    assert code == 0

    code, out, _ = invoke(
        capsys,
        "vc",
        "review",
        "--minutes",
        "60",
        "--mode",
        "custom",
        "--today",
        "2026-11-02",
        "--json",
        "--home",
        home,
    )
    assert code == 0
    session = json.loads(out)
    assert session["total"] == min(100, len(load_content().cards) + 1)
