from __future__ import annotations

import json
from pathlib import Path

import pytest

import nage


def run_json(capsys: pytest.CaptureFixture[str], *argv: str) -> dict:
    assert nage.main(["--json", *argv]) == 0
    return json.loads(capsys.readouterr().out)


def test_finance_operation_is_whitelisted(capsys: pytest.CaptureFixture[str]) -> None:
    payload = run_json(capsys, "finance", "future_value", "pv=100", "rate=0.1", "periods=2")
    assert payload["operation"] == "future_value"
    assert payload["result"] == pytest.approx(121.0)


def test_math_accepts_comma_separated_values(capsys: pytest.CaptureFixture[str]) -> None:
    payload = run_json(capsys, "math", "mean", "values=1,2,3")
    assert payload["result"] == pytest.approx(2.0)


def test_arbitrary_operation_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert nage.main(["finance", "__import__"]) == 2
    captured = capsys.readouterr()
    assert "opération inconnue" in captured.err
    assert "Autorisées" in captured.err


def test_plan_serializes_tasks_and_respects_capacity(capsys: pytest.CaptureFixture[str]) -> None:
    payload = run_json(
        capsys,
        "plan",
        "--minutes",
        "60",
        "--today",
        "2026-11-01",
        "--task",
        "NPV|2026-11-02|45|1",
        "--task",
        "Révisions|2026-11-03|30|2",
    )
    assert payload["day_date"] == "2026-11-01"
    assert [task["title"] for task in payload["tasks"]] == ["NPV"]
    assert payload["total_minutes"] == 45


def test_budget_add_then_report_stays_in_given_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    run_json(capsys, "budget", "--ledger", str(ledger), "add", "income", "1200", "Stage")
    run_json(
        capsys,
        "budget",
        "--ledger",
        str(ledger),
        "add",
        "expense",
        "200",
        "Loyer",
        "--category",
        "logement",
    )
    payload = run_json(capsys, "budget", "--ledger", str(ledger), "report", "--month", "2026-11")
    assert payload["report"]["income"] == 1200.0
    assert payload["report"]["expense"] == 200.0
    assert payload["report"]["income_expense_diff"] == 1000.0
    assert ledger.exists()


def test_default_ledger_is_outside_the_repository() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    assert repo_root not in nage.DEFAULT_LEDGER.parents


def test_research_keeps_placeholder_for_empty_section(capsys: pytest.CaptureFixture[str]) -> None:
    payload = run_json(
        capsys,
        "research",
        "--topic",
        "Finance durable",
        "--section",
        "Introduction",
        "--section",
        "",
        "--fact",
        "La BCE publie un rapport annuel",
    )
    assert payload["sections"][1]["placeholder"] is True
    assert payload["checks"]


def test_homework_returns_method_not_final_answer(capsys: pytest.CaptureFixture[str]) -> None:
    payload = run_json(capsys, "homework", "--type", "npv", "--level", "master")
    assert payload["problem_type"] == "npv"
    assert payload["steps"]
    assert "réponse finale" in payload["note"]
    assert "result" not in payload
