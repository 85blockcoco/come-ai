"""Profile readiness and profile-offer compatibility stay separate and factual."""

from __future__ import annotations

from career.profile_readiness import assess_profile_readiness
from career.scoring import score_job
from career.service import CareerService


def complete_profile() -> dict:
    return {
        "display_name": "Camille Exemple",
        "contact_email": "camille@example.test",
        "contact_phone": "",
        "linkedin_url": "https://www.linkedin.com/in/camille-example",
        "education": "Master 1 Finance — information synthétique",
        "experience": "Stage fictif en contrôle de gestion, six mois.",
        "skills": "Excel, analyse financière, Python",
        "languages": "français, anglais C1",
        "eligibility": "compatible",
        "target_companies": "Entreprise Exemple",
        "notes": "",
    }


def test_empty_profile_is_zero_and_missing_facts_are_never_invented():
    result = assess_profile_readiness({})
    assert result["score_out_of_20"] == 0
    assert result["known_fields"] == []
    assert {item["field"] for item in result["missing_fields"]} >= {
        "education", "experience", "skills", "languages", "eligibility"
    }
    assert result["label"] == "Profil à compléter"
    assert "probabilité" in result["disclaimer"].lower()


def test_complete_profile_reaches_twenty_with_auditable_components():
    result = assess_profile_readiness(complete_profile())
    assert result["score_out_of_20"] == 20
    assert result["label"] == "Profil prêt pour personnaliser les candidatures"
    assert sum(item["points"] for item in result["components"]) == 20
    assert result["missing_fields"] == []


def test_profile_service_recalculates_readiness_after_local_edit(tmp_path):
    service = CareerService(tmp_path)
    before = service.get_profile()
    assert before["readiness"]["score_out_of_20"] == 0
    saved = service.update_profile(complete_profile())
    assert saved["readiness"]["score_out_of_20"] == 20
    assert CareerService(tmp_path).get_profile()["readiness"] == saved["readiness"]


def test_offer_score_exposes_twenty_point_scale_and_evidence_confidence():
    profile = complete_profile()
    preferences = {
        "families": [{"key": "corporate-finance", "label": "Corporate Finance", "enabled": True}],
        "locations": [{"key": "paris", "label": "Paris", "enabled": True, "scope": "primary"}],
    }
    job = {
        "company": "Entreprise Exemple", "title": "Corporate Finance Intern",
        "job_family": "Corporate Finance", "city": "Paris", "country": "France",
        "requirements": "Excel, English and financial analysis", "languages_required": "English",
        "calendar_status": "compatible", "eligibility_requirement": "Work authorisation required",
        "source_status": "open",
    }
    result = score_job(profile, preferences, {"answers": {}}, job)
    assert result["score_out_of_20"] == round(result["score"] / 5)
    assert result["confidence"] in {"faible", "moyenne", "élevée"}
    assert result["known_component_count"] + result["unknown_component_count"] == len(result["components"])
    assert "probabilité" in result["disclaimer"].lower()

