"""Geographic ranking: France is penalized, targeted countries are rewarded.

Every fixture is synthetic and offline.  The rules under test are the ones a
person asked for: a French offer never leads the list, an offer published in a
targeted country climbs, and a city never proves a country.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from career.discovery import GreenhouseBoard, GreenhouseJobBoardConnector
from career.models import DEFAULT_PREFERRED_COUNTRIES
from career.offer_qualification import geo_score_for, qualify_offer
from career.service import CareerService
from career.stage_search import default_brief, score_brief_match, validate_brief, vocabulary
from come_ai_web import create_app
from fastapi.testclient import TestClient


BOARD = GreenhouseBoard(id="synthetic-board", company="Synthetic Bank", board_token="synthetic-bank")


def raw_job(job_id: str, *, title: str = "M&A Intern", location: str = "Paris, France",
            content: str = "<p>Synthetic merger and acquisition internship.</p>") -> dict[str, Any]:
    return {
        "id": job_id,
        "title": title,
        "absolute_url": f"https://careers.example.test/jobs/{job_id}",
        "location": {"name": location},
        "content": content,
    }


def offer(**updates: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "company": "Synthetic Finance",
        "title": "Corporate Finance Intern",
        "employment_type": "Internship",
        "official_url": "https://example.test/jobs/synthetic-role",
        "source_name": "greenhouse",
        "source_id": "synthetic-role",
        "source_verified": True,
        "source_status": "open",
        "start_date": "2027-01-15",
        "duration_months": 6,
        "country": "France",
        "city": "Paris",
        "description_original": "Corporate Finance internship for six months.",
    }
    payload.update(updates)
    return payload


def qualify(job: dict[str, Any], **criteria: Any):
    return qualify_offer(job, as_of=date(2026, 10, 21), **criteria)


def match(brief: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    return score_brief_match(brief, job)


# --- 1. Pénalité France -------------------------------------------------------


def test_france_penalty_50() -> None:
    """Une offre France perd 50 points au classement."""
    france = qualify(offer(country="France", city="Lyon"))
    assert france.geo_score == -50
    assert "exclu" in france.geo_reason.lower()

    job = offer(country="France", city="Lyon")
    result = match(validate_brief({"domains": ["Corporate Finance"]}), job)
    assert result["geo_score"] == -50
    assert result["score"] == result["base_score"] - 50
    assert result["total_score"] == result["score"]


def test_preferred_country_boost_20() -> None:
    """Une offre publiée dans un pays ciblé gagne 20 points."""
    germany = qualify(offer(country="Germany", city="Frankfurt"),
                      preferred_countries=["DE"], geo_excluded_countries=[])
    assert germany.geo_score == 20
    assert "cibl" in germany.geo_reason.lower()

    result = match(validate_brief({"domains": ["Corporate Finance"], "preferred_countries": ["DE"]}),
                   offer(country="Germany", city="Frankfurt"))
    assert result["geo_score"] == 20
    assert result["score"] == min(100, result["base_score"] + 20)


def test_multiple_preferred_is_not_cumulative() -> None:
    """Un pays ciblé ne rapporte ses points qu'une fois."""
    brief = validate_brief({"domains": ["Corporate Finance"], "preferred_countries": ["NL", "DE", "NL"]})
    result = match(brief, offer(country="Netherlands", city="Amsterdam"))
    assert result["geo_score"] == 20
    assert result["score"] == min(100, result["base_score"] + 20)


def test_neutral_country() -> None:
    """Un pays ni ciblé ni exclu reste neutre."""
    result = match(validate_brief({"preferred_countries": ["DE"], "geo_excluded_countries": ["FR"]}),
                   offer(country="United States", city="New York"))
    assert result["geo_score"] == 0
    assert "neutre" in result["geo_reason"].lower()


def test_country_unknown_neutral() -> None:
    """Sans pays écrit par la source, le score géographique est nul."""
    unknown = qualify(offer(country="", city="Paris"))
    assert unknown.geo_score == 0
    assert unknown.geo_reason == "Pays inconnu"

    result = match(validate_brief({"domains": ["Corporate Finance"]}), offer(country="", city="Paris"))
    assert result["geo_score"] == 0
    assert result["geo_reason"] == "Pays inconnu"
    assert result["total_score"] == result["score"]


