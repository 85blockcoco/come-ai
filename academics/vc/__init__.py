"""Coach local de révision Venture Capital.

Le package reste déterministe et hors ligne. Les supports personnels sont
chargés par l'utilisateur vers un stockage local séparé du dépôt.
"""

from .models import Card, Review, SessionSummary
from .scheduler import grade_card, start_session, submit_review
from .storage import VCStore

__all__ = ["Card", "Review", "SessionSummary", "VCStore", "grade_card", "start_session", "submit_review"]
