"""SPEC-005 — cockpit quotidien local (« Aujourd'hui »).

Règles testées partout :

* le calcul est **pur et déterministe** : même entrant, même sortie ;
* une donnée absente reste un inconnu affiché, jamais un chiffre inventé ;
* une ligne SQLite n'est jamais assimilée à un envoi ;
* Paris et la France sont exclus des opportunités par défaut ;
* rien n'est envoyé : ni e-mail, ni message, ni candidature.

Toutes les données sont synthétiques ; aucune base réelle n'est lue.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career.daily_digest import (
    DEFAULT_EXCLUDED_CITIES,
    DEFAULT_EXCLUDED_COUNTRIES,
    DEFAULT_TTL_SECONDS,
    EXPIRING_OFFER_WINDOW_DAYS,
    FOLLOWUP_DELAY_DAYS,
    build_daily_calendar_ics,
    compute_daily,
)
from career.daily_digest_store import DailyDigestStore, default_ttl_seconds
from career.service import CareerService
from come_ai_web import create_app

TODAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
STATIC_DIR = Path(__file__).resolve().parents[1] / "career_static"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def manual_job(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "company": "Banque Synthétique",
        "title": "Stagiaire M&A",
        "source_name": "manual",
        "source_id": "",
        "official_url": "https://careers.example.test/jobs/synthetic-42",
        "job_family": "M&A / Investment Banking",
        "city": "Londres",
        "country": "Royaume-Uni",
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


def job_record(job_id: str = "job-1", **changes: object) -> dict[str, object]:
    record: dict[str, object] = {
        "id": job_id,
        "company": "Goldman Sachs",
        "title": "M&A Analyst",
        "city": "Londres",
        "country": "Royaume-Uni",
        "deadline_date": "2026-10-23",
        "posted_date": "2026-10-19",
        "source_status": "open",
        "official_url": "https://careers.example.test/jobs/synthetic-1",
        "scoring": {"score": 86},
        "source_verified": True,
    }
    record.update(changes)
    return record


def application_record(
    application_id: str = "app-1",
    *,
    stage: str = "submitted",
    receipt_status: str = "not_submitted",
    events: list[dict[str, str]] | None = None,
    **changes: object,
) -> dict[str, object]:
    record: dict[str, object] = {
        "application_id": application_id,
        "job_id": "job-1",
        "stage": stage,
        "receipt_status": receipt_status,
        "company": "Goldman Sachs",
        "title": "M&A Analyst",
        "city": "Londres",
        "country": "Royaume-Uni",
        "updated_at": "2026-10-19T08:00:00+00:00",
        "events": events if events is not None else [],
    }
    record.update(changes)
    return record


def stage_event(created_at: str) -> dict[str, str]:
    return {"event_type": "stage_updated", "detail": "déclaré", "created_at": created_at}


# ---------------------------------------------------------------------------
# Contrat de la projection pure
# ---------------------------------------------------------------------------


def test_compute_daily_is_deterministic_and_pure() -> None:
    jobs = [job_record()]
    applications = [application_record(events=[stage_event("2026-10-05T09:00:00+00:00")])]
    first = compute_daily("local", today=TODAY, now=NOW, jobs=jobs, applications=applications)
    second = compute_daily("local", today=TODAY, now=NOW, jobs=jobs, applications=applications)
    assert first.to_dict() == second.to_dict()
    # Le module ne touche ni aux entrées ni à la sortie : rien n'est modifié.
    assert jobs[0]["deadline_date"] == "2026-10-23"
    payload = first.to_dict()
    for key in ("date", "urgent", "opportunities", "progression", "last_refresh", "cache_expires_at"):
        assert key in payload
    assert payload["date"] == "2026-10-20"
    assert payload["last_refresh"] == "2026-10-20T08:00:00Z"
    # Cache de 4 heures par défaut.
    assert payload["cache_expires_at"] == "2026-10-20T12:00:00Z"
    assert payload["ttl_seconds"] == DEFAULT_TTL_SECONDS


def test_expiring_offer_is_urgent_with_an_action() -> None:
    digest = compute_daily(
        "local",
        today=TODAY,
        now=NOW,
        jobs=[job_record(deadline_date="2026-10-23")],
    )
    assert len(digest.urgent) == 1
    item = digest.urgent[0]
    assert item["type"] == "expiring_offer"
    assert item["offer_id"] == "job-1"
    assert item["employer"] == "Goldman Sachs"
    assert item["deadline_date"] == "2026-10-23"
    assert item["days_left"] == 3
    assert 0 < item["days_left"] <= EXPIRING_OFFER_WINDOW_DAYS
    assert item["match_score"] == 86
    assert item["action_label"] == "Candidater avant clôture"
    assert item["action_url"].startswith("/api/career/jobs/")
    assert item["is_email"] is False


def test_offer_outside_the_urgent_window_is_not_urgent() -> None:
    digest = compute_daily(
        "local",
        today=TODAY,
        now=NOW,
        jobs=[job_record(deadline_date="2026-11-30")],
    )
    assert digest.urgent == []
    # Une échéance dépassée ne devient jamais une date inventée.
    past = compute_daily(
        "local",
        today=TODAY,
        now=NOW,
        jobs=[job_record(deadline_date="2026-10-01")],
    )
    assert past.urgent == []


def test_unknown_deadline_is_an_unknown_not_an_invented_date() -> None:
    digest = compute_daily(
        "local",
        today=TODAY,
        now=NOW,
        jobs=[job_record(deadline_date="")],
    )
    assert digest.urgent == []
    assert any("date limite" in note for note in digest.notes)


def test_closed_and_already_tracked_offers_are_not_urgent() -> None:
    closed = compute_daily(
        "local",
        today=TODAY,
        now=NOW,
        jobs=[job_record(source_status="closed")],
    )
    assert closed.urgent == []
    tracked = compute_daily(
        "local",
        today=TODAY,
        now=NOW,
        jobs=[job_record(application={"id": "app-9", "stage": "submitted"})],
        applications=[application_record("app-9", stage="submitted")],
    )
    assert tracked.urgent == []


def test_followup_due_after_the_respiration_delay() -> None:
    application = application_record(
        events=[stage_event("2026-10-05T09:00:00+00:00")],
    )
    digest = compute_daily("local", today=TODAY, now=NOW, applications=[application])
    assert len(digest.urgent) == 1
    item = digest.urgent[0]
    assert item["type"] == "followup_due"
    assert item["application_id"] == "app-1"
    assert item["offer_title"] == "M&A Analyst"
    assert item["sent_date"] == "2026-10-05"
    assert item["days_since_sent"] == 15
    assert item["days_since_sent"] >= FOLLOWUP_DELAY_DAYS
    assert item["suggested_followup_date"] == "2026-10-15"
    assert item["status"] == "due"
    assert item["action_label"] == "Relancer"
    assert item["is_email"] is False


def test_followup_is_shown_three_days_before_the_reasonable_date() -> None:
    """Le cockpit prépare la relance en avance, sans jamais l'envoyer."""

    application = application_record(events=[stage_event("2026-10-13T09:00:00+00:00")])
    digest = compute_daily("local", today=TODAY, now=NOW, applications=[application])
    assert len(digest.urgent) == 1
    item = digest.urgent[0]
    assert item["type"] == "followup_due"
    assert item["days_since_sent"] == 7
    # La date raisonnable reste celle du délai de respiration du radar local.
    assert item["suggested_followup_date"] == "2026-10-23"
    assert item["status"] == "upcoming"


