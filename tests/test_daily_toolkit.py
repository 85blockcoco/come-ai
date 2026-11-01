"""Tests de la boîte à outils quotidienne (NAGE BALANCE 8H)."""

from __future__ import annotations

import json

from academics.daily_toolkit import (
    Ledger,
    Task,
    budget_report,
    card_weights,
    category_totals,
    daily_brief,
    daily_plan,
    grade_card,
    load_cards,
    pick_study_set,
    prioritize_tasks,
    save_cards,
)

TODAY = "2026-11-01"
NOW = "2026-11-01T08:00:00"


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def test_ledger_add_and_month_entries() -> None:
    ledger = Ledger()
    ledger.add("income", 2000, "Salaire", category="job", date_str="2026-11-05")
    ledger.add("expense", 40, "Courses", date_str="2026-11-10")
    ledger.add("expense", 15, "Frais", date_str="2026-10-31")
    assert len(ledger.entries()) == 3
    assert len(ledger.entries_for_month("2026-11")) == 2
    assert len(ledger.entries_for_month("2026-10")) == 1


def test_ledger_refuse_negative_amount() -> None:
    try:
        Ledger().add("expense", -5, "Ticket")
        raise AssertionError("ValueError attendu pour un montant négatif")
    except ValueError:
        pass


def test_ledger_refuse_empty_label() -> None:
    ledger = Ledger()
    for label in ("", "   "):
        try:
            ledger.add("expense", 5, label)
            raise AssertionError("ValueError attendu pour un label vide")
        except ValueError:
            pass


def test_ledger_refuse_bad_kind() -> None:
    try:
        Ledger().add("don", 5, "Caritatif")
        raise AssertionError("ValueError attendu pour un kind inconnu")
    except ValueError:
        pass


def test_ledger_jsonl_roundtrip(tmp_path) -> None:
    path = tmp_path / "livre.jsonl"
    ledger = Ledger(path)
    ledger.add("income", 1500, "Freelance", category="job", date_str="2026-11-03")
    ledger.add("expense", 300, "Loyer", category="logement", date_str="2026-11-04")
    reloaded = Ledger(path)
    assert len(reloaded.entries()) == 2
    assert reloaded.entries()[0]["label"] == "Freelance"
    assert reloaded.entries()[1]["amount"] == 300.0


def test_ledger_jsonl_format(tmp_path) -> None:
    path = tmp_path / "livre.jsonl"
    ledger = Ledger(path)
    ledger.add("expense", 7, "Café", date_str="2026-11-01")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["label"] == "Café"


def test_category_totals() -> None:
    ledger = Ledger()
    ledger.add("income", 1000, "Mission", category="job", date_str="2026-11-02")
    ledger.add("expense", 100, "Bus", category="transport", date_str="2026-11-03")
    ledger.add("expense", 200, "SNCF", category="transport", date_str="2026-11-04")
    totals = category_totals(ledger, "2026-11")
    assert list(totals) == ["job", "transport"]  # tri alphabétique
    assert totals["job"]["income"] == 1000
    assert totals["transport"]["expense"] == 300
    assert totals["transport"]["net"] == -300


def test_budget_report_values() -> None:
    ledger = Ledger()
    ledger.add("income", 2000, "Salaire", date_str="2026-11-01")
    ledger.add("expense", 1500, "Dépenses", date_str="2026-11-02")
    report = budget_report(ledger, "2026-11")
    assert report["income"] == 2000
    assert report["expense"] == 1500
    assert report["income_expense_diff"] == 500
    assert report["income_expense_diff_pct"] == 25.0
    assert report["saved_vs_earn"] == 0.25


def test_budget_report_zero_income() -> None:
    ledger = Ledger()
    ledger.add("expense", 50, "Courses", date_str="2026-11-01")
    report = budget_report(ledger, "2026-11")
    assert report["income_expense_diff_pct"] == 0.0
    assert report["saved_vs_earn"] == 0.0
    assert report["income_expense_diff"] == -50


# ---------------------------------------------------------------------------
# Tâches
# ---------------------------------------------------------------------------


def test_task_dataclass_defaults() -> None:
    task = Task(title="Réviser", due="2026-11-05", estimate_minutes=30)
    assert task.priority == 2
    assert task.done is False


def test_task_field_values() -> None:
    task = Task(title="Sprinter", due="2026-11-02", estimate_minutes=45, priority=1, done=True)
    assert task.priority == 1 and task.done is True and task.estimate_minutes == 45


