"""Structured, local numerical practice aligned with the VC 2025 past exam."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from .ingest import CorpusIndex


@dataclass(frozen=True)
class PracticeStep:
    step_id: str
    group: str
    label: str
    unit: str
    expected: float
    tolerance: float
    points: float
    explanation: str


@dataclass(frozen=True)
class PracticeCase:
    case_id: str
    exam_question: str
    title: str
    chapter: str
    prompt: str
    citation_query: str
    citation_source_contains: str
    course_query: str
    steps: tuple[PracticeStep, ...]

    @property
    def max_score(self) -> float:
        return round(sum(step.points for step in self.steps), 2)

    def public(self, citations: list[dict[str, Any]], *, stats: dict[str, Any]) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "exam_question": self.exam_question,
            "title": self.title,
            "chapter": self.chapter,
            "prompt": self.prompt,
            "max_score": self.max_score,
            "rubric": "Barème pédagogique NAGe, indicatif; le corrigé officiel ne publie pas de grille de points partiels.",
            "steps": [
                {"step_id": step.step_id, "group": step.group, "label": step.label, "unit": step.unit, "points": step.points}
                for step in self.steps
            ],
            "citations": citations,
            "stats": stats,
        }


_EXAM_SOURCE = "vc final exam 2025 solutions"

_CASES: tuple[PracticeCase, ...] = (
    PracticeCase(
        "VC25-Q16", "Q16", "VC Method : ownership requise", "TOPIC 3",
        "Un VC investit 5 M$ aujourd’hui. La sortie est estimée à 50 M$ dans 5 ans et son hurdle rate est de 40 %. Calcule le CCM requis, la valeur de sortie nécessaire pour le VC, puis sa part du capital.",
        "Palooka Products 5 million 50 million 5 years 40% hurdle 5.378 9.297 54%",
        _EXAM_SOURCE,
        "venture capital method hurdle rate cash-on-cash multiple post-money ownership formula",
        (
            PracticeStep("ccm", "1 · Rendement requis", "CCM requis", "x", 5.378, 0.02, 1.0, "CCM = (1 + hurdle rate)^n = 1,4^5 = 5,378x."),
            PracticeStep("proceeds", "2 · Part du produit de sortie", "Produit requis à la sortie", "M$", 26.89, 0.08, 1.0, "Produit revenant au VC = investissement × CCM = 5 × 5,378 = 26,89 M$."),
            PracticeStep("ownership", "3 · Ownership", "Part du capital acceptée par le VC", "%", 53.8, 0.8, 1.0, "Ownership = produit requis / valeur totale de sortie = 26,89 / 50 = 53,8 %, arrondi à 54 %."),
        ),
    ),
    PracticeCase(
        "VC25-Q17", "Q17", "Cap table fully diluted", "TOPIC 3",
        "La société a 5 millions d’actions fondateurs. Le VC investit 2 M$ sur une valorisation post-money de 8 M$. Le pool d’options doit représenter 20 % post-money. Retrouve les fractions de propriété et le nombre d’actions fully diluted.",
        "startup 5m founder shares VC invests 2m 8m post-money valuation 20% post-money options pool founders 55% 9090909",
        _EXAM_SOURCE,
        "fully diluted founder shares post-money options pool venture capital cap table",
        (
            PracticeStep("vc_ownership", "1 · Ownership", "Part du VC", "%", 25.0, 0.3, 0.6, "Part du VC = 2 / 8 = 25 %."),
            PracticeStep("founder_ownership", "1 · Ownership", "Part des fondateurs", "%", 55.0, 0.3, 0.6, "Part des fondateurs = 100 % − 25 % VC − 20 % pool = 55 %."),
            PracticeStep("total_shares", "2 · Nombre d’actions", "Total fully diluted", "millions d’actions", 9.090909, 0.02, 0.6, "Les 5 millions d’actions fondateurs représentent 55 % : total = 5 / 0,55 = 9,091 millions."),
            PracticeStep("pool_shares", "2 · Nombre d’actions", "Actions du pool", "millions d’actions", 1.818182, 0.02, 0.6, "Pool = 20 % × 9,091 = 1,818 million d’actions."),
            PracticeStep("vc_shares", "2 · Nombre d’actions", "Actions du VC", "millions d’actions", 2.272727, 0.02, 0.6, "Actions VC = 25 % × 9,091 = 2,273 millions."),
        ),
    ),
    PracticeCase(
        "VC25-Q18", "Q18", "Conversion, dilution et IRR", "TOPIC 3",
        "Miller investit 5 M$ contre 1 million d’actions préférentielles convertibles en 2 actions ordinaires chacune. Après conversion, 15 millions d’actions existent; l’IPO en émet 3 millions. Le cours de l’action à la sortie est de 25 $ après 8 ans. Calcule l’ownership puis l’IRR.",
        "Miller Venture Capital 5 million investment 8 years 1 million convertible preferred 2 common shares 15 million shares IPO 3 million 11% stock 25",
        _EXAM_SOURCE,
        "convertible preferred shares 2 common shares IPO 3 million shares 11% cash on cash IRR 8 years",
        (
            PracticeStep("converted_shares", "1 · Conversion", "Actions ordinaires après conversion", "millions d’actions", 2.0, 0.02, 0.75, "1 million d’actions préférentielles × 2 = 2 millions d’actions ordinaires."),
            PracticeStep("ipo_total", "2 · Dilution à l’IPO", "Actions après émission à l’IPO", "millions d’actions", 18.0, 0.02, 0.5, "Total après IPO = 15 + 3 = 18 millions d’actions."),
            PracticeStep("ownership", "2 · Dilution à l’IPO", "Ownership de Miller après IPO", "%", 11.1, 0.3, 0.75, "Ownership = 2 / 18 = 11,1 %."),
            PracticeStep("exit_value", "3 · Rendement", "Valeur de la participation à la sortie", "M$", 50.0, 0.5, 0.75, "Produit de sortie = 2 millions d’actions × 25 $ = 50 M$."),
            PracticeStep("ccm", "3 · Rendement", "CCM de l’investissement", "x", 10.0, 0.1, 0.5, "CCM = valeur de sortie / investissement initial = 50 / 5 = 10x."),
            PracticeStep("irr", "3 · Rendement", "IRR annuel composé", "%", 33.35, 0.8, 0.75, "IRR = CCM^(1/8) − 1 = 10^(1/8) − 1 ≈ 33,4 %, arrondi à 33 %."),
        ),
    ),
    PracticeCase(
        "VC25-Q19", "Q19", "Financements successifs et dilution à la sortie", "TOPIC 3",
        "La startup prévoit une sortie à 6 Md$ dans 7 ans. Les tours sont : Seed (1 M$ investi, multiple cible 8x), Series A (25 M$, 5x), Series B (50 M$, 4x), Series C (200 M$, 3x). Remonte les post-money à partir de la sortie, puis calcule l’ownership après chaque tour et à la sortie.",
        "startup strategic acquisition 6 billion seed 1 million target multiple 8 series A 25 5 series B 50 4 series C 200 3 fully diluted ownership founders 47",
        _EXAM_SOURCE,
        "venture capital multiple method successive rounds post-money valuation pre-money ownership dilution founder exit 47%",
        (
            PracticeStep("series_c_post", "1 · Valorisations à rebours", "Post-money Series C", "M$", 2000.0, 2.0, 0.5, "Post-money C = sortie / multiple C = 6 000 / 3 = 2 000 M$."),
            PracticeStep("series_b_post", "1 · Valorisations à rebours", "Post-money Series B", "M$", 450.0, 1.0, 0.5, "Pre-money C = 2 000 − 200 = 1 800 M$; post-money B = 1 800 / 4 = 450 M$."),
            PracticeStep("series_a_post", "1 · Valorisations à rebours", "Post-money Series A", "M$", 80.0, 0.5, 0.25, "Pre-money B = 450 − 50 = 400 M$; post-money A = 400 / 5 = 80 M$."),
            PracticeStep("seed_post", "1 · Valorisations à rebours", "Post-money Seed", "M$", 6.875, 0.05, 0.25, "Pre-money A = 80 − 25 = 55 M$; post-money Seed = 55 / 8 = 6,875 M$."),
            PracticeStep("seed_round_pct", "2 · Ownership après chaque tour", "Part Seed après le tour", "%", 14.55, 0.35, 0.25, "Ownership Seed = 1 / 6,875 = 14,55 %."),
            PracticeStep("series_a_round_pct", "2 · Ownership après chaque tour", "Part Series A après le tour", "%", 31.25, 0.35, 0.25, "Ownership A = 25 / 80 = 31,25 %."),
            PracticeStep("series_b_round_pct", "2 · Ownership après chaque tour", "Part Series B après le tour", "%", 11.11, 0.35, 0.25, "Ownership B = 50 / 450 = 11,11 %."),
            PracticeStep("series_c_round_pct", "2 · Ownership après chaque tour", "Part Series C après le tour", "%", 10.0, 0.35, 0.25, "Ownership C = 200 / 2 000 = 10 %."),
            PracticeStep("founder_exit_pct", "3 · Ownership à la sortie", "Part des fondateurs à la sortie", "%", 47.0, 0.7, 0.5, "Les fondateurs conservent successivement (1 − Seed) × (1 − A) × (1 − B) × (1 − C) ≈ 47 %."),
            PracticeStep("seed_exit_pct", "3 · Ownership à la sortie", "Part Seed à la sortie", "%", 8.0, 0.5, 0.5, "Part Seed à la sortie = 14,55 % × rétention A × rétention B × rétention C ≈ 8 %."),
            PracticeStep("series_a_exit_pct", "3 · Ownership à la sortie", "Part Series A à la sortie", "%", 25.0, 0.7, 0.5, "Part A à la sortie = 31,25 % × rétention B × rétention C = 25 %."),
            PracticeStep("series_b_exit_pct", "3 · Ownership à la sortie", "Part Series B à la sortie", "%", 10.0, 0.5, 0.5, "Part B à la sortie = 11,11 % × rétention C = 10 %."),
            PracticeStep("series_c_exit_pct", "3 · Ownership à la sortie", "Part Series C à la sortie", "%", 10.0, 0.5, 0.5, "La participation Series C est de 200 / 2 000 = 10 %; aucun tour ultérieur ne la dilue."),
        ),
    ),
)


def _parse_number(raw: Any, *, unit: str) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        has_percent = False
    elif isinstance(raw, str) and len(raw) <= 64:
        value_text = raw.strip().replace("−", "-").replace(" ", " ")
        has_percent = "%" in value_text
        value_text = re.sub(r"(?i)(millions?|m\$|usd|eur|[$€%x\s])", "", value_text)
        if not re.fullmatch(r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)", value_text):
            return None
        try:
            value = float(value_text.replace(",", "."))
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(value):
        return None
    if unit == "%" and not has_percent and abs(value) <= 1:
        value *= 100
    return round(value, 6)


def _display_expected(step: PracticeStep) -> str:
    if step.unit == "%":
        value = f"{step.expected:.2f}".rstrip("0").rstrip(".")
        return f"{value} %"
    value = f"{step.expected:.6g}"
    return f"{value} {step.unit}".strip()


class CasePracticeEngine:
    """Persist attempts locally and grade against explicit educational rubrics."""

    def __init__(self, index: CorpusIndex, db_path: str | Path):
        self.index = index
        self._lock = RLock()
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS case_practice_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, submitted_at TEXT NOT NULL,
                score REAL NOT NULL, max_score REAL NOT NULL, answers_json TEXT NOT NULL, result_json TEXT NOT NULL
            )"""
        )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _case(case_id: str) -> PracticeCase:
        for item in _CASES:
            if item.case_id == case_id:
                return item
        raise KeyError("Exercice introuvable.")

    def _citations(self, case: PracticeCase, *, reveal_excerpt: bool = False) -> list[dict[str, Any]]:
        hits = self.index.search(case.citation_query, limit=20)
        official = [hit for hit in hits if case.citation_source_contains in Path(hit.source_path).name.casefold()]
        course = self.index.search(case.course_query, limit=20, section=case.chapter)
        result: list[dict[str, Any]] = []
        for hit in (official[:1] + course[:1]):
            cite = hit.citation()
            if not reveal_excerpt:
                cite.pop("excerpt", None)
            if not any(existing["source"] == cite["source"] and existing["page"] == cite["page"] for existing in result):
                result.append(cite)
        return result

    def _stats(self, case_id: str) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT score, max_score FROM case_practice_attempts WHERE case_id=? ORDER BY id DESC",
            (case_id,),
        ).fetchall()
        scores = [float(row["score"]) for row in rows]
        max_score = float(rows[0]["max_score"]) if rows else self._case(case_id).max_score
        return {
            "attempts": len(rows),
            "best_score": max(scores) if scores else None,
            "max_score": max_score,
            "local_only": True,
        }

    def list_cases(self) -> dict[str, Any]:
        with self._lock:
            return {
                "cases": [case.public(self._citations(case), stats=self._stats(case.case_id)) for case in _CASES],
                "local_only": True,
            }

    def submit(self, case_id: str, answers: dict[str, Any]) -> dict[str, Any]:
        case = self._case(case_id)
        if not isinstance(answers, dict):
            raise ValueError("Les réponses doivent être fournies sous forme de champs numériques.")
        known_steps = {step.step_id: step for step in case.steps}
        if set(answers) - set(known_steps):
            raise ValueError("Une réponse ne correspond à aucun champ de cet exercice.")
        with self._lock:
            graded: list[dict[str, Any]] = []
            score = 0.0
            safe_answers: dict[str, float | None] = {}
            for step in case.steps:
                entered = _parse_number(answers.get(step.step_id), unit=step.unit)
                safe_answers[step.step_id] = entered
                correct = entered is not None and abs(entered - step.expected) <= step.tolerance
                awarded = step.points if correct else 0.0
                score += awarded
                graded.append({
                    "step_id": step.step_id,
                    "group": step.group,
                    "label": step.label,
                    "unit": step.unit,
                    "entered": entered,
                    "valid_number": entered is not None,
                    "correct": correct,
                    "awarded": awarded,
                    "points": step.points,
                    "expected": step.expected,
                    "expected_display": _display_expected(step),
                    "explanation": step.explanation,
                })
            max_score = case.max_score
            citations = self._citations(case, reveal_excerpt=True)
            result = {
                "case_id": case.case_id,
                "exam_question": case.exam_question,
                "score": round(score, 2),
                "max_score": max_score,
                "percent": round(score / max_score * 100) if max_score else 0,
                "rubric": "Barème pédagogique NAGe, indicatif; le corrigé officiel ne publie pas de grille de points partiels.",
                "steps": graded,
                "citations": citations,
                "local_only": True,
            }
            self._conn.execute(
                "INSERT INTO case_practice_attempts(case_id,submitted_at,score,max_score,answers_json,result_json) VALUES(?,?,?,?,?,?)",
                (case_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), score, max_score,
                 json.dumps(safe_answers, ensure_ascii=False), json.dumps(result, ensure_ascii=False)),
            )
            self._conn.commit()
            result["stats"] = self._stats(case_id)
            return result


__all__ = ["CasePracticeEngine"]
