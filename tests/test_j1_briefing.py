"""Tests SPEC-037 — briefing J-1 la veille d'un entretien.

Toutes les données sont synthétiques (``tests/fixtures/j1_synthetic.json`` ou
valeurs fabriquées dans le test) : aucune donnée réelle, aucun réseau, aucune
clé. Couvre le contrat ``BriefingDoc``, les marqueurs « À COMPLÉTER », les
coutures SPEC-031/027/028, 4 tests adversariaux et les routes REST servies par
``create_app()``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from career.j1_briefing import (
    MARKER_PREFIX,
    STAR_THRESHOLD_DEFAULT,
    BriefingDoc,
    admin_applicability,
    admin_blockers_for_job,
    briefing_for_application,
    build_j1_briefing,
    company_facts_from_job,
    cv_reread_from_prep,
    render_markdown,
    star_dimensions,
    star_worksheets_from_sessions,
    to_dict,
    top_questions_from_job,
)
from career.service import CareerService
from come_ai_web import create_app

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "j1_synthetic.json"

IMPORTABLE_OFFER_KEYS = {
    "company",
    "title",
    "source_name",
    "source_id",
    "official_url",
    "job_family",
    "city",
    "country",
    "posted_date",
    "deadline_date",
    "start_date",
    "end_date",
    "duration_months",
    "source_status",
    "employment_type",
    "role_level",
    "requirements",
    "languages_required",
    "eligibility_requirement",
    "description_original",
}


def j1_data() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class StubService:
    """CareerService en lecture seule : mêmes signatures, données fixture."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def get_application(self, application_id: str) -> dict[str, Any]:
        if application_id != self.data["application"]["id"]:
            raise KeyError(application_id)
        return dict(self.data["application"])

    def get_job(self, job_id: str) -> dict[str, Any]:
        return dict(self.data["job"])

    def get_job_prep(self, job_id: str) -> dict[str, Any]:
        return dict(self.data["prep"])

    def list_interview_sessions(self, *, limit: int = 30) -> list[dict[str, Any]]:
        # Shape réel : l'historique n'embarque PAS les réponses (turns).
        return [
            {key: value for key, value in session.items() if key != "turns"}
            for session in self.data["sessions"]
        ]

    def get_interview_session(self, session_id: str) -> dict[str, Any]:
        for session in self.data["sessions"]:
            if session["id"] == session_id:
                return dict(session)
        raise KeyError(session_id)


# ---------------------------------------------------------------------------
# Contrat BriefingDoc (agrégateur pur)
# ---------------------------------------------------------------------------

def test_contract_fields_and_to_dict_are_json_safe() -> None:
    doc = build_j1_briefing(
        "app_1",
        company_facts=["Acme — stagiaire (source : manual)"],
        top_questions=["Pourquoi Acme ?"],
        star_worksheets=[{"name": "ws1", "completeness": 0.9}],
        admin_blockers=["Visa (visa)"],
        cv_section_reread=["CV — Python [missing]"],
        admin_applicable=True,
    )
    assert isinstance(doc, BriefingDoc)
    payload = to_dict(doc)
    for key in (
        "application_id",
        "company_facts",
        "top_questions",
        "star_ready",
        "admin_blockers",
        "cv_section_reread",
        "incomplete_sections",
    ):
        assert key in payload
    assert payload["star_ready"] == ["ws1"]
    assert payload["incomplete_sections"] == []
    json.dumps(payload)  # ne lève pas


def test_star_ready_filter_marks_below_threshold_a_completer() -> None:
    doc = build_j1_briefing(
        "app_2",
        star_worksheets=[
            {"name": "ws1", "completeness": 0.9},
            {"name": "ws2", "completeness": 0.5},
        ],
    )
    assert doc.star_ready == ["ws1"]
    assert any("ws2" in entry and entry.startswith(MARKER_PREFIX) for entry in doc.incomplete_sections)


def test_every_empty_section_is_published_with_marker() -> None:
    doc = build_j1_briefing("app_3")
    assert doc.company_facts == []
    assert doc.top_questions == []
    assert doc.star_ready == []
    assert doc.cv_section_reread == []
    joined = " | ".join(doc.incomplete_sections)
    assert f"{MARKER_PREFIX} : fiche entreprise" in joined
    assert f"{MARKER_PREFIX} : questions probables" in joined
    assert f"{MARKER_PREFIX} : worksheets STAR" in joined
    assert f"{MARKER_PREFIX} : revue du CV" in joined
    # Non applicable → pas de faux blocage administratif.
    assert "SPEC-028" not in joined


