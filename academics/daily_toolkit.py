"""Boîte à outils quotidienne (NAGE BALANCE 8H).

Trois piliers réunis en un module stdlib-only :

1. BUDGET — ``Ledger`` (livre de comptes avec persistance JSONL optionnelle),
   ``category_totals`` et ``budget_report``.
2. TÂCHES — ``Task`` (dataclass), ``prioritize_tasks`` et ``daily_plan``.
3. FLASHCARDS — ``load_cards`` / ``save_cards`` (JSONL), ``card_weights``,
   ``grade_card`` (SM-2 simplifié) et ``pick_study_set``.

Plus un point d'entrée journalier : ``daily_brief`` qui résume la journée en
un dict à 4 clés et ne lève jamais d'exception sur des données vides.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# BUDGET
# ---------------------------------------------------------------------------


def _month(date_str: str) -> str:
    """Renvoie le mois « YYYY-MM » d'une date ISO « YYYY-MM-DD »."""
    return str(date_str)[:7]


class Ledger:
    """Livre de comptes mensuel ; persistance optionnelle en JSONL.

    Chaque ligne du fichier est une entrée sérialisée ``{"kind", "amount",
    "label", "category", "date"}`` — lisible ligne par ligne et robuste
    aux lignes invalides (ignorées silencieusement).
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._entries: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                self._entries.append(entry)

    def _persist(self, entry: dict[str, Any]) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def add(
        self,
        kind: str,
        amount: float,
        label: str,
        category: str = "divers",
        date_str: str | None = None,
    ) -> dict[str, Any]:
        """Enregistre un revenu (« income ») ou une dépense (« expense »).

        Lève ``ValueError`` sur les montants négatifs, les labels vides ou
        un type d'opération inconnu.
        """
        if kind not in ("income", "expense"):
            raise ValueError(f"kind invalide : {kind!r} (income|expense)")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise ValueError(f"amount non numérique : {amount!r}")
        if amount < 0:
            raise ValueError("montant négatif refusé")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("label vide refusé")
        entry_date = date_str if date_str is not None else date.today().isoformat()
        entry = {
            "kind": kind,
            "amount": float(amount),
            "label": label.strip(),
            "category": category,
            "date": _month(entry_date) if len(entry_date) <= 7 else entry_date,
        }
        self._entries.append(entry)
        self._persist(entry)
        return entry

    def entries(self) -> list[dict[str, Any]]:
        """Toutes les entrées du livre."""
        return list(self._entries)

    def entries_for_month(self, month: str) -> list[dict[str, Any]]:
        """Entrées du mois « YYYY-MM »."""
        return [e for e in self._entries if e.get("date", "")[:7] == month]


def category_totals(ledger: Ledger, month: str) -> dict[str, dict[str, float]]:
    """Totaux par catégorie pour un mois : income, expense et net."""
    totals: dict[str, dict[str, float]] = {}
    for entry in ledger.entries_for_month(month):
        bucket = totals.setdefault(entry.get("category", "divers"), {"income": 0.0, "expense": 0.0, "net": 0.0})
        amount = float(entry.get("amount", 0.0))
        kind = entry.get("kind")
        if kind == "income":
            bucket["income"] += amount
        elif kind == "expense":
            bucket["expense"] += amount
        bucket["net"] = bucket["income"] - bucket["expense"]
    return {cat: totals[cat] for cat in sorted(totals)}


def budget_report(ledger: Ledger, month: str) -> dict[str, Any]:
    """Rapport mensuel : income_expense_diff, son % et le taux d'épargne."""
    income = 0.0
    expense = 0.0
    for entry in ledger.entries_for_month(month):
        amount = float(entry.get("amount", 0.0))
        if entry.get("kind") == "income":
            income += amount
        elif entry.get("kind") == "expense":
            expense += amount
    diff = income - expense
    pct = (abs(diff) / income * 100.0) if income else 0.0
    return {
        "month": month,
        "income": round(income, 2),
        "expense": round(expense, 2),
        "income_expense_diff": round(diff, 2),
        "income_expense_diff_pct": round(pct, 2),
        "saved_vs_earn": round((diff / income) if income else 0.0, 4),
    }


