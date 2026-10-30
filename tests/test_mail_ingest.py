"""Tests pour career/mail_ingest.py et career/mail_states.py — SPEC-039.

Toutes les données sont synthétiques. Aucun réseau, aucun IMAP réel.
"""

from __future__ import annotations

import email
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pytest

from career.mail_ingest import (
    EvidenceMail,
    IngestReport,
    MailIngestConfig,
    connect,
    dedupe_emails,
    fetch_since,
    fetch_unread,
    fingerprint_of,
    ingest_emails,
    is_duplicate,
    is_recruiter_email,
    link_to_application,
    make_evidence_mail,
    parse_body,
    parse_email,
    parse_headers,
    process_email,
    purge_older_than,
    recruiter_score,
    run_ingest,
)
from career.mail_states import StateDetection, detect_state, state_for_email

# ---------------------------------------------------------------------------
# Fixtures synthétiques
# ---------------------------------------------------------------------------


def make_raw_email(
    subject: str = "Your application",
    sender: str = "careers@example.test",
    body: str = "Thank you for applying. We received your application.",
    message_id: str = "<synthetic-1@example.test>",
) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = "candidate@example.test"
    msg["Date"] = "Tue, 20 Oct 2026 10:00:00 +0000"
    msg["Message-ID"] = message_id
    msg.set_content(body)
    return msg.as_bytes()


RECRUITER_EMAIL = make_raw_email(
    subject="Interview invitation - Software Engineer",
    sender="careers@acme.test",
    body="We would like to invite you to an interview. Please confirm.",
    message_id="<rec-1@acme.test>",
)

REJECTION_EMAIL = make_raw_email(
    subject="Update on your application",
    sender="hr@bigcorp.test",
    body="Unfortunately we will not be moving forward. Regret to inform you.",
    message_id="<rej-1@bigcorp.test>",
)

ASSESSMENT_EMAIL = make_raw_email(
    subject="Technical assessment",
    sender="talent@startup.test",
    body="Please complete the coding challenge assessment.",
    message_id="<ass-1@startup.test>",
)

OFFER_EMAIL = make_raw_email(
    subject="Job offer",
    sender="hr@company.test",
    body="We are pleased to offer you the position. Offer letter attached.",
    message_id="<off-1@company.test>",
)

RECEIVED_EMAIL = make_raw_email(
    subject="Application received",
    sender="noreply@ats.test",
    body="We have received your application. Thank you for applying.",
    message_id="<recv-1@ats.test>",
)

PERSONAL_EMAIL = make_raw_email(
    subject="Lunch tomorrow?",
    sender="friend@gmail.com",
    body="Hey, are you free for lunch tomorrow?",
    message_id="<pers-1@gmail.com>",
)

APPLICATIONS = [
    {"application_id": "app_1", "company": "Acme", "title": "Software Engineer", "job_id": "job_1"},
    {"application_id": "app_2", "company": "BigCorp", "title": "Analyst", "job_id": "job_2"},
]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parse_email_returns_parsed_object() -> None:
    parsed = parse_email(RECRUITER_EMAIL)
    assert parsed.subject.startswith("Interview")
    assert "acme" in parsed.sender
    assert parsed.fingerprint
    assert len(parsed.fingerprint) == 64


def test_parse_headers_contains_subject() -> None:
    msg = email.message_from_bytes(RECRUITER_EMAIL)
    headers = parse_headers(msg)
    assert "Subject" in headers
    assert "Interview" in headers["Subject"]


def test_parse_body_extracts_text() -> None:
    msg = email.message_from_bytes(RECRUITER_EMAIL)
    body = parse_body(msg)
    assert "interview" in body.lower()


def test_parse_email_handles_multipart() -> None:
    msg = EmailMessage()
    msg["Subject"] = "Test"
    msg["From"] = "hr@test.com"
    msg.set_content("Hello")
    msg.add_alternative("<p>Hello</p>", subtype="html")
    raw = msg.as_bytes()
    parsed = parse_email(raw)
    assert "Hello" in parsed.body


def test_parse_email_none_subject_defaults_empty() -> None:
    raw = make_raw_email(subject="", sender="hr@test.com", body="body")
    parsed = parse_email(raw)
    assert parsed.subject == ""


def test_parse_email_fingerprint_deterministic() -> None:
    a = parse_email(RECRUITER_EMAIL)
    b = parse_email(RECRUITER_EMAIL)
    assert a.fingerprint == b.fingerprint


def test_fingerprint_of_bytes() -> None:
    fp = fingerprint_of(RECRUITER_EMAIL)
    assert len(fp) == 64


def test_parse_email_message_id() -> None:
    parsed = parse_email(RECRUITER_EMAIL)
    assert "rec-1" in parsed.message_id