def test_followup_is_not_shown_before_the_preview_window() -> None:
    application = application_record(events=[stage_event("2026-10-18T09:00:00+00:00")])
    digest = compute_daily("local", today=TODAY, now=NOW, applications=[application])
    assert digest.urgent == []


def test_unsent_application_never_becomes_a_followup() -> None:
    application = application_record(
        stage="to_prepare",
        events=[stage_event("2026-10-01T09:00:00+00:00")],
    )
    digest = compute_daily("local", today=TODAY, now=NOW, applications=[application])
    assert digest.urgent == []


def test_unknown_receipt_is_flagged_before_any_followup() -> None:
    application = application_record(
        receipt_status="unknown",
        events=[stage_event("2026-10-01T09:00:00+00:00")],
    )
    digest = compute_daily("local", today=TODAY, now=NOW, applications=[application])
    assert [item["type"] for item in digest.urgent] == ["receipt_unknown"]
    assert digest.urgent[0]["action_label"] == "Vérifier la réception"


def test_declared_interview_is_listed_separately() -> None:
    application = application_record(
        stage="interview",
        events=[stage_event("2026-10-18T09:00:00+00:00")],
    )
    digest = compute_daily("local", today=TODAY, now=NOW, applications=[application])
    assert digest.urgent == []
    assert len(digest.interviews) == 1
    assert digest.interviews[0]["interview_date"] == "2026-10-18"
    assert digest.interviews[0]["action_label"] == "Préparer l’entretien"