# ---------------------------------------------------------------------------
# TÂCHES
# ---------------------------------------------------------------------------


@dataclass
class Task:
    title: str
    due: str  # date ISO « YYYY-MM-DD »
    estimate_minutes: int
    priority: int = 2  # 1 = urgent, 3 = basse
    done: bool = False


def prioritize_tasks(tasks: list[Task]) -> list[Task]:
    """Tâches non terminées triées par urgence : échéance puis priorité.

    Déterministe : les ex æquo sont départagés par estimate_minutes puis
    par titre (ordre alphabétique).
    """
    pending = [t for t in tasks if not t.done]
    return sorted(pending, key=lambda t: (t.due, t.priority, t.estimate_minutes, t.title))


def daily_plan(tasks: list[Task], minutes_per_day: int = 120, today: str | None = None) -> dict[str, Any]:
    """Plan du jour : tâches non terminées tenant dans ``minutes_per_day``.

    Parcours déterministe dans l'ordre de ``prioritize_tasks`` ; une tâche
    trop longue pour la capacité restante est ignorée mais n'interrompt pas
    le remplissage. ``day_date`` = ``today`` si fourni, sinon la plus proche
    échéance, sinon chaîne vide.
    """
    pending = prioritize_tasks(tasks)
    if today is not None:
        day_date = today
    elif pending:
        day_date = min(t.due for t in pending)
    else:
        day_date = ""
    selected: list[Task] = []
    total = 0
    for task in pending:
        if total + task.estimate_minutes <= minutes_per_day:
            selected.append(task)
            total += task.estimate_minutes
    return {"day_date": day_date, "tasks": selected}


# ---------------------------------------------------------------------------
# FLASHCARDS
# ---------------------------------------------------------------------------


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise ValueError(f"date ISO invalide : {value!r}") from None


def _card_key(card: dict[str, Any], index: int, seen: set[str]) -> str:
    front = card.get("front") or card.get("id")
    key = str(front) if front else f"carte-{index}"
    while key in seen:
        key = f"{key}#{index}"
    seen.add(key)
    return key


