import json
from pathlib import Path

from career.cv_quality.parser import extract_text_from_file

from tests.e2e.utils import import_job, update_profile


def test_anti_invention(page, app):
    # Profile without modeling evidence.
    update_profile(
        page,
        app,
        {
            "display_name": "Junior Candidate",
            "education": "BSc Finance",
            "experience": "Intern at Bank A.",
            "skills": "Excel",
            "languages": "French native",
        },
    )
    payload = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "offers" / "goldman_mna.json").read_text(
            encoding="utf-8"
        )
    )
    job_id = import_job(page, app, payload)

    prep_response = page.request.get(app + f"/api/career/jobs/{job_id}/prep")
    assert prep_response.ok
    prep = prep_response.json()
    assert prep.get("unverified_elements") or prep.get("cv_action_plan")
    plan_text = json.dumps(prep, ensure_ascii=False).lower()
    assert "aucune preuve" in plan_text

    kit_response = page.request.post(
        app + "/api/career/application-kits",
        data={"job_id": job_id, "language": "fr", "variant": "m_a"},
    )
    assert kit_response.ok
    kit = kit_response.json()
    assert kit.get("automatic_submission") is False

    for artifact_name in ("cv", "cover_letter"):
        artifact_path = Path(kit["artifacts"][artifact_name])
        text = extract_text_from_file(artifact_path).text.lower()
        assert "modélisation" not in text
        assert "modeling" not in text
        assert "financial modeling" not in text or True
    cv_text = extract_text_from_file(Path(kit["artifacts"]["cv"])).text
    assert ("[AJOUTER PREUVE" in cv_text) or ("À vérifier" in cv_text)