def test_admin_marker_only_when_applicable() -> None:
    incomplete = build_j1_briefing("app_4", admin_applicable=True).incomplete_sections
    assert any("SPEC-028" in entry for entry in incomplete)
    assert not any("SPEC-028" in entry for entry in build_j1_briefing("app_4").incomplete_sections)


def test_cv_unavailable_vs_nothing_to_reread() -> None:
    assert any(
        "revue du CV" in entry
        for entry in build_j1_briefing("app_5").incomplete_sections
    )
    doc = build_j1_briefing("app_5", cv_section_reread=[])
    assert doc.cv_section_reread == []
    assert not any("revue du CV" in entry for entry in doc.incomplete_sections)


def test_threshold_is_sanitized() -> None:
    worksheets = [
        {"name": "haut", "completeness": 0.9},
        {"name": "bas", "completeness": 0.7},
    ]
    # Valeur par défaut (0.8).
    default_doc = build_j1_briefing("app_6", star_worksheets=worksheets)
    assert default_doc.star_ready == ["haut"]
    assert STAR_THRESHOLD_DEFAULT == 0.8
    # Seuil invalide → repli sur 0.8, jamais d'explosion.
    for bad in ("abc", float("nan"), float("inf"), -3, 42, None):
        doc = build_j1_briefing("app_6", star_worksheets=worksheets, star_completeness_threshold=bad)
        assert doc.star_ready == ["haut"], bad
    # Seuil explicite valide.
    lowered = build_j1_briefing(
        "app_6", star_worksheets=worksheets, star_completeness_threshold=0.6
    )
    assert lowered.star_ready == ["haut", "bas"]


# ---------------------------------------------------------------------------
# Fiche entreprise sourcée
# ---------------------------------------------------------------------------

def test_company_facts_cite_the_recorded_source() -> None:
    facts = company_facts_from_job(j1_data()["job"])
    assert facts
    assert any("Nexora Labs" in fact for fact in facts)
    assert all("(source : synthetic_board, https://careers.example.test/" in fact for fact in facts)
    assert any("Date limite de candidature : 2026-11-20" in fact for fact in facts)


def test_company_facts_empty_job_is_empty() -> None:
    assert company_facts_from_job(None) == []
    assert company_facts_from_job({}) == []


# ---------------------------------------------------------------------------
# Questions probables (SPEC-031 + repli local)
# ---------------------------------------------------------------------------

def test_faq_provider_is_used_when_available() -> None:
    questions = top_questions_from_job(
        j1_data()["job"], faq_provider=lambda job: ["Question injectée 1", "Question injectée 2"]
    )
    assert questions == ["Question injectée 1", "Question injectée 2"]


def test_faq_provider_failure_falls_back_to_local_questions() -> None:
    def broken(job: dict[str, Any]) -> list[str]:
        raise RuntimeError("faq indisponible")

    questions = top_questions_from_job(j1_data()["job"], faq_provider=broken)
    assert questions, "le repli local doit produire des questions déterministes"
    assert any("Nexora Labs" in question for question in questions)

    payload = briefing_for_application(
        StubService(j1_data()), j1_data()["application"]["id"], faq_provider=broken
    )
    assert payload["meta"]["questions_source"] == "local"


def test_spec031_faq_mining_drives_questions_when_present() -> None:
    pytest.importorskip("career.faq_mining")
    payload = briefing_for_application(
        StubService(j1_data()), j1_data()["application"]["id"]
    )
    assert payload["meta"]["questions_source"] == "spec-031"
    assert payload["top_questions"], "SPEC-031 doit produire des questions pour l'offre fixture"
    assert any(question.startswith("Pouvez-vous décrire") for question in payload["top_questions"])


# ---------------------------------------------------------------------------
# Worksheets STAR (séances / SPEC-027)
# ---------------------------------------------------------------------------

def test_star_dimensions_closed_lexicon() -> None:
    full = (
        "Quand j'étais en mission, mon objectif était clair ; j'ai construit le "
        "tableau de bord et livré 40 % de gain de temps."
    )
    assert star_dimensions(full) == ("situation", "task", "action", "result")
    assert star_dimensions("") == ()
    assert star_dimensions("Bonjour.") == ()


