from academics.vc.mastery import build_radar, build_study_plan
from academics.vc.models import Card


def test_radar_keeps_untested_topics_out_of_mastery():
    cards = [Card("a", "valuation", "q", "a"), Card("b", "returns", "q", "a")]
    radar = build_radar(cards, {"a": {"quality": 5}})
    assert radar == [
        {"topic": "returns", "status": "non testé", "mastery": None, "reviews": 0},
        {"topic": "valuation", "status": "solide", "mastery": 1.0, "reviews": 1},
    ]


def test_plan_is_bounded_and_prioritizes_weak_topics():
    plan = build_study_plan([
        {"topic": "solide", "status": "solide", "mastery": 0.9},
        {"topic": "fragile", "status": "fragile", "mastery": 0.2},
        {"topic": "nouveau", "status": "non testé", "mastery": None},
    ], capacity_minutes=35)
    assert plan["planned_minutes"] <= 35
    assert plan["items"][0]["topic"] == "nouveau"