def test_prioritize_tasks_order() -> None:
    tasks = [
        Task(title="Basse", due="2026-11-02", estimate_minutes=30, priority=3),
        Task(title="Urgente", due="2026-11-01", estimate_minutes=30, priority=2),
        Task(title="Haute", due="2026-11-01", estimate_minutes=30, priority=1),
    ]
    ordered = [t.title for t in prioritize_tasks(tasks)]
    assert ordered == ["Haute", "Urgente", "Basse"]


def test_prioritize_tasks_tiebreak_deterministic() -> None:
    tasks = [
        Task(title="Zulu", due="2026-11-01", estimate_minutes=30, priority=1),
        Task(title="Alpha", due="2026-11-01", estimate_minutes=30, priority=1),
        Task(title="Mini", due="2026-11-01", estimate_minutes=10, priority=2),
    ]
    ordered = [t.title for t in prioritize_tasks(tasks)]
    assert ordered == ["Alpha", "Zulu", "Mini"]  # priorité d'abord, puis titre
    # Idempotent : même entrée → même sortie
    assert [t.title for t in prioritize_tasks(tasks)] == ordered


def test_prioritize_tasks_excludes_done() -> None:
    tasks = [
        Task(title="Faite", due="2026-11-01", estimate_minutes=10, priority=1, done=True),
        Task(title="À faire", due="2026-11-01", estimate_minutes=10, priority=1),
    ]
    ordered = [t.title for t in prioritize_tasks(tasks)]
    assert ordered == ["À faire"]


def test_daily_plan_respects_capacity() -> None:
    tasks = [
        Task(title="A", due="2026-11-01", estimate_minutes=60, priority=1),
        Task(title="B", due="2026-11-02", estimate_minutes=90, priority=2),
        Task(title="C", due="2026-11-03", estimate_minutes=30, priority=3),
    ]
    plan = daily_plan(tasks, minutes_per_day=120)
    titles = [t.title for t in plan["tasks"]]
    assert plan["day_date"] == "2026-11-01"
    assert titles == ["A", "C"]  # B (90) dépasse la capacité restante (60)
    assert sum(t.estimate_minutes for t in plan["tasks"]) <= 120


def test_daily_plan_day_date_fallback_and_today() -> None:
    tasks = [Task(title="A", due="2026-11-05", estimate_minutes=30)]
    assert daily_plan(tasks)["day_date"] == "2026-11-05"
    assert daily_plan(tasks, today=TODAY)["day_date"] == TODAY
    empty = daily_plan([])
    assert empty["day_date"] == "" and empty["tasks"] == []


def test_daily_plan_empty_and_deterministic() -> None:
    tasks = [
        Task(title="Révision", due="2026-11-02", estimate_minutes=40, priority=1),
        Task(title="Sport", due="2026-11-01", estimate_minutes=50, priority=2),
        Task(title="Lecture", due="2026-11-03", estimate_minutes=20, priority=3),
    ]
    one = daily_plan(tasks, minutes_per_day=120, today=TODAY)
    two = daily_plan(tasks, minutes_per_day=120, today=TODAY)
    assert one == two
    assert [t.title for t in one["tasks"]] == ["Sport", "Révision", "Lecture"]


# ---------------------------------------------------------------------------
# Flashcards
# ---------------------------------------------------------------------------


def test_cards_save_load_roundtrip(tmp_path) -> None:
    path = tmp_path / "cartes.jsonl"
    cards = [
        {"front": "Q1", "back": "R1", "streak": 2, "due": "2026-11-01"},
        {"front": "Q2", "back": "R2", "streak": 0},
    ]
    save_cards(path, cards)
    loaded = load_cards(path)
    assert loaded == cards


def test_load_cards_missing_and_bad_lines(tmp_path) -> None:
    path = tmp_path / "cartes.jsonl"
    assert load_cards(path) == []
    path.write_text('{"front": "OK"}\npas du json\n{"front": "OK2"}\n\n', encoding="utf-8")
    loaded = load_cards(path)
    assert [c["front"] for c in loaded] == ["OK", "OK2"]


def test_save_cards_writes_jsonl(tmp_path) -> None:
    path = tmp_path / "cartes.jsonl"
    save_cards(path, [{"front": "A"}, {"front": "B"}])
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["front"] == "B"


def test_card_weights_formula() -> None:
    cards = [
        {"front": "Neuf", "streak": 0},
        {"front": "Confirmée", "streak": 4},
        {"front": "Sans streak"},
    ]
    weights = card_weights(cards, TODAY)
    assert weights["Neuf"] == 1
    assert weights["Confirmée"] == 5  # 1 + streak
    assert weights["Sans streak"] == 1


def test_card_weights_ignores_negative_streak() -> None:
    weights = card_weights([{"front": "Corrompue", "streak": -3}], TODAY)
    assert weights["Corrompue"] == 1