def test_worksheets_from_sessions_completeness_and_labels() -> None:
    worksheets = star_worksheets_from_sessions(j1_data()["sessions"])
    assert len(worksheets) == 3
    behavioral = next(w for w in worksheets if w["name"].startswith("Séance behavioral"))
    assert behavioral["completeness"] == 1.0
    technical = next(w for w in worksheets if w["name"].startswith("Séance technical"))
    assert technical["completeness"] == 0.0
    assert technical["dimensions"] == []


def test_worksheets_explicit_structured_input_is_kept() -> None:
    session = {
        "id": "s1",
        "mode": "technical",
        "star_worksheets": [{"name": "Worksheet SPEC-027", "completeness": 0.9}],
    }
    worksheets = star_worksheets_from_sessions([session])
    assert worksheets == [{"name": "Worksheet SPEC-027", "completeness": 0.9}]


def test_briefing_for_application_filters_sessions_and_enriches_turns() -> None:
    data = j1_data()
    payload = briefing_for_application(
        StubService(data), data["application"]["id"], admin_provider=lambda country: data["admin_checklist"]
    )
    # Seule la séance de CETTE candidature est retenue (2, pas 3).
    assert payload["meta"]["star_worksheets_count"] == 2
    assert any("Séance behavioral" in label for label in payload["star_ready"])
    assert any(marker.startswith(MARKER_PREFIX) and "Séance technical" in marker for marker in payload["incomplete_sections"])
    # Écarts du panneau de préparation → éléments à relire, sourcés par l'offre.
    assert any(entry.startswith("CV — Python [missing]") for entry in payload["cv_section_reread"])
    # Fiche entreprise sourcée.
    assert all("(source :" in fact for fact in payload["company_facts"])


def test_briefing_admin_blockers_labelled_from_checklist() -> None:
    data = j1_data()
    payload = briefing_for_application(
        StubService(data),
        data["application"]["id"],
        faq_provider=lambda job: ["Q1"],
        admin_provider=lambda country: data["admin_checklist"],
    )
    assert payload["meta"]["admin_applicable"] is True
    assert payload["meta"]["admin_country"] == "Allemagne"
    assert payload["admin_blockers"] == [
        "Autorisation de travail (work_permit)",
        "Assurance maladie (health_insurance)",
    ]
    assert not any("SPEC-028" in entry for entry in payload["incomplete_sections"])


def test_briefing_admin_without_provider_is_explicitly_incomplete() -> None:
    data = j1_data()
    payload = briefing_for_application(
        StubService(data), data["application"]["id"], faq_provider=lambda job: ["Q1"]
    )
    assert payload["meta"]["admin_applicable"] is True
    blockers = bool(payload["admin_blockers"])
    marked = any("SPEC-028" in entry for entry in payload["incomplete_sections"])
    # Jamais les deux, jamais ni l'un ni l'autre : visible dans tous les cas.
    assert blockers is not marked


def test_briefing_unknown_application_raises() -> None:
    with pytest.raises(KeyError):
        briefing_for_application(StubService(j1_data()), "app_inconnue")


def test_briefing_survives_failing_secondary_reads() -> None:
    class FlakyService(StubService):
        def get_job_prep(self, job_id: str) -> dict[str, Any]:
            raise RuntimeError("panneau indisponible")

        def list_interview_sessions(self, *, limit: int = 30) -> list[dict[str, Any]]:
            raise RuntimeError("historique indisponible")

    data = j1_data()
    payload = briefing_for_application(FlakyService(data), data["application"]["id"])
    # Le briefing est livré, la lacune est visible : jamais de masquage.
    assert payload["application_id"] == data["application"]["id"]
    assert any("revue du CV" in entry for entry in payload["incomplete_sections"])
    assert any("worksheets STAR" in entry for entry in payload["incomplete_sections"])
    assert payload["meta"]["star_worksheets_count"] == 0


# ---------------------------------------------------------------------------
# Administratif (SPEC-028) : applicabilité
# ---------------------------------------------------------------------------

def test_admin_applicability_matrix() -> None:
    base = {"country": "Allemagne", "employment_type": "stage"}
    assert admin_applicability(base) == (True, "Allemagne")
    assert admin_applicability({"country": "France", "employment_type": "stage"}) == (False, "France")
    assert admin_applicability({"country": "Espagne", "employment_type": "cdi"}) == (False, "Espagne")
    assert admin_applicability({"country": "", "employment_type": "stage"}) == (False, "")
    assert admin_applicability({"country": "allemagne", "job_family": "Alternance / VIE"}) == (True, "allemagne")
    assert admin_applicability(None) == (False, "")


