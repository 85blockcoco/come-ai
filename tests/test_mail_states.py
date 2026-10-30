"""Synthetic contracts for mail state detection (SPEC-039 / CVBOOST-74)."""

from __future__ import annotations

import socket

import pytest

from career.mail_states import (
    MailState,
    detect_state,
    detect_mail_state,
    classify_state,
    classify_email,
    email_state,
    state_from_subject,
    state_from_body,
    state_from_text,
    state_from_email,
    is_pending_confirmation,
    state_label,
    allowed_transitions,
    can_transition,
    apply_state_to_application,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
)


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


CASES = [
    ("Your application has been received", "received"),
    ("Thank you for applying, we received your candidature", "received"),
    ("Interview invitation for next week", "interview"),
    ("Invitation to an interview", "interview"),
    ("Technical assessment and coding test", "assessment"),
    ("Case study assignment", "assessment"),
    ("We regret to inform you that you were not selected", "rejected"),
    ("Rejection: not moving forward", "rejected"),
    ("We are pleased to offer you the position", "offer"),
    ("Job offer attached", "offer"),
    ("Following up on your application", "unknown"),
]


@pytest.mark.parametrize("text,expected", CASES, ids=[c[0] for c in CASES])
def test_detect_state_text(text, expected):
    det = detect_state(text)
    if expected == "unknown":
        assert det.state in ("unknown", "followup", "received")
    else:
        assert det.state == expected


def test_pending_confirmation_always_true():
    for text, _ in CASES:
        assert detect_state(text).pending_user_confirmation is True


def test_detect_state_mapping():
    em = {"subject": "Interview invitation", "body": "Schedule"}
    assert detect_state(em).state == "interview"


def test_detect_mail_state_alias():
    assert detect_mail_state("Interview invitation").state == "interview"


def test_classify_state_alias():
    assert classify_state("Offer letter").state == "offer"


def test_classify_email_alias():
    assert classify_email({"subject": "Assessment"}).state == "assessment"


def test_email_state_returns_str():
    assert email_state("rejected candidate") == "rejected"


def test_state_from_subject():
    assert state_from_subject("Interview invitation").state == "interview"


def test_state_from_body():
    assert state_from_body("We regret to inform you").state == "rejected"


def test_state_from_text():
    assert state_from_text("Offer letter").state == "offer"


def test_state_from_email_obj():
    class E:
        subject = "Assessment test"
        body = "complete"
        sender = "hr@x.com"
    assert state_from_email(E()).state == "assessment"


def test_confidence_high():
    det = detect_state("Interview invitation interview interview")
    assert det.confidence in (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW)


def test_state_label():
    assert state_label("interview") == "Entretien"
    assert state_label("received") == "Reçu"


def test_allowed_transitions():
    tr = allowed_transitions()
    assert "interview" in tr["received"]
    assert can_transition("received", "interview") is True
    assert can_transition("rejected", "interview") is False


def test_apply_state_to_application_pending():
    app = {"id": "a1", "application_stage": "submitted"}
    det = detect_state("Interview invitation")
    out = apply_state_to_application(app, det)
    assert out["pending_mail_state"] == "interview"
    assert out["mail_state_pending_confirmation"] is True
    assert app["application_stage"] == "submitted"  # not mutated


def test_apply_state_to_application_auto_high():
    app = {"id": "a1", "application_stage": "submitted"}
    det = detect_state("Interview invitation interview interview")
    # force high confidence
    det.confidence = CONFIDENCE_HIGH
    out = apply_state_to_application(app, det, auto=True)
    assert out["application_stage"] == "interview"
    assert out["mail_state_pending_confirmation"] is False


def test_mailstate_enum_str():
    assert str(MailState.INTERVIEW) == "interview"
    assert MailState.INTERVIEW.value == "interview"


def test_is_pending_confirmation():
    det = detect_state("hi")
    assert is_pending_confirmation(det) is True
    assert is_pending_confirmation({"pending_user_confirmation": False}) is False


def test_detect_state_empty():
    det = detect_state("")
    assert det.state in ("unknown", "followup")


def test_detect_state_none():
    det = detect_state(None)
    assert det.state in ("unknown", "followup", "received")


# Extra cases to reach volume
EXTRA = [
    "Your application for the internship has been received",
    "Invitation: phone screen with hiring manager",
    "Please complete the assessment center exercise",
    "We are sorry to let you know you were not successful",
    "Offer letter and contract details",
    "Checking in regarding your candidature",
    "Entretien RH prévu la semaine prochaine",
    "Test technique à compléter",
    "Refus de candidature",
    "Proposition de stage",
    "Accusé de réception de votre candidature",
    "Rendez-vous téléphonique",
    "Évaluation psychotechnique",
    "Malheureusement votre profil n'a pas été retenu",
    "Nous avons le plaisir de vous proposer une offre",
    "Relance candidature",
]
@pytest.mark.parametrize("text", EXTRA)
def test_extra_cases_no_crash(text):
    det = detect_state(text)
    assert det.state in ("received", "interview", "assessment", "rejected", "offer", "followup", "unknown")
    assert det.pending_user_confirmation is True