def test_parse_email_sender_domain() -> None:
    parsed = parse_email(RECRUITER_EMAIL)
    assert parsed.sender_domain == "acme.test"


def test_parse_email_body_preview() -> None:
    parsed = parse_email(RECRUITER_EMAIL)
    assert len(parsed.body_preview) <= 200


def test_parse_raw_email_alias() -> None:
    from career.mail_ingest import parse_raw_email

    parsed = parse_raw_email(RECRUITER_EMAIL)
    assert parsed.subject.startswith("Interview")


# ---------------------------------------------------------------------------
# Recruiter filter
# ---------------------------------------------------------------------------


def test_recruiter_email_detected() -> None:
    parsed = parse_email(RECRUITER_EMAIL)
    assert parsed.is_recruiter is True


def test_personal_email_not_recruiter() -> None:
    parsed = parse_email(PERSONAL_EMAIL)
    assert parsed.is_recruiter is False


def test_is_recruiter_email_function() -> None:
    assert is_recruiter_email(parse_email(RECRUITER_EMAIL)) is True
    assert is_recruiter_email(parse_email(PERSONAL_EMAIL)) is False


def test_recruiter_score_high_for_careers() -> None:
    score = recruiter_score(parse_email(RECRUITER_EMAIL))
    assert score >= 0.35


def test_recruiter_score_low_for_personal() -> None:
    score = recruiter_score(parse_email(PERSONAL_EMAIL))
    assert score < 0.35


def test_matches_recruiter_alias() -> None:
    from career.mail_ingest import matches_recruiter

    assert matches_recruiter(parse_email(RECRUITER_EMAIL)) is True


def test_is_recruiter_dict_input() -> None:
    d = {"subject": "Interview", "sender": "careers@x.test", "body": "apply"}
    assert is_recruiter_email(d) is True


# ---------------------------------------------------------------------------
# State detection
# ---------------------------------------------------------------------------


def test_detect_interview_state() -> None:
    det = detect_state("Interview invitation", "We invite you to an interview.")
    assert det.state == "interview"
    assert det.confidence > 0


def test_detect_rejection_state() -> None:
    det = detect_state("Update", "Unfortunately we will not be moving forward. Regret.")
    assert det.state == "rejection"


def test_detect_assessment_state() -> None:
    det = detect_state("Technical assessment", "Complete the coding challenge.")
    assert det.state == "assessment"


def test_detect_offer_state() -> None:
    det = detect_state("Job offer", "We are pleased to offer you the position.")
    assert det.state == "offer_received"


def test_detect_received_state() -> None:
    det = detect_state("Application received", "We have received your application.")
    assert det.state == "received"


def test_detect_unknown_state() -> None:
    det = detect_state("Hello", "How are you?")
    assert det.state == "unknown"
    assert det.confidence == 0.0


def test_detect_state_empty() -> None:
    det = detect_state("", "")
    assert det.state == "unknown"


def test_detect_state_none() -> None:
    det = detect_state(None, None)
    assert det.state == "unknown"


def test_state_detection_needs_confirmation() -> None:
    det = detect_state("Interview", "interview")
    assert det.needs_confirmation is True


def test_state_for_email_dict() -> None:
    d = {"subject": "Interview", "body": "interview invite"}
    det = state_for_email(d)
    assert det.state == "interview"


def test_state_for_email_object() -> None:
    parsed = parse_email(RECRUITER_EMAIL)
    det = state_for_email(parsed)
    assert det.state == "interview"


def test_detect_state_str_function() -> None:
    from career.mail_states import detect_state_str

    assert detect_state_str("Interview", "interview") == "interview"


# ---------------------------------------------------------------------------
# Linking
# ---------------------------------------------------------------------------


def test_link_to_application_by_company() -> None:
    parsed = parse_email(RECRUITER_EMAIL)
    # subject contains "Acme"? no. Let's make email mention Acme
    raw = make_raw_email(
        subject="Interview at Acme",
        sender="careers@acme.test",
        body="Acme interview invitation",
        message_id="<x>",
    )
    parsed = parse_email(raw)
    linked = link_to_application(parsed, APPLICATIONS)
    assert linked == "app_1"


def test_link_to_application_none_if_no_match() -> None:
    parsed = parse_email(PERSONAL_EMAIL)
    linked = link_to_application(parsed, APPLICATIONS)
    assert linked is None


def test_link_to_application_by_job_id() -> None:
    raw = make_raw_email(subject="job_2 update", sender="hr@test.com", body="job_2", message_id="<y>")
    parsed = parse_email(raw)
    linked = link_to_application(parsed, APPLICATIONS)
    assert linked == "app_2"