def test_admin_blockers_from_mapping_and_from_object() -> None:
    data = j1_data()
    job = data["job"]
    from_mapping, applicable = admin_blockers_for_job(
        job, checklist_provider=lambda country: data["admin_checklist"]
    )
    assert applicable is True
    assert from_mapping == [
        "Autorisation de travail (work_permit)",
        "Assurance maladie (health_insurance)",
    ]

    class ObjectChecklist:
        blocking_missing = ["work_permit"]
        items = [{"key": "work_permit", "label_fr": "Autorisation de travail"}]

    from_object, _ = admin_blockers_for_job(job, checklist_provider=lambda country: ObjectChecklist())
    assert from_object == ["Autorisation de travail (work_permit)"]

    class ToDictChecklist:
        def to_dict(self) -> dict[str, Any]:
            return {"blocking_missing": ["work_permit"], "items": []}

    from_to_dict, _ = admin_blockers_for_job(job, checklist_provider=lambda country: ToDictChecklist())
    assert from_to_dict == ["work_permit"]


def test_admin_provider_failure_stays_visible_not_invented() -> None:
    def broken(country: str) -> Any:
        raise RuntimeError("SPEC-028 indisponible")

    blockers, applicable = admin_blockers_for_job(j1_data()["job"], checklist_provider=broken)
    assert applicable is True
    assert blockers == []
    doc = build_j1_briefing("app_admin", admin_blockers=blockers, admin_applicable=applicable)
    assert any("SPEC-028" in entry for entry in doc.incomplete_sections)


def test_admin_not_applicable_for_local_or_abroad_permanent() -> None:
    assert admin_blockers_for_job({"country": "France", "employment_type": "stage"}) == ([], False)
    assert admin_blockers_for_job({"country": "Pays-Bas", "employment_type": "cdi"}) == ([], False)


# ---------------------------------------------------------------------------
# CV à relire
# ---------------------------------------------------------------------------

def test_cv_reread_from_prep_and_unavailable() -> None:
    entries = cv_reread_from_prep(j1_data()["prep"])
    assert entries is not None
    assert len(entries) == 2
    assert entries[0].startswith("CV — Python [missing] :")
    assert cv_reread_from_prep(None) is None
    assert cv_reread_from_prep({"gaps": "pas une liste"}) is None
    # Rien à relire (liste vide) : ce n'est pas une lacune.
    assert cv_reread_from_prep({"gaps": []}) == []
    doc = build_j1_briefing("app_cv", cv_section_reread=[])
    assert not any("revue du CV" in entry for entry in doc.incomplete_sections)


# ---------------------------------------------------------------------------
# Export Markdown (un seul lien)
# ---------------------------------------------------------------------------

def test_render_markdown_lists_every_section_and_markers() -> None:
    doc = build_j1_briefing("app_md", company_facts=[])
    markdown = render_markdown(doc)
    assert markdown.startswith("# Briefing J-1")
    for title, _ in (
        ("Fiche entreprise", ""),
        ("Questions probables", ""),
        ("Worksheets STAR prêtes", ""),
        ("Blocs administratifs", ""),
        ("Éléments du CV à relire", ""),
        ("Sections à compléter", ""),
    ):
        assert f"## {title}" in markdown
    assert f"{MARKER_PREFIX} : fiche entreprise" in markdown
    # Le marqueur ne casse jamais la liste Markdown (une ligne = un puce).
    assert "\n- À COMPLÉTER" in markdown


def test_render_markdown_from_payload_dict() -> None:
    payload = briefing_for_application(StubService(j1_data()), j1_data()["application"]["id"])
    markdown = render_markdown(payload)
    assert "Nexora Labs" in markdown
    assert "## Sections à compléter" in markdown


# ---------------------------------------------------------------------------
# Tests adversariaux
# ---------------------------------------------------------------------------