def test_frankfurt_is_not_france() -> None:
    """Une ville ne prouve jamais un pays : Francfort n'est pas la France."""
    frankfurt = qualify(offer(country="Frankfurt", city="Frankfurt"))
    assert frankfurt.geo_score == 0
    assert frankfurt.geo_reason == "Pays inconnu"

    real_germany = qualify(offer(country="DE", city="Frankfurt"))
    assert real_germany.geo_score == 20
    assert real_germany.geo_score != -50


def test_no_geographic_inference_from_the_city() -> None:
    """Le pays manquant n'est jamais déduit de la ville de l'offre."""
    result = match(validate_brief({"domains": ["Corporate Finance"]}),
                   offer(country="", city="Frankfurt"))
    assert result["geo_score"] == 0
    assert result["geo_reason"] == "Pays inconnu"


# --- 2. Configuration par brief ----------------------------------------------


def test_preferred_override_default() -> None:
    """Sans liste explicite, le défaut européen s'applique."""
    brief = validate_brief({})
    assert brief["preferred_countries"] == list(DEFAULT_PREFERRED_COUNTRIES)
    result = match(brief, offer(country="DE", city="Berlin"))
    assert result["geo_score"] == 20

    custom = match(validate_brief({"preferred_countries": ["GB"]}), offer(country="DE", city="Berlin"))
    assert custom["geo_score"] == 0


def test_excluded_override_default() -> None:
    """Une liste d'exclusions vide désactive la pénalité France."""
    brief = validate_brief({"excluded_countries": []})
    assert brief["geo_excluded_countries"] == []
    result = match(brief, offer(country="France", city="Lyon"))
    assert result["geo_score"] == 0

    default = match(validate_brief({}), offer(country="France", city="Lyon"))
    assert default["geo_score"] == -50


def test_explicit_geo_exclusion_list_wins() -> None:
    """La liste géographique explicite prime sur la liste d'exclusions."""
    brief = validate_brief({"excluded_countries": ["France"], "geo_excluded_countries": ["BE"]})
    assert brief["geo_excluded_countries"] == ["BE"]
    belgium = match(brief, offer(country="Belgium", city="Bruxelles"))
    france = match(brief, offer(country="France", city="Lyon"))
    assert belgium["geo_score"] == -50
    assert france["geo_score"] == 0


def test_brief_defaults_penalize_france_and_reward_europe() -> None:
    """Le brief par défaut expose la configuration géographique."""
    brief = default_brief()
    assert brief["geo_excluded_countries"] == ["FR"]
    assert "DE" in brief["preferred_countries"]
    assert validate_brief({}) == brief


def test_vocabulary_exposes_the_country_lists() -> None:
    """Le formulaire peut afficher les pays sans rien inventer."""
    rendered = vocabulary()
    assert "DE" in rendered["preferred_countries"]
    assert rendered["geo_excluded_countries"] == ["FR"]


# --- 3. Transparence ----------------------------------------------------------


def test_geo_reason_is_visible_in_the_qualification() -> None:
    """Le résultat de qualification porte le score et sa raison."""
    result = qualify(offer(country="France", city="Lyon"))
    assert result.geo_score == -50
    assert result.geo_reason
    assert result.country == "France"
    payload = result.to_dict()
    assert payload["geo_score"] == -50
    assert payload["geo_reason"] == result.geo_reason


def test_score_is_bounded_between_0_and_100() -> None:
    """Le score total reste toujours dans l'échelle 0-100."""
    brief = validate_brief({"domains": ["Corporate Finance"]})
    for country, expected in (("France", -50), ("Germany", 20), ("United States", 0)):
        result = match(brief, offer(country=country))
        assert 0 <= result["score"] <= 100
        assert 0 <= result["total_score"] <= 100
        assert result["total_score"] == max(0, min(100, result["base_score"] + expected))
        assert result["score"] == result["total_score"]


def test_geo_signal_never_changes_admissibility() -> None:
    """La pénalité est un signal de classement, pas un filtre."""
    france = qualify(offer(country="France", city="Lyon"), excluded_countries=[],
                     geo_excluded_countries=["FR"])
    assert france.target_status == "conforming"
    assert france.geo_score == -50


