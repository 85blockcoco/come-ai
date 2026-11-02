"""Case studies VC originaux et correction par grille explicable."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CaseQuestion:
    id: str
    prompt: str
    expected_keywords: tuple[str, ...]
    points: int


@dataclass(frozen=True)
class CaseStudy:
    id: str
    title: str
    statement: str
    questions: tuple[CaseQuestion, ...]


@dataclass(frozen=True)
class CaseGrade:
    case_id: str
    score: int
    max_score: int
    criteria: tuple[dict[str, Any], ...]
    unsupported_claims: tuple[str, ...]


def seed_round_case() -> CaseStudy:
    return CaseStudy(
        "seed-round-001",
        "Seed round — cap table et préférence de liquidation",
        "La société lève 2 M€ à une valorisation pre-money de 8 M€. Un pool d'options de 10 % est créé avant le tour. L'investisseur reçoit une préférence 1x non participating. À la sortie, la société vaut 15 M€.",
        (
            CaseQuestion("q1", "Calcule la post-money et la part de l'investisseur.", ("10", "20", "post-money"), 2),
            CaseQuestion("q2", "Explique l'effet du pool d'options sur les fondateurs.", ("10", "pool", "dilution"), 2),
            CaseQuestion("q3", "Décris le choix économique de l'investisseur à la sortie.", ("1x", "préférence", "residual"), 2),
            CaseQuestion("q4", "Compare participating et non participating.", ("participating", "non participating", "double"), 2),
            CaseQuestion("q5", "Cite les hypothèses que l'énoncé ne fournit pas.", ("absent", "hypothèse", "inconnu"), 2),
        ),
    )


def series_a_case() -> CaseStudy:
    return CaseStudy("series-a-001", "Series A — dilution et pro rata", "Une Series A finance la croissance. L'investisseur demande un droit pro rata. Les données non fournies restent à compléter.",
                     (CaseQuestion("q1", "Explique le droit pro rata.", ("pro rata", "participer"), 2),
                      CaseQuestion("q2", "Liste les données nécessaires pour calculer la dilution.", ("inconnu", "capitalisation"), 2)))


def down_round_case() -> CaseStudy:
    return CaseStudy("down-round-001", "Down round — protection anti-dilution", "Une société lève à une valorisation inférieure au tour précédent. Le mécanisme exact de protection n'est pas précisé.",
                     (CaseQuestion("q1", "Pourquoi parle-t-on de down round ?", ("valorisation", "inférieure"), 2),
                      CaseQuestion("q2", "Que faut-il vérifier avant de calculer l'ajustement ?", ("mécanisme", "inconnu"), 2)))


def liquidation_waterfall_case() -> CaseStudy:
    return CaseStudy("waterfall-001", "Liquidation waterfall — ordre de priorité", "À la sortie, plusieurs classes d'actions existent et une préférence 1x est mentionnée. Les participations exactes sont à vérifier.",
                     (CaseQuestion("q1", "Quelle classe récupère en premier ?", ("préférence", "priorité"), 2),
                      CaseQuestion("q2", "Pourquoi faut-il connaître participating ou non participating ?", ("participating", "residual"), 2)))


def grade_case(case: CaseStudy, answers: dict[str, str]) -> CaseGrade:
    criteria: list[dict[str, Any]] = []
    unsupported: list[str] = []
    total = 0
    for question in case.questions:
        answer = str(answers.get(question.id, "")).strip().casefold()
        matched = [keyword for keyword in question.expected_keywords if keyword.casefold() in answer]
        points = question.points if len(matched) >= max(1, len(question.expected_keywords) // 2) else 0
        if any(token in answer for token in ("certain", "garanti", "toujours")) and "absent" not in answer and "inconnu" not in answer:
            unsupported.append(question.id)
        total += points
        criteria.append({"question_id": question.id, "points": points, "max_points": question.points,
                         "matched": matched, "missing": [item for item in question.expected_keywords if item not in matched]})
    return CaseGrade(case.id, total, sum(question.points for question in case.questions), tuple(criteria), tuple(unsupported))
