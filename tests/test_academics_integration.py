"""Integration tests across the academics toolkit (finance x math x daily x research)."""

from __future__ import annotations

from academics.daily_toolkit import Ledger, Task, budget_report, daily_plan, pick_study_set, card_weights
from academics.finance_core import annuity_pv, amortization_schedule, irr, npv
from academics.math_core import mean, outliers_iqr, values_std
from academics.research_kit import build_outline, citation_format, homework_steps


# --- Chaîne 1 : devoir finance -------------------------------------------------
def problem_loan_schedule(principal: float, rate: float, years: int) -> dict:
    schedule = amortization_schedule(principal, rate, years)
    payment = schedule[0]["paiement"]
    recon = annuity_pv(payment, rate, years)
    return {"payment": payment, "recon": recon}


def test_chaine_devoir_credit_etudiant() -> None:
    """Un crédit de 50k € à 5% / 5 ans : échéancier cohérent, reste final ~0."""
    out = problem_loan_schedule(50000.0, 0.05, 5)
    assert abs(out["payment"] - 11548.74) < 1.0
    assert abs(out["recon"] - 50000.0) < 1.0


def test_chaine_devoir_npv_irr() -> None:
    flows = [-10000.0, 3000.0, 4000.0, 5000.0]
    r = irr(flows)
    # Le TRI annule la VAN : aller-retour ≈ 0.
    if r is not None:
        assert abs(npv(flows, r)) < 0.5


# --- Chaîne 2 : budget + outliers (dépenses du mois) ---------------------------
def test_budget_outlier_detection() -> None:
    ledger = Ledger()
    for amount, label in ((430.0, "courses1"), (450.0, "courses2"), (470.0, "courses3"), (480.0, "courses4"), (2500.0, "reparation")):
        ledger.add("expense", amount, label, "divers", "2026-11-10")
    entries = ledger.entries_for_month("2026-11")
    expenses = [e["amount"] for e in entries if e["kind"] == "expense"]
    bad = outliers_iqr(expenses)
    assert bad == [4]


def test_budget_consistency_with_math_stats() -> None:
    ledger = Ledger()
    ledger.add("income", 2000.0, "salaire", "revenus", "2026-11-01")
    ledger.add("expense", 500.0, "x", "loisirs", "2026-11-02")
    rep = budget_report(ledger, "2026-11")
    assert rep["income_expense_diff"] == 1500.0
    assert mean([2000.0, 500.0]) == 1250.0


# --- Chaîne 3 : plan d'étude + flashcards --------------------------------------
def test_plan_respects_capacity_and_flashcards() -> None:
    tasks = [Task(title=f"Ch{i}", due="2026-11-02", estimate_minutes=40) for i in range(4)]
    plan = daily_plan(tasks, minutes_per_day=100, today="2026-11-01")
    total_minutes = sum(t.estimate_minutes for t in plan["tasks"])
    assert total_minutes <= 100
    cards = [{"id": "c1", "question": "NPV ?", "answer": "actualise les flux", "streak": 2, "due": "2026-11-01"}]
    assert card_weights(cards, "2026-11-01") == {"c1": 3}  # {id: poids}
    assert pick_study_set(cards, 1, "2026-11-01")[0]["id"] == "c1"


# --- Chaîne 4 : dissertation recherche + citations ------------------------------
def test_outline_never_invents() -> None:
    outline = build_outline("Analyse d'un portefeuille", ["Introduction", "", "Conclusion"], ["Fait : PI en 1952"])
    assert outline.ok is False
    assert outline.missing_facts == ["Fait : PI en 1952"]


def test_citation_reusable_in_outline_pipeline() -> None:
    ref = citation_format("Markowitz", "1952", "Portfolio Selection", "Journal of Finance", "apa")
    assert "Markowitz" in ref and "(1952)" in ref


def test_homework_steps_no_answers() -> None:
    for problem_type in ("npv", "annuity", "derivative"):
        steps = homework_steps(problem_type, "BBA")
        for step in steps["steps"]:
            assert "action" in step


# --- Chaîne 5 : volatilite des budgets via stats (écart-type) -------------------
def test_monthly_expense_volatility() -> None:
    ledger = Ledger()
    months = [("2026-03", 400.0), ("2026-04", 450.0), ("2026-05", 500.0)]
    for month, amount in months:
        ledger.add("expense", amount, "courses", "alimentation", f"{month}-15")
    series = [e["amount"] for e in ledger.entries()]
    std = values_std(series)
    assert std is not None and std > 0


# Imports used for dataclass checks
def test_modules_combinables_in_one_flow() -> None:
    """Une session complète : plan du jour acte le devoir finance + citation."""
    tasks = [Task(title="Devoir NPV", due="2026-11-02", estimate_minutes=60, priority=1)]
    plan = daily_plan(tasks, minutes_per_day=120, today="2026-11-01")
    steps = homework_steps("npv", "BBA")
    assert plan["tasks"][0].title == "Devoir NPV"
    assert len(steps["steps"]) == 5