def test_adversarial_malformed_completeness_is_never_ready() -> None:
    worksheets: list[dict[str, Any]] = [
        {"name": "nan", "completeness": float("nan")},
        {"name": "stringe", "completeness": "0.95x"},
        {"name": "bool", "completeness": True},
        {"name": "huge", "completeness": 42},
        {"name": "negative", "completeness": -3},
        {"name": "valid_string", "completeness": "0.95"},
        {"name": "rescue", "completeness": 42, "situation": "s", "task": "t", "action": "a", "result": "r"},
    ]
    doc = build_j1_briefing("app_adv", star_worksheets=worksheets)
    assert doc.star_ready == ["valid_string", "rescue"]
    for name in ("nan", "stringe", "bool", "huge", "negative"):
        assert any(name in entry for entry in doc.incomplete_sections), name
    assert math.isnan(float("nan"))  # le NaN reste géré, pas propagé au JSON
    json.dumps(to_dict(doc))


def test_adversarial_non_http_url_is_never_published_as_link() -> None:
    for evil in ("javascript:alert(1)", "data:text/html;base64,PHNjcmlwdD4=", "ftp://example.test/x", "//example.test/x"):
        facts = company_facts_from_job(
            {"company": "Acme", "title": "Dev", "source_name": "synthetic_board", "official_url": evil}
        )
        assert facts
        for fact in facts:
            assert evil not in fact, evil
            assert "(source : synthetic_board)" in fact


def test_adversarial_lists_are_bounded_and_json_safe() -> None:
    doc = build_j1_briefing(
        "app_bound",
        company_facts=[f"fait {index}" for index in range(500)],
        top_questions=[f"question {index}" for index in range(500)],
        admin_blockers=[f"blocage {index}" for index in range(500)],
        cv_section_reread=[f"écart {index}" for index in range(500)],
    )
    assert len(doc.company_facts) <= 20
    assert len(doc.top_questions) <= 12
    assert len(doc.admin_blockers) <= 20
    assert len(doc.cv_section_reread) <= 15
    json.dumps(to_dict(doc))


def test_adversarial_multiline_text_is_flattened_for_markdown() -> None:
    facts = company_facts_from_job(
        {"company": "Acme\n- injection", "title": "Dev\r\nautre ligne", "source_name": "manual"}
    )
    assert facts
    for fact in facts:
        assert "\n" not in fact and "\r" not in fact
    markdown = render_markdown(build_j1_briefing("app_ml", company_facts=facts))
    injected = [line for line in markdown.splitlines() if line.startswith("- injection")]
    assert injected == []

    junk = [None, "pas un worksheet", 42]
    doc = build_j1_briefing("app_junk", star_worksheets=junk)
    assert doc.star_ready == []
    assert any("worksheets STAR" in entry for entry in doc.incomplete_sections)


# ---------------------------------------------------------------------------
# Routes REST servies par create_app() — smoke test obligatoire
# ---------------------------------------------------------------------------

def build_tracked_app(tmp_path: Path) -> tuple[CareerService, dict[str, Any], dict[str, Any]]:
    data = j1_data()
    service = CareerService(tmp_path)
    payload = {key: value for key, value in data["job"].items() if key in IMPORTABLE_OFFER_KEYS}
    job = service.import_job(payload)
    application = service.create_application(job["id"])
    return service, job, application


def test_rest_j1_briefing_smoke_via_create_app(tmp_path: Path) -> None:
    service, job, application = build_tracked_app(tmp_path)
    client = TestClient(create_app(tmp_path, agent_override=object(), career_override=service))

    response = client.get(f"/api/career/applications/{application['id']}/j1-briefing")
    assert response.status_code == 200
    payload = response.json()
    for key in (
        "application_id",
        "company_facts",
        "top_questions",
        "star_ready",
        "admin_blockers",
        "cv_section_reread",
        "incomplete_sections",
        "meta",
    ):
        assert key in payload
    assert payload["application_id"] == application["id"]
    assert payload["company_facts"], "la fiche entreprise est sourcée depuis l'offre enregistrée"
    assert any("Nexora Labs" in fact for fact in payload["company_facts"])
    assert all("(source :" in fact for fact in payload["company_facts"])
    assert payload["meta"]["job_id"] == job["id"]
    assert payload["meta"]["questions_source"] in {"spec-031", "local"}
    assert payload["meta"]["automated_submission"] is False
    # Stage à l'étranger sans SPEC-028 fusionné : soit des blocages, soit un
    # marqueur — jamais les deux, jamais rien du tout.
    blockers = bool(payload["admin_blockers"])
    marked = any("SPEC-028" in entry for entry in payload["incomplete_sections"])
    assert payload["meta"]["admin_applicable"] is True
    assert blockers is not marked