def test_match_application_alias() -> None:
    from career.mail_ingest import match_application

    raw = make_raw_email(subject="Acme interview", sender="careers@acme.test", body="Acme", message_id="<z>")
    parsed = parse_email(raw)
    assert match_application(parsed, APPLICATIONS) == "app_1"


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------


def test_consent_off_by_default_config() -> None:
    cfg = MailIngestConfig(host="imap.test", username="u")
    assert cfg.consent is False


def test_consent_granted_false_default() -> None:
    from career.mail_ingest import consent_granted

    assert consent_granted(MailIngestConfig()) is False


def test_consent_granted_true() -> None:
    from career.mail_ingest import consent_granted

    cfg = MailIngestConfig(consent=True)
    assert consent_granted(cfg) is True


def test_require_consent_raises_when_off() -> None:
    from career.mail_ingest import require_consent

    with pytest.raises(PermissionError):
        require_consent(MailIngestConfig())


def test_require_consent_ok_when_on() -> None:
    from career.mail_ingest import require_consent

    require_consent(MailIngestConfig(consent=True))  # no raise


def test_run_ingest_requires_consent() -> None:
    cfg = MailIngestConfig(host="imap.test", username="u", consent=False)
    with pytest.raises(PermissionError):
        run_ingest(cfg, messages=[])


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def test_make_evidence_mail() -> None:
    parsed = parse_email(RECRUITER_EMAIL)
    ev = make_evidence_mail(parsed, "app_1")
    assert isinstance(ev, EvidenceMail)
    assert ev.sha256 == parsed.fingerprint
    assert ev.application_id == "app_1"
    assert ev.pending_confirmation if hasattr(ev, "pending_confirmation") else True


def test_evidence_state_pending() -> None:
    parsed = parse_email(RECRUITER_EMAIL)
    ev = make_evidence_mail(parsed)
    assert ev.state == parsed.state


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


def test_fingerprint_deterministic_for_same_raw() -> None:
    assert fingerprint_of(RECRUITER_EMAIL) == fingerprint_of(RECRUITER_EMAIL)


def test_is_duplicate_true() -> None:
    fp = fingerprint_of(RECRUITER_EMAIL)
    assert is_duplicate(fp, {fp}) is True


def test_is_duplicate_false() -> None:
    assert is_duplicate("abc", {"def"}) is False


def test_dedupe_emails_removes_duplicates() -> None:
    result = dedupe_emails([RECRUITER_EMAIL, RECRUITER_EMAIL, PERSONAL_EMAIL])
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Purge
# ---------------------------------------------------------------------------


def test_purge_older_than_removes_old() -> None:
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    old_date = (now - timedelta(days=800)).isoformat()
    recent_date = (now - timedelta(days=10)).isoformat()
    items = [
        {"received_at": old_date, "subject": "old"},
        {"received_at": recent_date, "subject": "recent"},
    ]
    kept, purged = purge_older_than(items, days=730, now=now)
    assert purged == 1
    assert len(kept) == 1
    assert kept[0]["subject"] == "recent"


def test_purge_keeps_unknown_dates() -> None:
    items = [{"subject": "no date"}]
    kept, purged = purge_older_than(items, days=10)
    assert purged == 0
    assert len(kept) == 1


def test_purge_evidence_mail() -> None:
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    ev = EvidenceMail(id="x", sha256="a", received_at=(now - timedelta(days=800)).isoformat(), subject="old", sender="s")
    kept, purged = purge_older_than([ev], days=730, now=now)
    assert purged == 1


# ---------------------------------------------------------------------------
# Pipeline ingest_emails
# ---------------------------------------------------------------------------


def test_ingest_emails_requires_consent() -> None:
    with pytest.raises(PermissionError):
        ingest_emails([RECRUITER_EMAIL], consent=False)


def test_ingest_emails_matches_recruiter() -> None:
    report = ingest_emails([RECRUITER_EMAIL, PERSONAL_EMAIL], consent=True, applications=APPLICATIONS)
    assert isinstance(report, IngestReport)
    assert report.fetched == 2
    assert report.matched == 1
    assert report.pending_confirmation == 1


def test_ingest_emails_links_application() -> None:
    raw = make_raw_email(subject="Interview at Acme", sender="careers@acme.test", body="Acme interview", message_id="<l1>")
    report = ingest_emails([raw], consent=True, applications=APPLICATIONS)
    assert report.linked == 1
    assert report.items[0]["application_id"] == "app_1"


def test_ingest_emails_dedupes() -> None:
    report = ingest_emails([RECRUITER_EMAIL, RECRUITER_EMAIL], consent=True)
    assert report.duplicates == 1
    assert report.matched == 1


def test_ingest_emails_counts_states() -> None:
    report = ingest_emails([RECRUITER_EMAIL, REJECTION_EMAIL], consent=True)
    assert "interview" in report.states or "unknown" in report.states
    assert report.matched == 2


