"""Coach local de révision Venture Capital.

Le package reste déterministe et hors ligne. Les supports personnels sont
chargés par l'utilisateur vers un stockage local séparé du dépôt.
"""

from .models import Card, Review, SessionSummary
from .scheduler import grade_card, start_session, submit_review
from .storage import VCStore
from .drills import (
    dilution,
    dpi,
    grade_numeric,
    irr,
    moic,
    option_pool_adjusted_ownership,
    ownership_after_investment,
    post_money,
    rvpi,
    tvpi,
)
from .cases import CaseGrade, CaseQuestion, CaseStudy, grade_case, seed_round_case
from .exams import ExamQuestion, ExamResult, MockExam, build_mock_exam, grade_mock_exam
from .mastery import build_radar, build_study_plan

__all__ = [
    "Card", "Review", "SessionSummary", "VCStore", "grade_card", "start_session", "submit_review",
    "post_money", "ownership_after_investment", "dilution", "option_pool_adjusted_ownership",
    "moic", "dpi", "rvpi", "tvpi", "irr", "grade_numeric",
    "CaseGrade", "CaseQuestion", "CaseStudy", "grade_case", "seed_round_case",
    "ExamQuestion", "ExamResult", "MockExam", "build_mock_exam", "grade_mock_exam",
    "build_radar", "build_study_plan",
]
