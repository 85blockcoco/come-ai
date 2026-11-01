"""CVBOOST-09 — projection locale déterministe des candidatures et radar de relance.

Règle centrale testée partout : une ligne SQLite n'est jamais assimilée à un
envoi. Toutes les données sont synthétiques ; aucun e-mail, message ou
formulaire n'est envoyé et aucune base réelle n'est lue.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career import application_dashboard as dashboard_module
from career.application_dashboard import (
    CHECKLIST_EVENT_TYPE,
    MAX_DASHBOARD_APPLICATIONS,
    PROJECT_CHECKLIST_ITEMS,
    application_entry,
    checklist_state,
    deadline_bucket,
    followup_bucket,
    parse_event_timestamp,
)
from career.calendar_export import build_deadline_calendar_ics
from career.service import CareerService
from come_ai_web import create_app
from workspace_core import UserFacingError

TODAY = date(2026, 10, 20)


def manual_job(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "company": "Banque Synthétique",
        "title": "Stagiaire M&A",
        "source_name": "manual",
        "source_id": "",
        "official_url": "https://careers.example.test/jobs/synthetic-42",
        "job_family": "M&A / Investment Banking",
        "city": "Paris",
        "country": "France",
        "posted_date": "2026-10-01",
        "deadline_date": "2026-12-15",
        "start_date": "2027-02-01",
        "end_date": "2027-05-31",
        "duration_months": 4,
        "source_status": "open",
        "requirements": "Excel modelling.\nEnglish fluency.",
        "description_original": "Stage de quatre mois.",
    }
    payload.update(changes)
    return payload


def tracked_application(tmp_path: Path, **job_changes: object) -> tuple[CareerService, dict, dict]:
    service = CareerService(tmp_path)
    job = service.import_job(manual_job(**job_changes))
    application = service.create_application(job["id"])
    return service, job, application


# ---------------------------------------------------------------------------
# Fuseaux, événements et checklist
# ---------------------------------------------------------------------------

def test_event_timestamps_mixed_offsets_are_normalized_to_utc() -> None:
    aware_paris = parse_event_timestamp("2026-10-20T12:00:00+02:00")
    aware_utc = parse_event_timestamp("2026-10-20T10:00:00+00:00")
    naive = parse_event_timestamp("2026-10-20T10:00:00")
    assert aware_paris is not None and aware_utc is not None and naive is not None
    # 12h00 à Paris vaut 10h00 UTC : jamais un jour d'écart entre deux fuseaux.
    assert aware_paris == aware_utc
    # Un horodatage historique sans fuseau est interprété comme UTC, jamais
    # comparé à l'heure locale du serveur.
    assert naive.tzinfo == timezone.utc
    assert parse_event_timestamp("pas-une-date") is None
    assert parse_event_timestamp("") is None
    assert parse_event_timestamp(None) is None


def test_checklist_state_reads_the_latest_event_and_tolerates_garbled_detail() -> None:
    events = [
        {"event_type": CHECKLIST_EVENT_TYPE, "detail": '{"items": {"cv_reviewed": true, "letter_customized": false}}', "created_at": "2026-10-01T09:00:00+00:00"},
        {"event_type": "stage_updated", "detail": "", "created_at": "2026-10-02T09:00:00+00:00"},
        {"event_type": CHECKLIST_EVENT_TYPE, "detail": '{"checked": ["cv_reviewed", "documents_checked"]}', "created_at": "2026-10-10T08:00:00+00:00"},
    ]
    state = checklist_state(events)
    assert state is not None
    # Le dernier événement gagne : la checklist reste rejouable et réversible.
    assert state["checked_keys"] == ["cv_reviewed", "documents_checked"]
    garbled = [{"event_type": CHECKLIST_EVENT_TYPE, "detail": "{pas du json", "created_at": "2026-10-03T09:00:00+00:00"}]
    assert checklist_state(garbled) is None
    assert checklist_state([{"event_type": "stage_updated", "detail": "", "created_at": "2026-10-02T09:00:00+00:00"}]) is None


def test_list_of_checklist_items_is_fixed_and_local() -> None:
    keys = {item["key"] for item in PROJECT_CHECKLIST_ITEMS}
    assert keys == {"cv_reviewed", "letter_customized", "documents_checked", "deadline_verified", "followup_planned"}
    assert "e-mail" not in " ".join(item["label"] for item in PROJECT_CHECKLIST_ITEMS).lower()


# ---------------------------------------------------------------------------
# Échéances et radar de relance (projections pures)
# ---------------------------------------------------------------------------

def test_deadline_bucket_covers_known_passed_soon_unknown_and_closed() -> None:
    assert deadline_bucket("2026-12-15", TODAY, "open") == "later"
    assert deadline_bucket("2026-10-24", TODAY, "open") == "soon"
    assert deadline_bucket("2026-10-13", TODAY, "open") == "passed"
    assert deadline_bucket("", TODAY, "open") == "unset"
    assert deadline_bucket("2026-12-15", TODAY, "closed") == "closed"
    assert deadline_bucket("date-invalide", TODAY, "open") == "unset"


def test_followup_bucket_for_waited_submission_is_overdue() -> None:
    last_event = datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc)
    bucket = followup_bucket(
        stage="submitted",
        sent_declared=True,
        receipt_status="unknown",
        approval_granted=True,
        deadline_date="2026-12-15",
        today=TODAY,
        last_event=last_event,
    )
    assert bucket["kind"] == "followup"
    assert bucket["status"] == "due"
    assert bucket["receipt_unknown"] is True
    # Délai de 10 jours : 5 oct. + 10 j = 15 oct., déjà dépassé → relance passée.
    assert bucket["suggested_date"] == "2026-10-15"
    assert bucket["waiting_days"] == 15
    assert bucket["is_email"] is False


def test_followup_bucket_not_yet_time_and_pre_submission_rules() -> None:
    recent = datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)
    upcoming = followup_bucket(
        stage="submitted_confirmed",
        sent_declared=True,
        receipt_status="confirmed",
        approval_granted=True,
        deadline_date="",
        today=TODAY,
        last_event=recent,
    )
    assert upcoming["kind"] == "followup"
    assert upcoming["status"] == "upcoming"
    assert upcoming["suggested_date"] == "2026-10-28"
    assert upcoming["waiting_days"] == 2

    # Dossier pas encore envoyé : aucune relance vers un employeur, seulement
    # une reprise locale du dossier.
    review = followup_bucket(
        stage="to_prepare",
        sent_declared=False,
        receipt_status="not_submitted",
        approval_granted=False,
        deadline_date="",
        today=TODAY,
        last_event=recent,
    )
    assert review["kind"] == "review"
    assert review["is_email"] is False

    deadline_soon = followup_bucket(
        stage="ready_to_apply",
        sent_declared=False,
        receipt_status="not_submitted",
        approval_granted=False,
        deadline_date="2026-10-24",
        today=TODAY,
        last_event=recent,
    )
    assert deadline_soon["kind"] == "deadline_close"
    # Limite - 3 jours, jamais dans le passé.
    assert deadline_soon["suggested_date"] == "2026-10-21"

    # Rejetée : plus rien à relancer.
    closed = followup_bucket(
        stage="rejected",
        sent_declared=False,
        receipt_status="not_submitted",
        approval_granted=False,
        deadline_date="2026-10-24",
        today=TODAY,
        last_event=recent,
    )
    assert closed["kind"] == "none"


def test_entry_prep_score_shows_three_factors_and_formula(tmp_path: Path) -> None:
    service, job, application = tracked_application(tmp_path)
    events = service.get_application(str(application["id"]))["events"]
    entry = application_entry(
        application,
        events,
        job,
        {"skills": "Excel modelling, valuation", "experience": "", "education": "", "languages": "English C1", "eligibility": ""},
        {},
        today=TODAY,
    )
    prep = entry["prep"]
    assert prep["scale"] == "0-100"
    assert prep["formula"].lower().startswith("note")
    assert set(prep["factors"]) <= {"couverture", "faits", "checklist"}
    # Profil partiel : aucun chiffre inventé, les facteurs inconnus sont nommés.
    if prep["partial"]:
        assert prep["unknowns"]
    assert prep["score"] is None or 0 <= prep["score"] <= 100


# ---------------------------------------------------------------------------
# Service : transitions, retour arrière, doublons, filtres
# ---------------------------------------------------------------------------

def test_dashboard_counts_transitions_and_going_back(tmp_path: Path) -> None:
    service, job, application = tracked_application(tmp_path)
    payload = service.application_dashboard()
    assert payload["counts_by_stage"]["to_review"] == 1
    service.update_application_stage(application["id"], "ready_to_apply", "dossier relu")
    service.update_application_stage(application["id"], "to_prepare", "retour arrière volontaire")
    events = service.get_application(application["id"])["events"]
    assert [event["event_type"] for event in events] == ["stage_updated", "stage_updated", "application_created"]
    payload = service.application_dashboard()
    assert payload["counts_by_stage"]["to_prepare"] == 1
    timeline_types = [item["event_type"] for item in payload["entries"][0]["timeline"]]
    # La chronologie garde l'historique dans les deux sens, jamais un écrasement.
    assert timeline_types.count("stage_updated") == 2


def test_duplicate_application_keeps_a_single_dashboard_line(tmp_path: Path) -> None:
    service, job, _ = tracked_application(tmp_path)
    repeat = service.create_application(job["id"])
    assert repeat["created"] is False
    payload = service.application_dashboard()
    assert len(payload["entries"]) == 1
    assert payload["totals"]["total"] == 1


def test_invalid_stage_and_unapproved_submission_are_rejected(tmp_path: Path) -> None:
    service, job, application = tracked_application(tmp_path)
    with pytest.raises(UserFacingError):
        service.update_application_stage(application["id"], "statu-fantome")
    with pytest.raises(UserFacingError):
        service.update_application_stage(application["id"], "submitted")


def test_filters_reduce_visible_entries_without_touching_counters(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job_a = service.import_job(manual_job())
    job_b = service.import_job(manual_job(
        title="Stagiaire Quant", company="Fonds Delta", deadline_date="",
        official_url="https://careers.example.test/jobs/synthetic-quant",
    ))
    service.create_application(job_a["id"])
    other = service.create_application(job_b["id"])
    service.update_application_stage(other["id"], "rejected", "hors critères")
    payload = service.application_dashboard()
    assert payload["counts_by_stage"]["rejected"] == 1
    assert payload["counts_by_stage"]["to_review"] == 1
    assert len(payload["entries"]) == 2
    filtered = service.application_dashboard(stage="rejected")
    assert len(filtered["entries"]) == 1
    assert filtered["entries"][0]["stage"] == "rejected"
    assert filtered["counts_by_stage"]["to_review"] == 1
    searched = service.application_dashboard(query="delta")
    assert len(searched["entries"]) == 1
    assert searched["entries"][0]["company"] == "Fonds Delta"
    closed_only = service.application_dashboard(stage="rejected")
    assert {entry["job_id"] for entry in closed_only["entries"]} == {job_b["id"]}
    with pytest.raises(UserFacingError):
        service.application_dashboard(stage="statut-fantome")


def test_dashboard_never_presents_an_unsent_application_as_sent(tmp_path: Path) -> None:
    service, job, application = tracked_application(tmp_path)
    payload = service.application_dashboard()
    entry = payload["entries"][0]
    assert entry["sent_declared"] is False
    assert entry["receipt_status"] == "not_submitted"
    assert entry["followup"]["kind"] != "followup"
    assert "non envoyée" in payload["honesty"] or "pas envoyée" in payload["honesty"]
    assert payload["honesty"].count("envoi") >= 2


def test_receipt_confirmation_and_unknown_receipt_are_visible(tmp_path: Path) -> None:
    service, job, application = tracked_application(tmp_path)
    service.approve_for_manual_submission(application["id"], True, "relu et prêt")
    service.update_application_stage(application["id"], "submitted", "dépôt du Fond Candidature")
    service.mark_receipt_unknown(application["id"], "aucune trace trouvée")
    entry = service.application_dashboard()["entries"][0]
    assert entry["receipt_status"] == "unknown"
    assert entry["action_required"] is True
    assert "renvoie" in f"{entry['next_action']['label']} {entry['next_action']['detail']}".lower()
    service.confirm_receipt(application["id"], "RéfSynthétique-001")
    entry = service.application_dashboard()["entries"][0]
    assert entry["receipt_status"] == "confirmed"
    assert entry["confirmation_reference"] == "RéfSynthétique-001"


def test_unknown_deadline_redirects_toward_official_page_not_invented_date(tmp_path: Path) -> None:
    service, job, application = tracked_application(tmp_path, deadline_date="", source_status="unknown")
    entry = service.application_dashboard()["entries"][0]
    assert entry["deadline"]["bucket"] == "unset"
    assert "inconnue" in entry["next_action"]["detail"]
    assert entry["followup"]["kind"] != "deadline_close"


def test_checklist_roundtrip_updates_prep_score(tmp_path: Path) -> None:
    service, job, application = tracked_application(tmp_path)
    before = service.application_dashboard()["entries"][0]
    assert before["checklist"]["unknown"] is True
    result = service.set_application_checklist(application["id"], ["cv_reviewed", "letter_customized"])
    assert result["checklist"]["checked_keys"] == ["cv_reviewed", "letter_customized"]
    entry = service.application_dashboard()["entries"][0]
    assert entry["checklist"]["checked_keys"] == ["cv_reviewed", "letter_customized"]
    assert entry["checklist"]["unknown"] is False
    factor = entry["prep"]["factors"].get("checklist")
    assert factor is not None and factor["percent"] == 40
    with pytest.raises(UserFacingError):
        service.set_application_checklist(application["id"], ["case-fantome"])


def test_empty_profile_marks_prep_factors_unknown_with_explicit_reasons(tmp_path: Path) -> None:
    service, job, application = tracked_application(tmp_path)
    entry = service.application_dashboard()["entries"][0]
    prep = entry["prep"]
    assert prep["score"] is None
    reasons = " ".join(unknown["reason"].lower() for unknown in prep["unknowns"])
    assert "profil" in reasons
    assert "embauche" in f"{reasons} {prep['disclaimer']}"


# ---------------------------------------------------------------------------
# Chronologie, limite dataset, calendrier, HTTP
# ---------------------------------------------------------------------------

def test_timeline_is_bounded_and_ordered_desc(tmp_path: Path) -> None:
    service, job, application = tracked_application(tmp_path)
    for stage in ("to_prepare", "ready_to_apply", "to_prepare"):
        service.update_application_stage(application["id"], stage, "itération")
    entry = service.application_dashboard()["entries"][0]
    stamps = [item["created_at"] for item in entry["timeline"]]
    assert len(stamps) == len(set(stamps))
    assert dashboard_module.MAX_TIMELINE_EVENTS <= 50
    assert stamps == sorted(stamps, reverse=True)


def test_dashboard_row_limit_is_respected(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    for index in range(MAX_DASHBOARD_APPLICATIONS + 3):
        job = service.import_job(manual_job(
            title=f"Stage synthétique {index}",
            official_url=f"https://careers.example.test/jobs/synth-{index}",
            deadline_date="",
        ))
        service.create_application(job["id"])
    payload = service.application_dashboard()
    assert len(payload["entries"]) == MAX_DASHBOARD_APPLICATIONS
    assert payload["limits"]["max_applications"] == MAX_DASHBOARD_APPLICATIONS
    assert payload["totals"]["truncated"] is True


def test_calendar_export_ignores_submitted_application_and_unknown_deadlines(tmp_path: Path) -> None:
    service, job, application = tracked_application(tmp_path)
    calendar = build_deadline_calendar_ics(service.list_jobs(), service.list_applications())
    assert "20261215" in calendar  # échéance connue → un événement VEVENT
    service.approve_for_manual_submission(application["id"], True)
    service.update_application_stage(application["id"], "submitted", "envoyé manuellement")
    calendar = build_deadline_calendar_ics(service.list_jobs(), service.list_applications())
    assert "20261215" not in calendar  # une candidature envoyée ne crée plus d'alerte
    other = service.import_job(manual_job(title="Stage sans échéance", deadline_date=""))
    service.create_application(other["id"])
    other_calendar = build_deadline_calendar_ics(service.list_jobs(), service.list_applications())
    # Une échéance inconnue ne crée jamais d'événement inventé.
    assert other_calendar.count("UID:") == calendar.count("UID:")


def test_http_dashboard_route_precedes_parameterized_route(tmp_path: Path) -> None:
    service, job, application = tracked_application(tmp_path)
    client = TestClient(create_app(tmp_path, agent_override=object(), career_override=service))
    payload = client.get("/api/career/applications/dashboard").json()
    assert payload["counts_by_stage"]["to_review"] == 1
    single = client.get(f"/api/career/applications/{application['id']}")
    assert single.status_code == 200
    filtered = client.get("/api/career/applications/dashboard", params={"stage": "to_review"})
    assert filtered.status_code == 200
    assert len(filtered.json()["entries"]) == 1
    assert client.get("/api/career/applications/dashboard", params={"stage": "intrus"}).status_code == 400
    checklisted = client.post(
        f"/api/career/applications/{application['id']}/checklist",
        json={"checked": ["deadline_verified"]},
    )
    assert checklisted.status_code == 200
    applied = client.get("/api/career/applications/dashboard").json()["entries"][0]["checklist"]
    assert applied["checked_keys"] == ["deadline_verified"]
    assert client.post(
        f"/api/career/applications/{application['id']}/checklist",
        json={"checked": ["intrus"]},
    ).status_code == 400


# ---------------------------------------------------------------------------
# Garde-fous statiques et comportementaux de l'interface
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).resolve().parents[1] / "career_static"


def test_ui_guards_no_new_native_prompt_and_local_copy_only() -> None:
    js = (STATIC_DIR / "career.js").read_text(encoding="utf-8")
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    # La suppression des données utilise désormais window.confirm (accessible).
    assert js.count("window.prompt") == 0
    assert 'aria-live="polite"' in html
    assert "applications-radar" in html
    assert "navigator.clipboard" in js
    assert "mailto:" not in js and "mailto:" not in html
    assert "smtp" not in js.lower() and "smtp" not in html.lower()


def _node() -> str:
    executable = shutil.which("node")
    if executable:
        return executable
    for candidate in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
        if Path(candidate).is_file():
            return candidate
    pytest.skip("Node absent : gardes comportementales non exécutables sur cette machine")


def test_radar_labels_are_honest_for_unsent_and_overdue_entries() -> None:
    source = (STATIC_DIR / "career.js").read_text(encoding="utf-8")
    function = source.split("function radarEntryText(", 1)[1].split("\nfunction renderApplicationRadar", 1)[0]
    script = r'''
const assert = require("assert");
function radarEntryText(FUNCTION
const due = radarEntryText({bucket:"followup", status:"due", draft:"brouillon", waiting_days:15, is_email:false});
assert.match(due.heading,/15 jours/);
assert.match(due.note,/aucun e-mail|aucun envoi|jamais/);
const upcoming = radarEntryText({bucket:"followup", status:"upcoming", draft:"brouillon", suggested_date:"2026-10-28", waiting_days:2, is_email:false});
assert.match(upcoming.heading,/relance|2026-10-28/);
const deadline = radarEntryText({bucket:"deadline_close", status:"due", draft:"note", suggested_date:"2026-10-21", is_email:false});
assert.match(deadline.heading,/date limite|finalise/i);
'''.replace("FUNCTION", function)
    completed = subprocess.run([_node(), "-e", script], text=True, capture_output=True, timeout=8)
    assert completed.returncode == 0, completed.stderr