def test_grade_card_streak_up_and_due_moves() -> None:
    graded = grade_card({"front": "Q", "streak": 2}, correct=True, today="2026-11-01")
    assert graded["streak"] == 3
    assert graded["due"] == "2026-11-04"  # streak jours plus tard
    assert graded["reps"] == 1


def test_grade_card_streak_reset_on_wrong() -> None:
    graded = grade_card({"front": "Q", "streak": 5}, correct=False, today=TODAY)
    assert graded["streak"] == 0
    assert graded["due"] == TODAY  # à revoir dès aujourd'hui


def test_grade_card_does_not_mutate_input() -> None:
    original = {"front": "Q", "streak": 1}
    grade_card(original, correct=False, today=TODAY)
    assert original["streak"] == 1


def test_pick_study_set_top_weight() -> None:
    cards = [
        {"front": "Faible", "streak": 0, "due": "2026-11-01"},
        {"front": "Forte", "streak": 5, "due": "2026-11-01"},
        {"front": "Moyenne", "streak": 2, "due": "2026-11-01"},
    ]
    picked = pick_study_set(cards, 2, TODAY)
    assert [c["front"] for c in picked] == ["Forte", "Moyenne"]


def test_pick_study_set_excludes_not_due() -> None:
    cards = [
        {"front": "Future", "streak": 9, "due": "2026-12-01"},
        {"front": "Dûe aujourd'hui", "streak": 0, "due": TODAY},
    ]
    picked = pick_study_set(cards, 5, TODAY)
    assert [c["front"] for c in picked] == ["Dûe aujourd'hui"]


def test_pick_study_set_tiebreak_key_sort() -> None:
    cards = [
        {"front": "Zoé", "streak": 0},
        {"front": "Anna", "streak": 0},
        {"front": "Marc", "streak": 0},
    ]
    picked = pick_study_set(cards, 2, TODAY)
    assert [c["front"] for c in picked] == ["Anna", "Marc"]


def test_pick_study_set_count_bounds() -> None:
    cards = [{"front": "Q", "streak": 0}]
    assert pick_study_set(cards, 10, TODAY) == cards
    assert pick_study_set(cards, 0, TODAY) == []


# ---------------------------------------------------------------------------
# Daily brief
# ---------------------------------------------------------------------------


def test_daily_brief_full_case() -> None:
    ledger = Ledger()
    ledger.add("income", 2000, "Salaire", date_str="2026-11-01")
    ledger.add("expense", 1200, "Loyer", date_str="2026-11-01")
    ledger.add("expense", 300, "Courses", date_str="2026-11-01")
    tasks = [
        Task(title="Devoir de maths", due="2026-11-01", estimate_minutes=60, priority=1),
        Task(title="Révisions partiels", due="2026-11-01", estimate_minutes=45, priority=2),
        Task(title="Trop long", due="2026-11-01", estimate_minutes=200, priority=1),
        Task(title="Plus tard", due="2026-12-01", estimate_minutes=30, priority=1),
    ]
    cards = [{"front": "Q1", "streak": 1, "due": "2026-11-01"}, {"front": "Q2", "streak": 0, "due": "2026-10-15"}]
    brief = daily_brief(tasks, (ledger, "2026-11"), cards, NOW)
    assert brief["urgent_tasks"][0]["title"] == "Devoir de maths"
    assert len(brief["urgent_tasks"]) == 3
    assert brief["money_gap"] == 500
    assert brief["study_load_minutes"] == 105  # 60 + 45 (200 dépasse la capacité)
    assert brief["cards_due_count"] == 2


def test_daily_brief_accepts_budget_report_dict() -> None:
    brief = daily_brief([], {"income": 1000, "expense": 400}, [], NOW)
    assert brief["money_gap"] == 600


def test_daily_brief_accepts_ledger_instance() -> None:
    ledger = Ledger()
    ledger.add("income", 100, "Prime", date_str="2026-11-01")
    brief = daily_brief([], ledger, [], NOW)
    assert brief["money_gap"] == 100


def test_daily_brief_empty_data() -> None:
    brief = daily_brief([], {}, [], NOW)
    assert brief == {
        "urgent_tasks": [],
        "money_gap": 0.0,
        "study_load_minutes": 0,
        "cards_due_count": 0,
    }


def test_daily_brief_counts_cards_by_due_date() -> None:
    cards = [
        {"front": "Passée", "streak": 0, "due": "2026-10-30"},
        {"front": "Future", "streak": 0, "due": "2027-01-01"},
    ]
    brief = daily_brief([], {}, cards, NOW)
    assert brief["cards_due_count"] == 1
    brief_int = daily_brief([], {}, 7, NOW)
    assert brief_int["cards_due_count"] == 7
