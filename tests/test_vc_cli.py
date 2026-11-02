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
    assert "Session active introuvable" in err


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
                "q1": "Post-money 10 M€, investisseur 20 %.",
                "q2": "2 millions d'actions nouvelles.",
                "q3": "Le runway se raccourcit et un bridge peut diluer.",
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
    assert "pas une note humaine" in result["notice"]

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
    assert "JSON invalide" in err

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
    assert "introuvable" in err


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
    assert "VC03" not in radar["untested"]

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
    assert json.loads(out)["notice"] == "non documenté"

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