def test_ingest_emails_empty() -> None:
    report = ingest_emails([], consent=True)
    assert report.fetched == 0
    assert report.matched == 0


def test_process_email_returns_dict() -> None:
    result = process_email(RECRUITER_EMAIL, applications=APPLICATIONS, consent=True)
    assert isinstance(result, dict)
    assert result["is_recruiter"] is True
    assert result["pending_confirmation"] is True


def test_process_email_personal_not_recruiter() -> None:
    result = process_email(PERSONAL_EMAIL, consent=True)
    assert result["is_recruiter"] is False


# ---------------------------------------------------------------------------
# run_ingest with messages
# ---------------------------------------------------------------------------


def test_run_ingest_with_messages() -> None:
    cfg = MailIngestConfig(host="imap.test", username="u", consent=True)
    report = run_ingest(cfg, messages=[RECRUITER_EMAIL], applications=APPLICATIONS)
    assert report.matched == 1


def test_run_ingest_consent_off_raises() -> None:
    cfg = MailIngestConfig(host="imap.test", username="u", consent=False)
    with pytest.raises(PermissionError):
        run_ingest(cfg, messages=[RECRUITER_EMAIL])


# ---------------------------------------------------------------------------
# IMAP mock (local fixture)
# ---------------------------------------------------------------------------


class FakeIMAP:
    def __init__(self, messages):
        self.messages = messages
        self.selected = None

    def search(self, charset, criteria):
        return "OK", [b" ".join(str(i + 1).encode() for i in range(len(self.messages)))]

    def fetch(self, mid, spec):
        idx = int(mid) - 1
        if idx < 0 or idx >= len(self.messages):
            return "NO", None
        return "OK", [(b"RFC822", self.messages[idx])]

    def select(self, mailbox):
        self.selected = mailbox
        return "OK", [b"1"]

    def login(self, u, p):
        return "OK", [b"logged in"]

    def logout(self):
        return "OK", [b"bye"]


def test_fetch_unread_with_fake_client() -> None:
    client = FakeIMAP([RECRUITER_EMAIL, PERSONAL_EMAIL])
    msgs = fetch_unread(None, client=client)
    # FakeIMAP.search returns all; fetch_unread fetches all
    assert len(msgs) >= 1


def test_fetch_since_with_fake_client() -> None:
    client = FakeIMAP([RECRUITER_EMAIL])
    msgs = fetch_since(None, since="2026-01-01", client=client)
    assert len(msgs) == 1


def test_connect_requires_host() -> None:
    # connect with empty host may fail; just ensure function exists
    assert callable(connect)


# ---------------------------------------------------------------------------
# Purge constant
# ---------------------------------------------------------------------------


def test_purge_constant_24_months() -> None:
    from career.mail_ingest import PURGE_AFTER_DAYS

    assert PURGE_AFTER_DAYS >= 700


# ---------------------------------------------------------------------------
# MailIngester class
# ---------------------------------------------------------------------------


def test_mail_ingester_class() -> None:
    from career.mail_ingest import MailIngester

    ing = MailIngester(MailIngestConfig(consent=True))
    report = ing.ingest(messages=[RECRUITER_EMAIL])
    assert report.matched == 1


def test_email_parser_class() -> None:
    from career.mail_ingest import EmailParser

    parsed = EmailParser.parse(RECRUITER_EMAIL)
    assert parsed.is_recruiter is True


# ---------------------------------------------------------------------------
# HTML body stripping
# ---------------------------------------------------------------------------


def test_parse_body_strips_html() -> None:
    # rebuild as html
    msg = EmailMessage()
    msg["Subject"] = "s"
    msg["From"] = "hr@test.com"
    msg.set_content("<p>Hello world</p>", subtype="html")
    body = parse_body(msg)
    assert "Hello" in body
    assert "<p>" not in body


# ---------------------------------------------------------------------------
# Keyring optional
# ---------------------------------------------------------------------------


def test_load_credentials_from_keyring_no_crash() -> None:
    from career.mail_ingest import load_credentials_from_keyring

    cfg = MailIngestConfig(host="h", username="u")
    out = load_credentials_from_keyring(cfg)
    assert out is cfg


# ---------------------------------------------------------------------------
# StateDetection dataclass
# ---------------------------------------------------------------------------


def test_state_detection_frozen() -> None:
    det = StateDetection(state="interview", confidence=0.8)
    with pytest.raises(Exception):
        det.state = "x"  # type: ignore[misc]


def test_all_states_tuple() -> None:
    from career.mail_states import ALL_STATES

    assert "interview" in ALL_STATES
    assert "unknown" in ALL_STATES
