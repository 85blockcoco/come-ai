from academics.vc.models import Card
from academics.vc.scheduler import start_session, submit_review, summarize_session
from academics.vc.storage import VCStore


def _store(tmp_path):
    store = VCStore(tmp_path / "vc")
    store.save_cards([
        Card("pm", "valuation", "How do you get post-money?", "Pre-money + investment", "synthetic"),
        Card("moic", "returns", "What is MOIC?", "Distributed plus residual over paid-in", "synthetic"),
    ])
    return store


def test_session_offers_new_cards_deterministically(tmp_path):
    store = _store(tmp_path)
    session_id, cards = start_session(store, today="2026-11-02", limit=10)
    assert session_id
    assert [card.id for card in cards] == ["moic", "pm"]


def test_weak_answer_is_due_next_day_and_summary_is_honest(tmp_path):
    store = _store(tmp_path)
    _, cards = start_session(store, today="2026-11-02", limit=1)
    submit_review(store, cards[0], 2, reviewed_on="2026-11-02")
    _, due = start_session(store, today="2026-11-03", limit=10)
    assert due[0].id == cards[0].id
    summary = summarize_session(store, [cards[0].id], today="2026-11-02", session_id="synthetic")
    assert summary.answered == 1
    assert summary.mastered == 0
    assert summary.to_review == 1


def test_high_quality_card_is_not_due_immediately(tmp_path):
    store = _store(tmp_path)
    _, cards = start_session(store, today="2026-11-02", limit=1)
    submit_review(store, cards[0], 5, reviewed_on="2026-11-02")
    _, due = start_session(store, today="2026-11-03", limit=10)
    assert cards[0].id not in {card.id for card in due}


def test_session_can_focus_one_topic(tmp_path):
    store = VCStore(tmp_path)
    store.save_cards([Card("a", "valuation", "q", "a"), Card("b", "returns", "q", "a")])
    _, cards = start_session(store, today="2026-11-02", topic="valuation")
    assert [card.id for card in cards] == ["a"]


def test_session_can_focus_weak_cards(tmp_path):
    store = _store(tmp_path)
    _, cards = start_session(store, today="2026-11-02", limit=1)
    submit_review(store, cards[0], 2, reviewed_on="2026-11-02")
    _, weak = start_session(store, today="2026-11-03", weak_only=True)
    assert weak and weak[0].id == cards[0].id