# ---------------------------------------------------------------------------
# Opportunités et exclusions géographiques
# ---------------------------------------------------------------------------


def opportunity_candidate(job_id: str = "job-2", **changes: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "job_id": job_id,
        "company": "Morgan Stanley",
        "title": "Equity Research",
        "city": "Londres",
        "country": "Royaume-Uni",
        "match_score": 92,
        "mandatory_covered": 8,
        "mandatory_total": 9,
        "source_verified": True,
        "posted_date": "2026-10-19",
        "source_status": "open",
    }
    candidate.update(changes)
    return candidate


def test_opportunity_exposes_score_coverage_and_trust() -> None:
    digest = compute_daily(
        "local",
        today=TODAY,
        now=NOW,
        opportunity_candidates=[opportunity_candidate()],
    )
    assert len(digest.opportunities) == 1
    item = digest.opportunities[0]
    assert item["offer_id"] == "job-2"
    assert item["employer"] == "Morgan Stanley"
    assert item["match_score"] == 92
    assert item["mandatory_coverage"] == "8/9"
    assert item["source_trust"] == "verified"
    assert item["published_days_ago"] == 1


def test_paris_and_france_are_excluded_from_opportunities_by_default() -> None:
    candidates = [
        opportunity_candidate("job-london"),
        opportunity_candidate("job-paris", city="Paris", country="Royaume-Uni"),
        opportunity_candidate("job-france", city="Bruxelles", country="France"),
        opportunity_candidate("job-paris-fr", city="Paris, France", country="France"),
    ]
    digest = compute_daily("local", today=TODAY, now=NOW, opportunity_candidates=candidates)
    assert [item["offer_id"] for item in digest.opportunities] == ["job-london"]
    assert digest.excluded_countries == list(DEFAULT_EXCLUDED_COUNTRIES)
    assert digest.excluded_cities == list(DEFAULT_EXCLUDED_CITIES)


def test_unknown_coverage_stays_unknown() -> None:
    digest = compute_daily(
        "local",
        today=TODAY,
        now=NOW,
        opportunity_candidates=[opportunity_candidate(mandatory_covered=None, mandatory_total=None)],
    )
    assert digest.opportunities[0]["mandatory_coverage"] == "inconnue"


def test_urgent_deadline_is_never_hidden_by_the_location_filter() -> None:
    digest = compute_daily(
        "local",
        today=TODAY,
        now=NOW,
        jobs=[job_record(city="Paris", country="France", deadline_date="2026-10-21")],
    )
    assert len(digest.urgent) == 1


# ---------------------------------------------------------------------------
# Progression
# ---------------------------------------------------------------------------


def test_progression_counts_only_declared_local_actions() -> None:
    applications = [
        application_record(
            "app-sent",
            stage="submitted",
            events=[stage_event("2026-10-19T09:00:00+00:00")],
        ),
        application_record(
            "app-old",
            stage="submitted",
            events=[stage_event("2026-09-01T09:00:00+00:00")],
        ),
        application_record(
            "app-interview",
            stage="interview",
            events=[stage_event("2026-10-18T09:00:00+00:00")],
        ),
        application_record(
            "app-rejected",
            stage="rejected",
            events=[stage_event("2026-10-17T09:00:00+00:00")],
        ),
    ]
    drafts = [
        {"id": "draft-1", "job_id": "job-1", "created_at": "2026-10-19T10:00:00+00:00"},
        {"id": "draft-2", "job_id": "job-2", "created_at": "2026-09-01T10:00:00+00:00"},
    ]
    digest = compute_daily(
        "local", today=TODAY, now=NOW, applications=applications, drafts=drafts
    )
    progression = digest.progression
    assert progression["prepared_this_week"] == 1
    assert progression["sent_this_week"] == 1
    assert progression["responses_this_week"] == 1
    assert progression["interviews_this_week"] == 1
    assert progression["rejections_this_week"] == 1
    assert progression["conversion_rate"] == 1.0
    assert progression["conversion_known"] is True


def test_conversion_rate_is_unknown_without_prepared_dossiers() -> None:
    digest = compute_daily("local", today=TODAY, now=NOW)
    assert digest.progression["conversion_rate"] == 0.0
    assert digest.progression["conversion_known"] is False