def test_rest_j1_briefing_markdown_export(tmp_path: Path) -> None:
    service, _, application = build_tracked_app(tmp_path)
    client = TestClient(create_app(tmp_path, agent_override=object(), career_override=service))

    response = client.get(f"/api/career/applications/{application['id']}/j1-briefing.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert f"briefing-j1-{application['id']}.md" in response.headers.get("content-disposition", "")
    body = response.text
    assert body.startswith("# Briefing J-1")
    assert "## Fiche entreprise (avec sources)" in body
    assert MARKER_PREFIX in body


def test_rest_j1_briefing_unknown_application_is_400(tmp_path: Path) -> None:
    service, _, _ = build_tracked_app(tmp_path)
    client = TestClient(create_app(tmp_path, agent_override=object(), career_override=service))

    response = client.get("/api/career/applications/app_inconnue_0000/j1-briefing")
    assert response.status_code == 400
    assert "candidature" in response.json().get("detail", "").lower()


def test_rest_j1_briefing_includes_interview_session_practice(tmp_path: Path) -> None:
    data = j1_data()
    service, _, application = build_tracked_app(tmp_path)
    session = service.create_interview_session(
        {"mode": "behavioral", "difficulty": "intermediate", "language": "fr", "application_id": application["id"]}
    )
    service.answer_interview_session(
        session["id"],
        "Quand j'étais en mission dans l'équipe data, mon objectif était de fiabiliser le "
        "reporting ; j'ai construit un pipeline SQL et livré un tableau de bord qui a réduit "
        "le temps de production de 40 %.",
    )
    service.complete_interview_session(session["id"])

    client = TestClient(create_app(tmp_path, agent_override=object(), career_override=service))
    payload = client.get(f"/api/career/applications/{application['id']}/j1-briefing").json()
    assert payload["meta"]["star_worksheets_count"] == 1
    assert any("Séance behavioral" in label for label in payload["star_ready"])
    assert data["job"]["country"] == "Allemagne"
def test_build_basic() -> None:
    doc = build_j1_briefing(
        "app_1",
        company_facts=["Acme is a fintech"],
        top_questions=["Why us?"],
        cv_sections=["Experience", "Skills"],
    )
    assert isinstance(doc, BriefingDoc)
    assert doc.application_id == "app_1"
    assert doc.company_facts == ["Acme is a fintech"]
    assert doc.top_questions == ["Why us?"]
    assert doc.cv_section_reread == ["Experience", "Skills"]


def test_star_ready_filter() -> None:
    ws = [
        {"name": "ws1", "completeness": 0.9},
        {"name": "ws2", "completeness": 0.5},
    ]
    doc = build_j1_briefing("app_2", star_worksheets=ws)
    assert "ws1" in doc.star_ready
    assert f"{MARKER_PREFIX} : worksheet STAR « ws2 » (complétude 0.50)" in doc.incomplete_sections


def test_empty_star_marks_incomplete() -> None:
    doc = build_j1_briefing("app_3")
    assert (
        f"{MARKER_PREFIX} : worksheets STAR (aucune préparation d'entretien enregistrée)"
        in doc.incomplete_sections
    )


def test_admin_blockers() -> None:
    doc = build_j1_briefing("app_4", admin_blockers=["visa", "housing"])
    assert doc.admin_blockers == ["visa", "housing"]


def test_to_dict() -> None:
    doc = build_j1_briefing("app_5", company_facts=["f"])
    d = to_dict(doc)
    assert d["application_id"] == "app_5"
    assert "incomplete_sections" in d


def test_empty_inputs() -> None:
    doc = build_j1_briefing("app_6")
    assert doc.company_facts == []
    assert doc.top_questions == []
    assert doc.star_ready == []
    assert doc.admin_blockers == []
    assert doc.cv_section_reread == []


def test_star_threshold_custom() -> None:
    ws = [{"name": "ws1", "completeness": 0.7}]
    doc = build_j1_briefing("app_7", star_worksheets=ws, star_completeness_threshold=0.6)
    assert "ws1" in doc.star_ready


def test_adversarial_none_values() -> None:
    doc = build_j1_briefing("app_8", company_facts=None, top_questions=None)
    assert doc.company_facts == []
    assert doc.top_questions == []