def test_geo_score_for_is_pure_and_explicit() -> None:
    """Le calcul du score géographique est une fonction pure."""
    assert geo_score_for("France", preferred_countries=["DE"], excluded_countries=["FR"]) == (
        -50,
        "Pays exclu (FR)",
    )
    assert geo_score_for("de", preferred_countries=["DE"], excluded_countries=["FR"]) == (
        20,
        "Pays ciblé (DE)",
    )
    assert geo_score_for("", preferred_countries=["DE"], excluded_countries=["FR"]) == (0, "Pays inconnu")
    # An excluded country is never rewarded, even when it is also targeted.
    assert geo_score_for("FR", preferred_countries=["FR"], excluded_countries=["FR"])[0] == -50


# --- 4. Classement ------------------------------------------------------------


def test_france_never_leads_the_ranking() -> None:
    """Même avec un score parfait, une offre France n'est jamais en tête."""
    jobs = [
        raw_job("france", title="M&A Intern", location="Paris, France"),
        raw_job("germany", title="M&A Intern", location="Berlin, Germany"),
    ]
    result = GreenhouseJobBoardConnector._normalise(
        BOARD, {"jobs": jobs}, selection_brief={"domains": ["M&A"]}
    )
    assert result.jobs[0]["source_id"] == "germany"
    assert "france" not in {job["source_id"] for job in result.jobs[:1]}


def test_ranking_integration_uses_the_total_score() -> None:
    """Le classement de la découverte tient compte du score géographique."""
    jobs = [
        raw_job("france", title="M&A Intern", location="Paris, France"),
        raw_job("germany", title="M&A Intern", location="Berlin, Germany"),
        raw_job("states", title="M&A Intern", location="New York, United States"),
    ]
    result = GreenhouseJobBoardConnector._normalise(
        BOARD, {"jobs": jobs}, selection_brief={"domains": ["M&A"]}
    )
    order = [job["source_id"] for job in result.jobs]
    assert order == ["germany", "states", "france"]

    brief = validate_brief({"domains": ["M&A"]})
    totals = {
        job["source_id"]: match(brief, {
            "title": job["title"],
            "description_original": "Synthetic merger and acquisition internship.",
            "country": job["country"],
        })
        for job in result.jobs
    }
    assert totals["germany"]["geo_score"] == 20
    assert totals["states"]["geo_score"] == 0
    assert totals["france"]["geo_score"] == -50
    # The targeted country reaches the highest total score, the penalized one
    # the lowest, even when every offer matches the same criteria.
    assert totals["germany"]["total_score"] >= totals["states"]["total_score"]
    assert totals["states"]["total_score"] > totals["france"]["total_score"]


def test_preferred_country_climbs_over_a_neutral_one() -> None:
    """Un pays ciblé remonte dans le classement."""
    jobs = [
        raw_job("states", title="M&A Intern", location="New York, United States"),
        raw_job("germany", title="M&A Intern", location="Berlin, Germany"),
    ]
    result = GreenhouseJobBoardConnector._normalise(
        BOARD, {"jobs": jobs}, selection_brief={"domains": ["M&A"], "preferred_countries": ["DE"]}
    )
    assert [job["source_id"] for job in result.jobs] == ["germany", "states"]


def test_internship_selection_reports_the_geographic_signal() -> None:
    """La qualification d'un stage porte aussi son signal géographique."""
    jobs = [
        raw_job("france", title="M&A Intern", location="Paris, France",
                content="<p>Stage en fusion-acquisition de six mois à partir de janvier 2027.</p>"),
        raw_job("germany", title="M&A Intern", location="Berlin, Germany",
                content="<p>Stage en fusion-acquisition de six mois à partir de janvier 2027.</p>"),
    ]
    result = GreenhouseJobBoardConnector._normalise(
        BOARD, {"jobs": jobs}, selection_brief={"domains": ["M&A"]}, internships_only=True
    )
    by_id = {job["source_id"]: job for job in result.jobs}
    assert by_id["france"]["qualification"]["geo_score"] == -50
    assert by_id["germany"]["qualification"]["geo_score"] == 20
    assert by_id["germany"]["qualification"]["geo_reason"]


# --- 5. Le signal atteint tous les classements -------------------------------


def test_a_country_code_and_its_name_exclude_the_same_offer() -> None:
    """« FR » et « France » désignent le même pays pour la personne."""
    brief = validate_brief({"domains": ["Corporate Finance"],
                            "excluded_countries": ["FR"], "geo_excluded_countries": ["FR"]})
    result = match(brief, offer(country="France", city="Lyon"))
    assert result["geo_score"] == -50
    assert result["base_score"] == result["score"] + 50
    # The hard exclusion understands the code as well.
    excluded = qualify(offer(country="France", city="Lyon"), excluded_countries=["FR"])
    assert excluded.geography_status == "excluded"
    assert excluded.target_status == "non_conforming"