# ---------------------------------------------------------------------------
# Export calendrier
# ---------------------------------------------------------------------------


def test_ics_export_contains_deadline_followup_and_recurrence() -> None:
    digest = compute_daily(
        "local",
        today=TODAY,
        now=NOW,
        jobs=[job_record("job-deadline", deadline_date="2026-10-23")],
        applications=[
            application_record(
                "app-1",
                events=[stage_event("2026-10-01T09:00:00+00:00")],
            )
        ],
    )
    calendar = build_daily_calendar_ics(digest.to_dict())
    assert calendar.startswith("BEGIN:VCALENDAR")
    assert calendar.rstrip().endswith("END:VCALENDAR")
    # L'échéance est le DTEND : la fenêtre d'action part du jour du digest.
    assert "DTEND;VALUE=DATE:20261023" in calendar
    assert "DTSTART;VALUE=DATE:20261020" in calendar
    assert "RRULE:FREQ=WEEKLY;INTERVAL=1;COUNT=4" in calendar
    assert "SUMMARY:Relance à préparer" in calendar
    # Les UID sont déterministes : réimporter le fichier met à jour les mêmes
    # événements au lieu d'en créer de nouveaux.
    assert build_daily_calendar_ics(digest.to_dict()) == calendar
    assert calendar.count("UID:come-ai-career-daily-") == 2


def test_ics_export_escapes_untrusted_text() -> None:
    digest = compute_daily(
        "local",
        today=TODAY,
        now=NOW,
        jobs=[job_record(title="M&A; Analyst, Londres\r\nX-Injected: 1")],
    )
    calendar = build_daily_calendar_ics(digest.to_dict())
    # Le retour ligne devient un échappement : aucune fausse propriété iCalendar
    # ne peut être injectée depuis un texte d'offre.
    assert "\\nX-Injected" in calendar
    assert "\r\nX-Injected" not in calendar
    assert "\\;" in calendar
    assert "\\," in calendar


# ---------------------------------------------------------------------------
# Cache local (TTL, persistance, invalidation)
# ---------------------------------------------------------------------------


def test_store_round_trip_and_expiry(tmp_path: Path) -> None:
    store = DailyDigestStore(tmp_path / "cache.json")
    moment = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
    store.write("local", {"date": "2026-10-20"}, now=moment, ttl_seconds=3600)
    entry = store.read("local", now=moment + timedelta(minutes=30))
    assert entry is not None
    assert entry["payload"]["date"] == "2026-10-20"
    assert entry["expires_at"] == "2026-10-20T09:00:00Z"
    # Une entrée expirée n'est jamais servie.
    assert store.read("local", now=moment + timedelta(hours=2)) is None