def load_cards(path: str | Path) -> list[dict[str, Any]]:
    """Charge des flashcards depuis un fichier JSONL ; lignes invalides ignorées."""
    cards: list[dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        return cards
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            card = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(card, dict):
            cards.append(card)
    return cards


def save_cards(path: str | Path, cards: list[dict[str, Any]]) -> None:
    """Écrit les flashcards au format JSONL (une carte par ligne)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for card in cards:
            fh.write(json.dumps(card, ensure_ascii=False) + "\n")


def card_weights(cards: list[dict[str, Any]], today: str) -> dict[str, float]:
    """Poids de répétition espacée (SM-2 simplifié).

    ``weight = 1 + streak`` ; le streak repart de 0 après une erreur (via
    ``grade_card``). ``today`` fait partie de la signature pour rester
    symétrique avec ``pick_study_set`` mais n'influence pas le poids brut.
    """
    weights: dict[str, float] = {}
    seen: set[str] = set()
    for index, card in enumerate(cards):
        streak = int(card.get("streak", 0))
        weights[_card_key(card, index, seen)] = 1 + max(0, streak)
    return weights


def grade_card(card: dict[str, Any], correct: bool, today: str) -> dict[str, Any]:
    """Note une révision : streak +1 si correct, remis à 0 si erreur.

    SM-2 simplifié : en cas de succès la carte revient dans ``streak`` jours,
    en cas d'échec elle est à réviser dès aujourd'hui. Renvoie une copie.
    """
    review_date = _parse_date(today)
    new_card = dict(card)
    streak = int(card.get("streak", 0))
    reps = int(card.get("reps", 0))
    if correct:
        streak += 1
        due = review_date + timedelta(days=streak)
    else:
        streak = 0
        due = review_date
    new_card["streak"] = streak
    new_card["reps"] = reps + 1
    new_card["last_review"] = review_date.isoformat()
    new_card["due"] = due.isoformat()
    return new_card


def _is_due(card: dict[str, Any], today: date) -> bool:
    due = card.get("due")
    if not due:
        return True
    try:
        return _parse_date(str(due)) <= today
    except ValueError:
        return True


def pick_study_set(cards: list[dict[str, Any]], count: int, today: str) -> list[dict[str, Any]]:
    """Choisit ``count`` cartes à réviser parmi celles dues.

    Déterministe : poids décroissant puis clé croissante pour départager
    les ex æquo (jamais de tirage aléatoire). Renvoie des copies des cartes.
    """
    review_date = _parse_date(today)
    seen: set[str] = set()
    candidates: list[tuple[str, float, dict[str, Any]]] = []
    for index, card in enumerate(cards):
        if not _is_due(card, review_date):
            continue
        streak = int(card.get("streak", 0))
        key = _card_key(card, index, seen)
        candidates.append((key, 1 + max(0, streak), card))
    candidates.sort(key=lambda item: (-item[1], item[0]))
    return [dict(card) for _, _, card in candidates[: max(0, count)]]


# ---------------------------------------------------------------------------
# BRIEF DU JOUR
# ---------------------------------------------------------------------------


def _money_gap(ledger_month: Any, today: str) -> float:
    if isinstance(ledger_month, Ledger):
        report = budget_report(ledger_month, _month(today))
        return float(report["income_expense_diff"])
    if isinstance(ledger_month, (tuple, list)) and len(ledger_month) == 2:
        ledger, month = ledger_month
        report = budget_report(ledger, str(month))
        return float(report["income_expense_diff"])
    if isinstance(ledger_month, dict):
        income = float(ledger_month.get("income", 0.0))
        expense = float(ledger_month.get("expense", 0.0))
        return round(income - expense, 2)
    return 0.0


def _cards_due_count(cards_due: Any, today: date) -> int:
    if isinstance(cards_due, (int, float)) and not isinstance(cards_due, bool):
        return max(0, int(cards_due))
    if isinstance(cards_due, dict):
        cards_due = list(cards_due.values())
    if isinstance(cards_due, (list, tuple)):
        return sum(1 for card in cards_due if isinstance(card, dict) and _is_due(card, today))
    return 0


def daily_brief(tasks: list[Task], ledger_month: Any, cards_due: Any, now: str) -> dict[str, Any]:
    """Brief quotidien : 4 clés, jamais d'exception sur des données vides.

    ``urgent_tasks`` : tâches non terminées dues au plus tard aujourd'hui.
    ``money_gap`` : revenus − dépenses du mois (Ledger, couple
    ``(Ledger, mois)`` ou dict ``{"income", "expense"}``).
    ``study_load_minutes`` : charge planifiée du jour (capacité 120 min).
    ``cards_due_count`` : nombre de flashcards à réviser aujourd'hui.
    """
    today = str(now)[:10]
    brief: dict[str, Any] = {
        "urgent_tasks": [],
        "money_gap": 0.0,
        "study_load_minutes": 0,
        "cards_due_count": 0,
    }
    try:
        plan = daily_plan(tasks, today=today)
        brief["study_load_minutes"] = sum(t.estimate_minutes for t in plan["tasks"])
        brief["urgent_tasks"] = [
            {"title": t.title, "due": t.due, "priority": t.priority, "estimate_minutes": t.estimate_minutes}
            for t in prioritize_tasks(tasks)
            if t.due <= today
        ]
    except Exception:
        pass
    try:
        brief["money_gap"] = _money_gap(ledger_month, today)
    except Exception:
        pass
    try:
        review_date = _parse_date(today)
        brief["cards_due_count"] = _cards_due_count(cards_due, review_date)
    except Exception:
        pass
    return brief