def test_a_country_outside_the_table_is_still_penalised_verbatim() -> None:
    """Un pays que la table ne connaît pas reste exclu s'il est écrit tel quel."""
    brief = validate_brief({"excluded_countries": ["Serbie"], "geo_excluded_countries": ["Serbie"]})
    result = match(brief, offer(country="Serbie", city="Belgrade"))
    assert result["geo_score"] == -50
    assert "exclu" in result["geo_reason"].lower()


def test_the_saved_offer_list_never_leads_with_a_penalised_country(tmp_path) -> None:
    """Le classement affiché dans l'application suit la règle géographique."""
    service = CareerService(tmp_path)
    service.update_stage_search({"domains": ["M&A"]})
    for city, country in (("Paris", "France"), ("Berlin", "Germany")):
        service.import_job({
            "company": "Banque Exemple",
            "title": f"M&A Intern {city}",
            "source_name": "manual",
            "official_url": f"https://careers.example.test/jobs/{city.lower()}",
            "job_family": "M&A / Investment Banking",
            "city": city,
            "country": country,
            "posted_date": "2026-10-01",
            "start_date": "2027-01-01",
            "end_date": "2027-06-30",
            "duration_months": 6,
            "source_status": "open",
            "description_original": "Stage de fusion-acquisition de six mois.",
        })
    matches = service.list_stage_matches()["matches"]
    order = [entry["job"]["title"] for entry in matches]
    assert order[0] == "M&A Intern Berlin"
    assert order[-1] == "M&A Intern Paris"
    scores = {entry["job"]["title"]: entry["stage_match"]["score"] for entry in matches}
    assert scores["M&A Intern Berlin"] > scores["M&A Intern Paris"]


def test_the_geographic_points_are_part_of_the_score_every_ranking_uses() -> None:
    """Le score lu par les classements est le total, pas la pertinence seule."""
    brief = validate_brief({"domains": ["Corporate Finance"]})
    france = match(brief, offer(country="France", city="Lyon"))
    germany = match(brief, offer(country="Germany", city="Frankfurt"))
    assert france["score"] == france["total_score"]
    assert germany["score"] == germany["total_score"]
    assert france["score"] == france["base_score"] - 50
    assert germany["score"] == min(100, germany["base_score"] + 20)


def test_vocabulary_exposes_the_country_labels() -> None:
    """Le formulaire peut afficher les pays sans rien inventer."""
    rendered = vocabulary()
    labels = {entry["code"]: entry["label"] for entry in rendered["countries"]}
    assert labels["DE"] == "Allemagne"
    assert labels["FR"] == "France"
    assert rendered["geo_preferred_boost"] == 20
    assert rendered["geo_excluded_penalty"] == -50


def test_the_brief_api_accepts_the_country_lists(tmp_path) -> None:
    """La personne règle la règle géographique depuis le brief enregistré."""
    service = CareerService(tmp_path)
    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        response = client.put("/api/career/stage-search", json={
            "domains": ["Corporate Finance"],
            "preferred_countries": ["DE", "GB"],
            "geo_excluded_countries": ["IT"],
        })
        assert response.status_code == 200
        saved = response.json()["brief"]
    assert saved["preferred_countries"] == ["DE", "GB"]
    assert saved["geo_excluded_countries"] == ["IT"]


def test_the_brief_api_keeps_the_local_defaults_when_nothing_is_set(tmp_path) -> None:
    """Un brief sans critère géographique garde les défauts du produit."""
    service = CareerService(tmp_path)
    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        response = client.put("/api/career/stage-search", json={"domains": ["Corporate Finance"]})
        assert response.status_code == 200
        saved = response.json()["brief"]
    assert saved["preferred_countries"] == list(DEFAULT_PREFERRED_COUNTRIES)
    # The penalty list follows the exclusions the product already offers: the
    # wording may be a code ("FR") or a name ("France"), the rule is the same.
    assert saved["geo_excluded_countries"] == ["France"]
    assert score_brief_match(saved, offer(country="France", city="Lyon"))["geo_score"] == -50
    assert score_brief_match(saved, offer(country="Germany", city="Berlin"))["geo_score"] == 20