def test_store_invalidate_and_corrupted_file(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    store = DailyDigestStore(path)
    moment = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
    store.write("local", {"date": "2026-10-20"}, now=moment)
    assert store.invalidate("local") is True
    assert store.read("local", now=moment) is None
    # Un fichier illisible ne casse jamais le cockpit.
    path.write_text("{pas du json", encoding="utf-8")
    assert store.read("local", now=moment) is None
    store.write("local", {"date": "2026-10-21"}, now=moment)
    assert store.read("local", now=moment) is not None


def test_store_ttl_is_configurable(tmp_path: Path) -> None:
    store = DailyDigestStore(tmp_path / "cache.json", default_ttl_seconds=120)
    moment = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
    store.write("local", {"date": "2026-10-20"}, now=moment)
    entry = store.read("local", now=moment)
    assert entry is not None
    assert entry["ttl_seconds"] == 120


def test_default_ttl_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAREER_DAILY_DIGEST_TTL_SECONDS", "600")
    assert default_ttl_seconds() == 600
    monkeypatch.setenv("CAREER_DAILY_DIGEST_TTL_SECONDS", "valeur-invalide")
    assert default_ttl_seconds() == DEFAULT_TTL_SECONDS


# ---------------------------------------------------------------------------
# Service local
# ---------------------------------------------------------------------------


def test_service_digest_is_cached_and_refresh_invalidates(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.import_job(manual_job(deadline_date=(date.today() + timedelta(days=2)).isoformat()))
    first = service.get_daily_digest()
    assert first["cached"] is False
    second = service.get_daily_digest()
    assert second["cached"] is True
    assert second["date"] == first["date"]
    refreshed = service.refresh_daily_digest()
    assert refreshed["cached"] is False


def test_service_export_writes_a_private_calendar(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.import_job(manual_job(deadline_date=(date.today() + timedelta(days=2)).isoformat()))
    path = service.export_daily_calendar()
    assert path.exists()
    assert path.suffix == ".ics"
    assert path.parent == service.export_dir
    content = path.read_text(encoding="utf-8")
    assert content.startswith("BEGIN:VCALENDAR")
    assert "UID:come-ai-career-daily-" in content


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def test_http_daily_routes(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.import_job(manual_job(deadline_date=(date.today() + timedelta(days=2)).isoformat()))
    client = TestClient(create_app(tmp_path, agent_override=object(), career_override=service))
    payload = client.get("/api/career/daily").json()
    assert payload["date"]
    assert isinstance(payload["urgent"], list)
    assert isinstance(payload["opportunities"], list)
    assert "progression" in payload
    assert client.get("/api/career/daily").json()["cached"] is True
    refreshed = client.post("/api/career/daily/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["cached"] is False
    calendar = client.get("/api/career/daily/ics")
    assert calendar.status_code == 200
    assert calendar.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in calendar.text
    # Les chemins courts du contrat répondent la même donnée.
    assert client.get("/career/daily").json()["date"] == payload["date"]
    assert client.get("/career/daily/ics").status_code == 200


# ---------------------------------------------------------------------------
# Garde-fous de l'interface
# ---------------------------------------------------------------------------


def test_static_assets_expose_the_daily_cockpit() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "js" / "daily-digest.js").read_text(encoding="utf-8")
    assert 'id="tab-daily"' in html
    assert 'id="view-daily"' in html
    assert 'id="daily-refresh"' in html
    assert '/api/career/daily/ics' in html
    assert '/career-static/js/daily-digest.js' in html
    # Aucun envoi automatique depuis l'interface du cockpit.
    assert "mailto:" not in script
    assert "smtp" not in script.lower()
    assert "innerHTML" not in script


def test_daily_script_does_not_redeclare_career_globals() -> None:
    script = (STATIC_DIR / "js" / "daily-digest.js").read_text(encoding="utf-8")
    for forbidden in ("const $ =", "const state =", "const elements =", "function api(", "function make("):
        assert forbidden not in script


def _node() -> str:
    executable = shutil.which("node")
    if executable:
        return executable
    for candidate in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
        if Path(candidate).is_file():
            return candidate
    pytest.skip("Node absent : gardes comportementales non exécutables sur cette machine")


def test_daily_scripts_are_valid_javascript() -> None:
    for script in ("js/daily-digest.js", "career.js"):
        completed = subprocess.run(
            [_node(), "--check", str(STATIC_DIR / script)],
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert completed.returncode == 0, completed.stderr


def test_career_js_registers_the_daily_view() -> None:
    source = (STATIC_DIR / "career.js").read_text(encoding="utf-8")
    assert '"daily"' in source
    assert "loadDailyDigest" in source
    assert "careerDailyDigest" in source


DAILY_DOM_SCRIPT = r'''
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const source = fs.readFileSync(process.argv[2], "utf8");

function makeNode(tag) {
  return {
    tagName: tag,
    children: [],
    textContent: "",
    className: "",
    hidden: false,
    disabled: false,
    type: "",
    dataset: {},
    listeners: {},
    append(...nodes) { this.children.push(...nodes); },
    replaceChildren(...nodes) { this.children = nodes; },
    addEventListener(type, handler) { (this.listeners[type] = this.listeners[type] || []).push(handler); },
    click() { (this.listeners.click || []).forEach((handler) => handler({})); },
    setAttribute() {},
    removeAttribute() {},
  };
}

const registry = new Map();
["daily-loading", "daily-error", "daily-honesty", "daily-progression-metrics", "daily-urgent",
 "daily-urgent-empty", "daily-opportunities", "daily-opportunities-empty", "daily-notes",
 "daily-status", "daily-refresh"].forEach((id) => registry.set(id, makeNode("div")));

const calls = [];
let payload = {};
let failNext = false;
const api = async (url, options = {}) => {
  calls.push({ url, options });
  if (failNext) throw new Error("réseau indisponible");
  return payload;
};

const sandbox = {
  document: { createElement: makeNode, getElementById: (id) => registry.get(id) || null },
  window: {},
  api,
  setMessage: () => {},
  showView: () => {},
  console,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(source, sandbox);

function texts(node) {
  const found = node.textContent ? [node.textContent] : [];
  node.children.forEach((child) => found.push(texts(child)));
  return found.join(" | ");
}

(async () => {
  // 1. Chargement normal : la route de lecture est appelée et les cartes sont rendues.
  payload = {
    date: "2026-10-21",
    urgent: [{
      type: "expiring_offer",
      title: "M&A Analyst",
      employer: "Goldman Sachs",
      location: "Londres, Royaume-Uni",
      deadline_date: "2026-10-23",
      days_left: 2,
      match_score: 86,
      action_label: "Candidater avant clôture",
      action_url: "/api/career/jobs/123/prep",
    }],
    opportunities: [{
      offer_id: "789",
      title: "Equity Research",
      employer: "Morgan Stanley",
      location: "Londres",
      match_score: 92,
      mandatory_coverage: "8/9",
      source_trust: "verified",
      published_days_ago: 1,
      action_label: "Préparer ce dossier",
      action_url: "/api/career/jobs/789/prep",
    }],
    interviews: [],
    progression: {
      prepared_this_week: 3, sent_this_week: 1, responses_this_week: 0,
      interviews_this_week: 1, rejections_this_week: 0,
      conversion_rate: 0.25, conversion_known: true,
    },
    notes: ["Aucune échéance inconnue."],
    disclaimer: "Rien n'est envoyé.",
    cached: false,
    cache_expires_at: "2026-10-21T12:00:00Z",
  };
  await sandbox.window.careerDailyDigest.load();
  assert.strictEqual(calls[0].url, "/api/career/daily");
  assert.strictEqual(registry.get("daily-urgent").children.length, 1);
  assert.strictEqual(registry.get("daily-urgent-empty").hidden, true);
  assert.strictEqual(registry.get("daily-opportunities").children.length, 1);
  assert.strictEqual(registry.get("daily-opportunities-empty").hidden, true);
  assert.match(texts(registry.get("daily-urgent")), /Goldman Sachs/);
  assert.match(texts(registry.get("daily-urgent")), /Candidater avant clôture/);
  assert.match(texts(registry.get("daily-opportunities")), /couverture 8\/9/);
  assert.match(texts(registry.get("daily-progression-metrics")), /Dossiers préparés/);
  assert.match(texts(registry.get("daily-notes")), /Aucune échéance inconnue/);
  assert.strictEqual(registry.get("daily-loading").hidden, true);

  // 2. Journée vide : les états vides redeviennent visibles.
  payload = { date: "2026-10-21", urgent: [], opportunities: [], progression: {}, notes: [], interviews: [] };
  await sandbox.window.careerDailyDigest.load();
  assert.strictEqual(registry.get("daily-urgent").children.length, 0);
  assert.strictEqual(registry.get("daily-urgent-empty").hidden, false);
  assert.strictEqual(registry.get("daily-opportunities-empty").hidden, false);

  // 3. Le bouton « Actualiser » invalide le cache via la route de refresh.
  await sandbox.window.careerDailyDigest.refresh();
  const refresh = calls[calls.length - 1];
  assert.strictEqual(refresh.url, "/api/career/daily/refresh");
  assert.strictEqual(refresh.options.method, "POST");

  // 4. Une erreur réseau reste affichée, jamais silencieuse.
  failNext = true;
  await sandbox.window.careerDailyDigest.load();
  assert.match(registry.get("daily-error").textContent, /réseau indisponible/);
  assert.strictEqual(registry.get("daily-error").hidden, false);
  console.log("DAILY_DOM_OK");
})().catch((error) => { console.error(error); process.exit(1); });
'''


def test_daily_digest_renders_cards_without_innerhtml() -> None:
    """Le rendu du cockpit est exécuté pour de vrai dans Node (stubs DOM/API)."""

    script_path = Path(__file__).resolve().parent / "_daily_digest_dom_check.js"
    script_path.write_text(DAILY_DOM_SCRIPT, encoding="utf-8")
    try:
        completed = subprocess.run(
            [_node(), str(script_path), str(STATIC_DIR / "js" / "daily-digest.js")],
            text=True,
            capture_output=True,
            timeout=30,
        )
    finally:
        script_path.unlink(missing_ok=True)
    assert completed.returncode == 0, completed.stderr
    assert "DAILY_DOM_OK" in completed.stdout
