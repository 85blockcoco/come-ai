"""Career Stage Hunter: offline coverage for the five-step journey.

Every fixture below is synthetic and labelled as such: no real offer, no real
company and no real deadline is used, and nothing here performs a network
request.  What is verified is the deterministic behaviour a person relies on:
criteria are never presumed, ranking is explainable, URLs and sources are
conserved, tracking persists, nothing is invented and nothing is sent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.application_prep import extract_requirements, prepare_application
from career.offer_dates import extract_offer_dates
from career.offer_qualification import qualify_offer
from career.router import create_career_router
from career.service import CareerService
from career.stage_search import (
    RANKING_CRITERIA,
    STAGE_DOMAINS,
    brief_is_configured,
    default_brief,
    score_brief_match,
    validate_brief,
)
from workspace_core import UserFacingError


def synthetic_job(**changes: object) -> dict[str, object]:
    """A clearly synthetic offer; it references no real company or posting."""
    payload: dict[str, object] = {
        "company": "Banque de Démo",
        "title": "M&A Intern",
        "source_name": "manual",
        "source_id": "",
        "official_url": "https://careers.example.test/jobs/77?utm_source=mail",
        "job_family": "M&A / Investment Banking",
        "city": "Paris",
        "country": "France",
        "posted_date": "2026-10-01",
        "deadline_date": "2026-12-15",
        "start_date": "2027-02-01",
        "end_date": "2027-05-31",
        "duration_months": 4,
        "source_status": "open",
        "role_level": "",
        "requirements": "Bac+5 en cours. Maîtrise d’Excel et anglais courant.",
        "languages_required": "Anglais C1",
        "eligibility_requirement": "",
        "description_original": "Stage synthétique de quatre mois en fusion-acquisition.",
    }
    payload.update(changes)
    return payload


def _profile_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "display_name": "Exemple Local",
        "contact_email": "exemple.local@example.test",
        "contact_phone": "+33600000000",
        "linkedin_url": "https://www.linkedin.com/in/exemple-local",
        "education": "Master 2 Finance",
        "experience": "Stage en contrôle de gestion.",
        "skills": "Excel, Power BI",
        "languages": "Français natif, anglais C1",
        "eligibility": "compatible",
    }
    payload.update(changes)
    return payload


# --- 1. Critères de recherche -------------------------------------------------


def test_empty_brief_presumes_nothing() -> None:
    """An unset reusable brief remains neutral outside the Career first-open UI."""
    brief = validate_brief({})
    assert brief == default_brief()
    assert brief_is_configured(brief) is False
    assert brief["domains"] == [] and brief["ranking"] == {}


def test_brief_validation_is_strict_and_explainable() -> None:
    with pytest.raises(UserFacingError, match="n’existe pas"):
        validate_brief({"domains": ["Métier inventé"]})
    with pytest.raises(UserFacingError, match="connu"):
        validate_brief({"ranking": {"critere_invente": 1.0}})
    with pytest.raises(UserFacingError, match="entre 0.5 et 2"):
        validate_brief({"ranking": {"domaine": 4.0}})
    with pytest.raises(UserFacingError, match="AAA-MM-JJ|format"):
        validate_brief({"start_date": "janvier 2027"})
    with pytest.raises(UserFacingError, match="1 et 24"):
        validate_brief({"duration_months": 40})
    validated = validate_brief(
        {"domains": ["M&A", "m&a"], "start_date": "2027-01-01", "duration_months": "4", "ranking": {"metier": 1.5}}
    )
    assert validated["domains"] == ["M&A"]  # canonicalized, deduplicated
    assert validated["duration_months"] == 4
    assert validated["ranking"]["metier"] == 1.5
    assert set(validated["ranking"]) <= set(RANKING_CRITERIA)


def test_stage_search_persists_locally_and_survives_restart(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    saved = service.update_stage_search(
        {
            "domains": ["M&A", "Private Equity"],
            "cities": ["Paris"],
            "start_date": "2027-01-01",
            "duration_months": 4,
            "study_level": "Bac+5",
            "languages": ["Anglais"],
            "constraints": "Pas de mobilité internationale.",
            "ranking": {"domaine": 1.5},
        }
    )
    assert saved["configured"] is True
    assert saved["brief"]["domains"] == ["M&A", "Private Equity"]
    assert saved["brief"]["ranking"] == {"domaine": 1.5}
    # Vocabulary and search hints come from local lexicons, never from a model.
    assert "M&A" in saved["vocabulary"]["domains"]
    assert any(entry["domain"] == "M&A" and entry["terms"] for entry in saved["search_terms"])

    reopened = CareerService(tmp_path)
    loaded = reopened.get_stage_search()
    assert loaded["brief"] == saved["brief"]
    assert loaded["configured"] is True


# --- 2. Classement ------------------------------------------------------------


def test_stage_match_is_deterministic_and_fully_explained() -> None:
    brief = validate_brief({"domains": ["M&A"], "cities": ["Paris"], "duration_months": 4, "languages": ["Anglais"]})
    job = dict(synthetic_job())
    first = score_brief_match(brief, job)
    second = score_brief_match(brief, dict(job))
    assert first == second
    assert 0 <= first["score"] <= 100
    for component in first["components"]:
        assert component["reason"], "chaque composante doit être expliquée"
        assert 0 <= component["points"] <= component["maximum"]
    assert first["components"], "le score ne peut pas être muet"
    assert first["label"] in {"Correspondance forte", "Correspondance à examiner", "Correspondance faible ou incomplète", "Aucun critère renseigné : classement neutre"}


def test_ranking_weights_change_the_score_in_a_visible_way() -> None:
    job = dict(synthetic_job())
    neutral = score_brief_match(validate_brief({"domains": ["M&A"], "cities": ["New York"]}), job)
    boosted = score_brief_match(
        validate_brief({"domains": ["M&A"], "cities": ["New York"], "ranking": {"localisation": 2.0}}), job
    )
    # The mismatching location gets double weight, so the total must drop.
    assert boosted["score"] < neutral["score"]
    assert boosted["weights_applied"]["localisation"] == 2.0
    assert neutral["weights_applied"]["localisation"] == 1.0


def test_unconfigured_brief_produces_no_ranking() -> None:
    brief = default_brief()
    match = score_brief_match(brief, dict(synthetic_job()))
    assert match["score"] is None
    assert match["label"].startswith("Aucun critère")


def test_stage_matches_are_sorted_and_flag_unverified_sources(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    weak = service.import_job(synthetic_job(title="Audit Intern", official_url="https://careers.example.test/jobs/1", job_family="Consulting", city="Lyon", description_original="Stage audit financier synthétique."))
    strong = service.import_job(synthetic_job(official_url="https://careers.example.test/jobs/2"))
    service.update_stage_search({"domains": ["M&A"], "cities": ["Paris"]})
    matches = service.list_stage_matches()
    assert matches["configured"] is True
    scores = [item["stage_match"]["score"] for item in matches["matches"]]
    assert scores == sorted(scores, reverse=True)
    by_id = {item["job"]["id"]: item for item in matches["matches"]}
    assert by_id[strong["id"]]["stage_match"]["score"] > by_id[weak["id"]]["stage_match"]["score"]
    # An offer whose open status is not confirmed stays usable but flagged.
    service.import_job(synthetic_job(title="PE Intern", official_url="https://careers.example.test/jobs/3", source_status="unknown"))
    matches = service.list_stage_matches()
    flagged = next(item for item in matches["matches"] if item["job"]["source_status"] == "unknown")
    assert flagged["stage_match"]["warnings"], "une offre non confirmée ouverte doit être signalée"


def test_high_relevance_never_hides_missing_mandatory_offer_facts(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(synthetic_job(
        source_name="greenhouse",
        source_id="synthetic-missing-facts",
        start_date="",
        end_date="",
        duration_months=None,
        description_original="M&A internship with corporate finance responsibilities.",
    ))
    # La personne cherche en France : elle l'autorise explicitement, ce parcours
    # mesure donc la pertinence et non la règle géographique du classement.
    service.update_stage_search({"domains": ["M&A"], "excluded_countries": []})
    item = next(entry for entry in service.list_stage_matches()["matches"] if entry["job"]["id"] == job["id"])
    match = item["stage_match"]
    assert match["score"] == 100
    assert match["fit_label"] == "Correspondance forte"
    assert match["qualification_status"] == "to_verify"
    assert match["label"] == "Pertinence élevée — informations obligatoires à vérifier"
    assert "Correspondance forte" not in match["label"]


def test_non_conforming_offer_never_gets_a_positive_presentation_label(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(synthetic_job(
        source_name="greenhouse",
        source_id="synthetic-april-short",
        start_date="2027-04-01",
        end_date="2027-07-31",
        duration_months=4,
        description_original="M&A internship with corporate finance responsibilities.",
    ))
    service.update_stage_search({"domains": ["M&A"], "excluded_countries": []})
    item = next(entry for entry in service.list_stage_matches()["matches"] if entry["job"]["id"] == job["id"])
    assert item["stage_match"]["score"] == 100
    assert item["stage_match"]["qualification_status"] == "non_conforming"
    assert item["stage_match"]["label"] == "Hors critères obligatoires sélectionnés"


def test_unconfigured_brief_leaves_default_order(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.import_job(synthetic_job())
    matches = service.list_stage_matches()
    assert matches["configured"] is False
    assert all(item["stage_match"] is None for item in matches["matches"])


# --- 3. Déduplication ---------------------------------------------------------


def test_same_canonical_url_never_creates_two_opportunities(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    first = service.import_job(synthetic_job())
    again = service.import_job(synthetic_job())
    assert first["id"] == again["id"]
    # Tracking parameters alone must not fork the opportunity either.
    variant = service.import_job(synthetic_job(official_url="https://careers.example.test/jobs/77?utm_source=linkedin"))
    assert variant["id"] == first["id"]
    assert len(service.list_jobs()) == 1


# --- 4. Conservation des URLs -------------------------------------------------


def test_official_url_is_conserved_verbatim_through_the_journey(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(synthetic_job())
    service.update_stage_search({"domains": ["M&A"]})
    matches = service.list_stage_matches()
    matched = next(item for item in matches["matches"] if item["job"]["id"] == job["id"])
    assert matched["job"]["official_url"] == job["official_url"]
    prep = service.get_job_prep(job["id"])
    assert prep["job"]["official_url"] == job["official_url"]
    assert prep["job"]["source_name"] == "manual"


def test_job_prep_compares_offer_requirements_with_saved_profile_facts(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.update_profile({"education": "Master 2 en Finance", "skills": "Excel"})
    job = service.import_job(
        synthetic_job(
            requirements="Master 2 en Finance requis. Maîtrise d’Excel obligatoire.",
            languages_required="Anglais C1 préféré.",
        )
    )

    prep = service.get_job_prep(job["id"])

    fit = prep["requirements_fit"]
    assert fit["fits"]
    supported = [item for item in fit["fits"] if item["verdict"] == "supported"]
    assert any("Master 2" in item["profile_evidence"] for item in supported)
    assert any("Excel" in item["profile_evidence"] for item in supported)
    assert fit["to_verify_count"] >= 1  # absence is never treated as incompatibility


def test_job_prep_carries_reconstructed_source_trust_and_temporal_evidence(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    payload = synthetic_job(
        company="Synthetic Bank",
        source_name="greenhouse",
        source_id="synthetic-january-2027",
        official_url="https://boards.greenhouse.io/synthetic-bank/jobs/synthetic-january-2027",
        description_original="Synthetic internship starting January 2027 for six months.",
        duration_months=6,
    )
    qualification = qualify_offer(
        payload,
        minimum_duration_months=1,
        minimum_stage_duration_months=1,
        allowed_contract_types=["internship"],
        allowed_start_months=list(range(1, 13)),
    ).to_dict()
    qualification["temporal_facts"] = [fact.to_dict() for fact in extract_offer_dates(payload)]
    payload["qualification"] = qualification
    job = service.import_job(payload)

    prep_job = service.get_job_prep(job["id"])["job"]

    assert prep_job["official_source_trust"]["status"] == "verified"
    assert prep_job["official_source_trust_label"] == "Source officielle vérifiée"
    assert prep_job["source_verified"] is False  # URL trust does not verify offer content.
    assert any(
        fact["fact_type"] == "start" and fact["value"]["year"] == 2027
        for fact in prep_job["qualification_facts"]["temporal_facts"]
    )


# --- 5. Offres indisponibles --------------------------------------------------


def test_unavailable_offer_is_flagged_not_hidden(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    closed = service.import_job(synthetic_job(source_status="closed"))
    prep = service.get_job_prep(closed["id"])
    assert any("confirmé" in item or "fermée" in item for item in prep["uncertainty"])
    # The offer is still available for reading; it is never silently deleted.
    assert service.get_job(closed["id"])["source_status"] == "closed"


def test_deadline_helpers_still_flag_closed_offers() -> None:
    prep = prepare_application({}, {}, dict(synthetic_job(source_status="unknown", deadline_status="closed")))
    assert prep["uncertainty"], "une annonce fermée doit rester signalée dans la préparation"


# --- 6. Suivi persistant ------------------------------------------------------


def test_funnel_statuses_persist_across_restarts(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(synthetic_job())
    application = service.create_application(job["id"])
    assert application["stage"] == "to_review", "un suivi débute à l’étape « À examiner »"
    service.update_application_stage(application["id"], "to_prepare")
    service.update_application_stage(application["id"], "ready_to_apply")
    service.approve_for_manual_submission(application["id"], True, "Dépôt manuel décidé par la personne")
    sent = service.update_application_stage(application["id"], "submitted", "Dépôt effectué manuellement sur le site officiel")
    assert sent["stage"] == "submitted"
    assert sent["receipt_status"] == "unknown", "un envoi déclaré n’est pas une réception confirmée"
    confirmed = service.confirm_receipt(application["id"], "accuse-2027-001")
    assert confirmed["stage"] == "submitted_confirmed"
    interviewed = service.update_application_stage(application["id"], "interview")
    assert interviewed["stage"] == "interview"
    offered = service.update_application_stage(application["id"], "offer_received")
    assert offered["stage"] == "offer_received"

    reopened = CareerService(tmp_path)
    persisted = reopened.get_application(application["id"])
    assert persisted["stage"] == "offer_received"
    assert persisted["events"], "l’historique du suivi doit être conservé"


def test_refusal_is_distinct_from_self_rejection(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(synthetic_job())
    application = service.create_application(job["id"])
    refused = service.update_application_stage(application["id"], "refused")
    assert refused["stage"] == "refused"
    reopened = CareerService(tmp_path)
    assert reopened.get_application(application["id"])["stage"] == "refused"


# --- 7. Absence d'invention dans les candidatures -----------------------------


def test_prep_quotes_only_real_profile_text() -> None:
    profile = _profile_payload()
    job = dict(synthetic_job())
    prep = prepare_application(profile, {}, job)
    profile_text = " ".join(str(profile[key]) for key in ("skills", "experience", "education", "languages"))
    assert prep["matched_elements"], "des éléments du profil doivent correspondre"
    for item in prep["matched_elements"]:
        assert item["evidence"].casefold() in profile_text.casefold(), "chaque preuve est un extrait réel du profil"
        assert item["profile_field"] in {"skills", "experience", "education", "languages", "eligibility"}
    for point in prep["letter_points"]:
        assert "ton profil mentionne" in point["point"]


def test_missing_requirement_is_never_asserted_against_the_person() -> None:
    profile = _profile_payload(skills="Excel", experience="", education="", languages="Français natif")
    job = dict(synthetic_job(requirements="Maîtrise de Python et de Bloomberg Terminal requise."))
    prep = prepare_application(profile, {}, job)
    missing_texts = [item["requirement"] for item in prep["unverified_elements"]]
    assert any("Python" in text for text in missing_texts)
    matched_texts = [item["requirement"] for item in prep["matched_elements"]]
    assert not any("Python" in text for text in matched_texts), "Python ne peut pas être présenté comme maîtrisé"
    for item in prep["unverified_elements"]:
        assert item["note"].startswith("Non trouvé dans ton profil")


def test_empty_profile_invents_nothing() -> None:
    prep = prepare_application({}, {}, dict(synthetic_job()))
    assert prep["matched_elements"] == []
    assert prep["requirements"], "les exigences de l’offre restent affichées"
    assert any("profil local" in item["suggestion"] for item in prep["cv_improvements"])
    assert all(check["key"] for check in prep["checks"])


def test_requirements_extraction_is_bounded_and_source_faithful() -> None:
    items = extract_requirements(dict(synthetic_job(requirements="Exigence A.\nExigence B.\nExigence A.")))
    texts = [item["text"] for item in items]
    assert texts.count("Exigence A.") == 1
    assert all(item["source"] in {"requirements", "languages_required", "eligibility_requirement"} for item in items)


# --- 8. Comportement en l'absence de fournisseur IA ---------------------------


def stage_hunter_client(service: CareerService) -> TestClient:
    """Minimal app with the same error contract as the real FastAPI app."""
    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


def test_stage_hunter_works_without_any_ai_provider(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(synthetic_job())
    client = stage_hunter_client(service)

    health = client.get("/api/career/health")
    assert health.status_code == 200
    assert health.json()["ai_enhancement"]["available"] is False
    assert health.json()["automated_submission"] is False
    assert health.json()["stage_search"]["ai_required"] is False

    assert client.get("/api/career/stage-search").status_code == 200
    put = client.put("/api/career/stage-search", json={"domains": ["M&A"], "cities": ["Paris"]})
    assert put.status_code == 200
    assert client.get("/api/career/stage-search/matches").status_code == 200
    prep = client.get(f"/api/career/jobs/{job['id']}/prep")
    assert prep.status_code == 200
    assert prep.json()["job"]["id"] == job["id"]

    # The local draft keeps working; the AI mode fails with a clear message.
    draft = client.post(
        "/api/career/application-drafts",
        json={"job_id": job["id"], "language": "fr", "mode": "ai"},
    )
    assert draft.status_code >= 400


def test_local_draft_still_available_without_ai(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(synthetic_job())
    draft = service.create_application_draft(job["id"], "fr")
    assert draft["generation_mode"] == "local"
    assert draft["provider"].startswith("Local")


# --- 9. Protection des données personnelles -----------------------------------


def test_contact_data_never_reaches_the_prep_output() -> None:
    profile = _profile_payload()
    prep = prepare_application(profile, {}, dict(synthetic_job()))
    serialized = json.dumps(prep, ensure_ascii=False)
    assert profile["contact_email"] not in serialized
    assert profile["contact_phone"] not in serialized
    assert profile["linkedin_url"] not in serialized


def test_stage_search_is_local_and_resettable(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.update_stage_search({"domains": ["M&A"], "cities": ["Paris"]})
    export_path = service.export_personal_data()
    exported = json.loads(Path(export_path).read_text(encoding="utf-8"))
    settings = exported["preferences"]["availability"]
    assert "stage_search_brief" in settings, "les critères sont exportés avec les données de la personne"
    service.reset_personal_data("SUPPRIMER MES DONNÉES CAREER")
    assert service.get_stage_search()["configured"] is False


# --- 10. Non-envoi sans autorisation ------------------------------------------


def test_submission_states_require_explicit_local_validation(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(synthetic_job())
    application = service.create_application(job["id"])
    with pytest.raises(UserFacingError, match="Approuve d’abord"):
        service.update_application_stage(application["id"], "submitted")
    with pytest.raises(UserFacingError, match="approbation explicite"):
        service.approve_for_manual_submission(application["id"], False)
    with pytest.raises(UserFacingError, match="Approuve d’abord"):
        service.confirm_receipt(application["id"], "ref-123")
    # A confirmed receipt can never be rewritten as a lesser state.
    service.approve_for_manual_submission(application["id"], True)
    service.confirm_receipt(application["id"], "ref-123")
    with pytest.raises(UserFacingError, match="antérieur"):
        service.update_application_stage(application["id"], "submitted")


def test_no_career_code_sends_anything(tmp_path: Path) -> None:
    """The Stage Hunter modules stay free of any network or mail capability."""
    package_dir = Path(__file__).resolve().parents[1] / "career"
    for name in ("stage_search.py", "application_prep.py"):
        source = (package_dir / name).read_text(encoding="utf-8")
        for forbidden in ("requests", "urllib.request", "smtplib", "socket", "http.client"):
            assert forbidden not in source, f"{name} ne doit pas contenir {forbidden}"


# --- Robustesse : brief stocké corrompu, invariants de persistance ------------


def _write_raw_setting(service: CareerService, key: str, value: str) -> None:
    """Simulate an on-disk corruption (no public API writes arbitrary JSON)."""
    with service._lock, service._connection() as connection:
        connection.execute(
            """
            INSERT INTO career_settings (setting_key, setting_value) VALUES (?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value
            """,
            (key, value),
        )


def test_corrupt_stored_brief_falls_back_without_locking_the_tab(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    _write_raw_setting(service, "stage_search_brief", "{pas du json")
    payload = service.get_stage_search()
    assert payload["configured"] is False
    assert payload["stored_brief_invalid"] is True, "la personne doit être prévenue"
    # The tab stays usable and the next save recovers a valid brief.
    saved = service.update_stage_search({"domains": ["M&A"]})
    assert saved["configured"] is True
    assert saved["stored_brief_invalid"] is False


def test_valid_json_but_invalid_brief_also_recovers(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    _write_raw_setting(
        service,
        "stage_search_brief",
        json.dumps({"domains": ["Domaine retiré du vocabulaire"], "ranking": {"critere_inconnu": 1.0}}),
    )
    payload = service.get_stage_search()
    assert payload["configured"] is False
    assert payload["stored_brief_invalid"] is True
    assert payload["brief"] == json.loads(json.dumps(payload["brief"]))  # sérialisable


def test_preferences_update_preserves_the_brief(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.update_stage_search({"domains": ["M&A"], "cities": ["Paris"]})
    preferences = service.get_preferences()
    service.update_preferences(
        {
            **preferences,
            "availability": {
                **preferences["availability"],
                "availability_start": "2027-03-01",
            },
        }
    )
    assert service.get_stage_search()["brief"]["domains"] == ["M&A"], (
        "une mise à jour des préférences ne doit pas écraser les critères de stage"
    )


def test_prep_endpoint_on_unknown_job_is_a_clean_400(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = stage_hunter_client(service)
    response = client.get("/api/career/jobs/job_inexistant_000/prep")
    assert response.status_code == 400
    assert "detail" in response.json()


# --- Scénario fonctionnel complet (données synthétiques) ----------------------


def test_full_http_journey_from_brief_to_offer_received(tmp_path: Path) -> None:
    """Un parcours réel, bout en bout, via les seuls endpoints HTTP publics."""
    service = CareerService(tmp_path)
    client = stage_hunter_client(service)

    # Étape A : la personne décrit le stage qu'elle cherche.  Elle vise
    # explicitement Paris et autorise la France : ce parcours mesure la
    # pertinence, pas la règle géographique du classement.
    put = client.put(
        "/api/career/stage-search",
        json={
            "domains": ["M&A"],
            "cities": ["Paris"],
            "excluded_countries": [],
            "excluded_cities": [],
            "start_date": "2027-01-01",
            "duration_months": 4,
            "languages": ["Anglais"],
            "ranking": {"domaine": 1.5},
        },
    )
    assert put.status_code == 200
    assert put.json()["configured"] is True

    # Étape B : une offre réelle importée depuis une source (ici, saisie).
    imported = client.post("/api/career/jobs/import", json=synthetic_job())
    assert imported.status_code == 201
    job = imported.json()
    assert job["source_status"] == "open"

    # Étape C : classement expliqué, URL officielle conservée.
    matches = client.get("/api/career/stage-search/matches").json()
    top = matches["matches"][0]
    assert top["stage_match"]["score"] == 100
    assert top["job"]["official_url"] == job["official_url"]
    assert all(component["reason"] for component in top["stage_match"]["components"])

    # Étape D : préparation factuelle, lien de candidature préservé.
    profile_put = client.put("/api/career/profile", json=_profile_payload())
    assert profile_put.status_code == 200
    prep = client.get(f"/api/career/jobs/{job['id']}/prep").json()
    assert prep["job"]["official_url"] == job["official_url"]
    assert prep["matched_elements"], "le profil local doit apparaître dans l’analyse"

    # Étape E : suivi complet, avec les gardes-fous.
    created = client.post("/api/career/applications", json={"job_id": job["id"]})
    assert created.status_code == 201
    application_id = created.json()["id"]
    assert created.json()["stage"] == "to_review"

    for stage in ("to_prepare", "ready_to_apply"):
        patched = client.patch(
            f"/api/career/applications/{application_id}",
            json={"stage": stage, "note": ""},
        )
        assert patched.status_code == 200
        assert patched.json()["stage"] == stage

    # Sans approbation, l’enregistrement d’un envoi est refusé.
    refused = client.patch(
        f"/api/career/applications/{application_id}",
        json={"stage": "submitted", "note": ""},
    )
    assert refused.status_code == 400
    assert "Approuve d’abord" in refused.json()["detail"]

    approved = client.post(
        f"/api/career/applications/{application_id}/approve",
        json={"approved": True, "note": "Dépôt manuel décidé par la personne"},
    )
    assert approved.status_code == 200
    sent = client.patch(
        f"/api/career/applications/{application_id}",
        json={"stage": "submitted", "note": "Dépôt effectué sur le site officiel"},
    )
    assert sent.status_code == 200
    assert sent.json()["receipt_status"] == "unknown"

    confirmed = client.post(
        f"/api/career/applications/{application_id}/confirm-receipt",
        json={"confirmation_reference": "accuse-synthetique-001"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["stage"] == "submitted_confirmed"
    assert confirmed.json()["receipt_status"] == "confirmed"

    offered = client.patch(
        f"/api/career/applications/{application_id}",
        json={"stage": "offer_received", "note": "Offre reçue (donnée synthétique)"},
    )
    assert offered.status_code == 200

    # Tout persiste après un redémarrage complet du service.
    reopened = CareerService(tmp_path)
    assert reopened.get_application(application_id)["stage"] == "offer_received"


# --- Qualité du classement finance : synonymes FR/EN et cas difficiles --------

_DOMAIN_TEXT_EXAMPLES: dict[str, tuple[str, str]] = {
    "M&A": (
        "Stage en fusions-acquisitions au sein d’une banque d’affaires.",
        "M&A internship within the investment banking division.",
    ),
    "Corporate Finance": (
        "Stage en finance d’entreprise : analyse financière et valorisation.",
        "Corporate finance internship: financial analysis and valuation.",
    ),
    "Private Equity": (
        "Stage en capital investissement au sein d’un fonds d’investissement.",
        "Private equity internship covering LBO and growth equity deals.",
    ),
    "Transaction Services": (
        "Stage en transaction services : due diligence financière.",
        "Transaction advisory internship supporting financial due diligence.",
    ),
    "Audit financier": (
        "Stage en audit financier et commissariat aux comptes.",
        "Statutory audit internship with external controls.",
    ),
    "Asset Management": (
        "Stage en gestion d’actifs au sein d’une société de gestion.",
        "Asset management internship in equity research.",
    ),
    "FP&A": (
        "Stage en contrôle de gestion : financial planning et business partnering.",
        "FP&A internship supporting financial planning analysis.",
    ),
}


@pytest.mark.parametrize("domain", sorted(_DOMAIN_TEXT_EXAMPLES))
@pytest.mark.parametrize("language", ["fr", "en"])
def test_each_finance_domain_is_recognized_in_french_and_english(domain: str, language: str) -> None:
    index = 0 if language == "fr" else 1
    text = _DOMAIN_TEXT_EXAMPLES[domain][index]
    brief = validate_brief({"domains": [domain]})
    match = score_brief_match(brief, dict(synthetic_job(description_original=text, title="Stage")))
    domain_component = next(c for c in match["components"] if c["key"] == "domaine")
    assert domain_component["status"] == "match", (
        f"{domain} devrait être reconnu depuis : « {text} »"
    )
    assert domain in domain_component["reason"]


def test_other_finance_domains_fall_back_to_the_job_family() -> None:
    brief = validate_brief({"domains": ["Autres métiers financiers"]})
    match = score_brief_match(
        brief, dict(synthetic_job(job_family="Sales & Trading", description_original="Stage synthétique sans domaine explicite."))
    )
    domain_component = next(c for c in match["components"] if c["key"] == "domaine")
    assert domain_component["status"] == "match"


def test_atypical_title_still_matches_through_the_description() -> None:
    brief = validate_brief({"domains": ["M&A", "Transaction Services"]})
    match = score_brief_match(
        brief,
        dict(
            synthetic_job(
                title="Deal Professional",
                description_original="Support aux opérations de fusions-acquisitions et aux due diligence financières.",
            )
        ),
    )
    domain_component = next(c for c in match["components"] if c["key"] == "domaine")
    assert domain_component["status"] == "match"
    assert "M&A" in domain_component["reason"] and "Transaction Services" in domain_component["reason"], (
        "un titre atypique ne doit pas masquer les domaines repérés dans le texte"
    )


def test_offer_without_location_is_flagged_unknown_not_silently_scored() -> None:
    brief = validate_brief({"cities": ["Paris"]})
    match = score_brief_match(brief, dict(synthetic_job(city="", country="")))
    location = next(c for c in match["components"] if c["key"] == "localisation")
    assert location["status"] == "unknown"
    assert any("Localisation" in item for item in match["unknowns"])


def test_higher_degree_requirement_breaks_the_match_visibly() -> None:
    brief = validate_brief({"study_level": "Licence (Bac+3)"})
    match = score_brief_match(brief, dict(synthetic_job(requirements="Master 2 requis.")))
    level = next(c for c in match["components"] if c["key"] == "niveau")
    assert level["status"] == "no_match"
    assert "supérieur" in level["reason"]


def test_permanent_contract_is_warned_but_not_hidden() -> None:
    brief = validate_brief({"domains": ["M&A"], "contract_types": ["stage"]})
    permanent = score_brief_match(
        brief, dict(synthetic_job(employment_type="CDI, Temps plein", description_original="Analyste M&A confirmé."))
    )
    assert any("permanent" in warning for warning in permanent["warnings"]), (
        "un CDI doit être signalé dans un produit de stages"
    )
    internship = score_brief_match(
        brief, dict(synthetic_job(employment_type="Stage, Temps plein", description_original="Stage M&A."))
    )
    assert not any("permanent" in warning for warning in internship["warnings"])


def test_dates_outside_the_window_are_visible_in_the_reason() -> None:
    brief = validate_brief({"start_date": "2027-01-01"})
    match = score_brief_match(
        brief, dict(synthetic_job(start_date="2026-04-01", end_date="2026-06-30"))
    )
    dates = next(c for c in match["components"] if c["key"] == "dates")
    assert dates["status"] == "no_match"
    assert "termine" in dates["reason"] or "avant" in dates["reason"]


def test_matching_uses_source_quoted_start_month_when_structured_date_is_absent() -> None:
    brief = validate_brief({"start_date": "2027-01-01"})
    job = dict(synthetic_job(
        start_date="",
        description_original="Synthetic finance internship starting January 2027 for six months.",
    ))
    match = score_brief_match(brief, job)
    dates = next(component for component in match["components"] if component["key"] == "dates")
    assert dates["status"] == "match"
    assert "January 2027" in dates["reason"]
    assert not any("Dates non renseignées" in item for item in match["unknowns"])


def test_matching_keeps_start_month_without_year_as_review() -> None:
    brief = validate_brief({"start_date": "2027-01-01"})
    job = dict(synthetic_job(
        start_date="",
        description_original="Synthetic finance internship starting in January for six months.",
    ))
    match = score_brief_match(brief, job)
    dates = next(component for component in match["components"] if component["key"] == "dates")
    assert dates["status"] in {"review", "unknown"}
    assert "année" in dates["reason"].lower() or any("année" in item.lower() for item in match["unknowns"])


def test_multi_domain_offer_lists_every_matched_domain() -> None:
    brief = validate_brief({"domains": ["Private Equity", "Transaction Services", "M&A"]})
    match = score_brief_match(
        brief,
        dict(synthetic_job(description_original="Stage en private equity couvrant les due diligence et les opérations M&A.")),
    )
    domain_component = next(c for c in match["components"] if c["key"] == "domaine")
    for domain in ("Private Equity", "Transaction Services", "M&A"):
        assert domain in domain_component["reason"]


# --- Parcours de première utilisation (service vierge) -----------------------


def test_first_open_starts_with_useful_finance_defaults_and_explains_itself(tmp_path: Path) -> None:
    """Une première ouverture recherche la finance sans inventer de préférence personnelle."""
    service = CareerService(tmp_path)
    payload = service.get_stage_search()
    assert payload["configured"] is False
    expected = default_brief()
    expected["domains"] = list(STAGE_DOMAINS)
    expected["excluded_countries"] = ["France"]
    expected["excluded_cities"] = ["Paris"]
    expected["require_known_location"] = True
    expected["start_date"] = "2027-01-01"
    expected["start_months"] = list(range(1, 13))
    assert payload["brief"] == expected
    assert payload["stored_brief_invalid"] is False
    assert payload["vocabulary"]["domains"], "le formulaire des domaines doit être renseignable"
    assert {item["domain"] for item in payload["search_terms"]} == set(STAGE_DOMAINS)
    matches = service.list_stage_matches()
    assert matches["matches"] == [], "aucune offre inventée au premier lancement"
    # Lancer une recherche sans source affiche une consigne claire, pas un échec muet.
    with pytest.raises(UserFacingError, match="Ajoute d’abord"):
        service.discover_opportunities()


def test_transport_guards_and_real_board_limits() -> None:
    """Le transport reste verrouillé sur l'hôte Greenhouse et borne la mémoire."""
    from career.discovery import (
        GREENHOUSE_HOST,
        GREENHOUSE_MAX_RESPONSE_BYTES,
        PublicSourceError,
        UrllibGreenhouseTransport,
    )

    transport = UrllibGreenhouseTransport()
    with pytest.raises(PublicSourceError, match="invalide"):
        transport.get_json("https://example.org/v1/boards/x/jobs", 5)
    assert GREENHOUSE_HOST == "boards-api.greenhouse.io"
    assert GREENHOUSE_MAX_RESPONSE_BYTES >= 8 * 1024 * 1024, (
        "un board réel publie plusieurs Mo de descriptions : la borne doit les accepter"
    )
