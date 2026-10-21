"""Contract tests for the source material transmitted by the eight connectors.

One synthetic fixture per provider lives in ``tests/fixtures/connectors_enrich``.
The fixtures are synthetic: they are shaped after the documented shape of each
feed, and no live board is contacted.  The real, bounded control of the same
contract lives in ``tests/test_connectors_enrich_live.py`` and never runs by
default.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from career.connectors import apec as apec_module
from career.connectors import jobteaser as jobteaser_module
from career.connectors import talent_com as talent_com_module
from career.connectors import welcome_jungle as welcome_jungle_module
from career.connectors.public_ats import AshbyConnector, LeverConnector, SmartRecruitersConnector
from career.discovery import GreenhouseBoard, GreenhouseJobBoardConnector
from career.source_fields import (
    CONFLICTS_KEY,
    CONTRACT_KEY,
    MAX_FIELD_TEXT,
    collect_source_fields,
    detect_source_conflicts,
)


FIXTURES = Path(__file__).parent / "fixtures" / "connectors_enrich"

PROVIDERS = (
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "welcome_jungle",
    "jobteaser",
    "talent_com",
    "apec",
)

# The published fields each provider is expected to transmit, under the exact
# name the source uses.
EXPECTED_FIELDS: dict[str, tuple[str, ...]] = {
    "greenhouse": ("id", "requisition_id", "internal_job_id", "first_published", "updated_at",
                   "application_deadline", "company_name", "language", "location", "education",
                   "metadata", "offices", "departments"),
    "lever": ("id", "text", "createdAt", "hostedUrl", "applyUrl", "country", "workplaceType",
              "categories", "openingPlain", "additionalPlain", "lists"),
    "ashby": ("id", "title", "publishedAt", "employmentType", "workplaceType", "isRemote",
              "isListed", "department", "team", "secondaryLocations", "location", "address",
              "jobUrl", "applyUrl"),
    "smartrecruiters": ("id", "name", "requisitionId", "postedDate", "releasedDate", "location",
                         "typeOfEmployment", "department", "company", "applyUrl", "ref",
                         "jobAd.sections"),
    "welcome_jungle": ("title", "company", "location", "contract_type", "url", "data-posted-at",
                       "datetime"),
    "jobteaser": ("title", "company", "location", "contract_type", "url", "data-posted-at", "datetime"),
    "talent_com": ("title", "company", "location", "contract_type", "url", "data-job-id",
                   "data-rank", "datetime"),
    "apec": ("title", "company", "location", "contract_type", "url", "data-offer-id", "datetime"),
}

# The published contract type of each provider, and the wording that
# contradicts it in the second posting of each fixture.
PUBLISHED_CONTRACT = {
    "greenhouse": "Internship",
    "lever": "Internship",
    "ashby": "Internship",
    "smartrecruiters": "Internship",
    "welcome_jungle": "Internship",
    "jobteaser": "Internship",
    "talent_com": "Internship",
    "apec": "STAGE",
}


class FixtureFetch:
    """Return a prepared HTML page; sockets stay blocked."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    def __call__(self, url: str) -> str | None:
        self.calls.append(url)
        if not self.responses:
            raise AssertionError("fixture fetch exhausted")
        return self.responses.pop(0)


def _fixture(provider: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{provider}.json").read_text(encoding="utf-8"))


def _source(provider: str) -> dict[str, Any]:
    return {
        "id": f"synthetic:{provider}:board",
        "provider": provider,
        "company": "Synthetic Finance",
        "board_token": "synthetic-board",
        "verified_at": "2026-10-18T00:00:00Z",
        "provenance_url": "https://careers.example.test/",
    }


def _cards_html(provider: str, cards: list[dict[str, Any]]) -> str:
    """Render the synthetic cards the way each board publishes them."""
    blocks: list[str] = []
    for card in cards:
        attributes = " ".join(f'{name}="{value}"' for name, value in card.get("attributes", {}).items())
        published_time = card.get("time", "")
        time_markup = f'<time datetime="{published_time}"></time>' if published_time else ""
        if provider == "welcome_jungle":
            blocks.append(f"""
            <article data-testid="job-card" {attributes}>
                <h3 data-testid="job-title">{card["title"]}</h3>
                <span data-testid="company">{card["company"]}</span>
                <span data-testid="location">{card["location"]}</span>
                <span data-testid="contract">{card["contract_type"]}</span>
                {time_markup}
                <a href="{card["url"].replace("https://www.welcometothejungle.com", "")}"></a>
                <div data-testid="description">{card["description"]}</div>
            </article>""")
        elif provider == "jobteaser":
            blocks.append(f"""
            <article class="job-card" {attributes}>
                <h3 class="title">{card["title"]}</h3>
                <span class="company">{card["company"]}</span>
                <span class="location">{card["location"]}</span>
                <span class="contract">{card["contract_type"]}</span>
                {time_markup}
                <a href="{card["url"].replace("https://www.jobteaser.com", "")}"></a>
                <div class="description">{card["description"]}</div>
            </article>""")
        elif provider == "talent_com":
            blocks.append(f"""
            <div class="job-card" {attributes}>
                <h2 class="title">{card["title"]}</h2>
                <span class="company">{card["company"]}</span>
                <span class="location">{card["location"]}</span>
                <span class="contract">{card["contract_type"]}</span>
                {time_markup}
                <a href="{card["url"].replace("https://www.talent.com", "")}"></a>
                <div class="description">{card["description"]}</div>
            </div>""")
        else:
            blocks.append(f"""
            <div class="job-result" {attributes}>
                <h2 class="title">{card["title"]}</h2>
                <span class="entreprise">{card["company"]}</span>
                <span class="lieu">{card["location"]}</span>
                <span class="contrat">{card["contract_type"]}</span>
                {time_markup}
                <a href="{card["url"].replace("https://www.apec.fr", "")}"></a>
                <div class="description">{card["description"]}</div>
            </div>""")
    return f"<html><body>{''.join(blocks)}</body></html>"


def _material(provider: str) -> list[dict[str, Any]]:
    """Return the material a connector transmits, before any admission.

    The connectors are read at the level where they only publish what the
    source published: the admission layer is exercised by the exploration
    tests, not by the contract of the transmitted material.
    """
    fixture = _fixture(provider)
    if provider == "greenhouse":
        board = GreenhouseBoard("synthetic-board", "Synthetic Finance", "synthetic-board")
        result = GreenhouseJobBoardConnector._normalise(board, {"jobs": fixture["jobs"]})
        return list(result.jobs)
    if provider == "lever":
        return LeverConnector(enabled=True).parse(_source(provider), fixture["postings"])
    if provider == "ashby":
        return AshbyConnector(enabled=True).parse(_source(provider), fixture["payload"])
    if provider == "smartrecruiters":
        return SmartRecruitersConnector(enabled=True).parse(_source(provider), fixture["payload"])
    module = {
        "welcome_jungle": welcome_jungle_module,
        "jobteaser": jobteaser_module,
        "talent_com": talent_com_module,
        "apec": apec_module,
    }[provider]
    html = _cards_html(provider, fixture["cards"])
    return list(module._iter_raw_offers(fetch=FixtureFetch([html])))


@pytest.mark.parametrize("provider", PROVIDERS)
def test_every_connector_transmits_the_published_fields(provider: str) -> None:
    jobs = _material(provider)
    assert len(jobs) == 2
    for job in jobs:
        block = job[CONTRACT_KEY]
        assert list(block) == [provider]
        assert block[provider], "the connector transmitted no published field"
        assert job["description_original"].strip(), "the published description was not transmitted"
    # The complete posting carries every published field of its provider.
    published = jobs[0][CONTRACT_KEY][provider]
    for name in EXPECTED_FIELDS[provider]:
        assert name in published, f"{provider} did not transmit the field {name!r}"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_transmitted_values_are_json_safe_and_bounded(provider: str) -> None:
    for job in _material(provider):
        block = job[CONTRACT_KEY]
        # The whole block must survive a JSON round trip: it travels with the
        # offer and reaches the database and the interface.
        assert json.loads(json.dumps(block, ensure_ascii=False)) == block
        for value in block[provider].values():
            if isinstance(value, str):
                assert len(value) <= MAX_FIELD_TEXT


@pytest.mark.parametrize("provider", PROVIDERS)
def test_published_description_is_transmitted_as_published(provider: str) -> None:
    description = _material(provider)[0]["description_original"]
    assert "<" not in description
    assert "Bachelor" in description or "Finance" in description


def test_greenhouse_publication_date_comes_from_the_published_field() -> None:
    clean, _contradicting = _material("greenhouse")
    assert clean["posted_date"] == "2026-10-08"
    assert clean["deadline_date"] == "2026-11-30"
    assert clean[CONTRACT_KEY]["greenhouse"]["first_published"] == "2026-10-08T06:02:11-04:00"
    # The maintenance timestamp is transmitted, but it is never a publication
    # date: an absent publication date stays unknown.
    assert clean[CONTRACT_KEY]["greenhouse"]["updated_at"] == "2026-10-19T11:45:02-04:00"


def test_greenhouse_without_publication_date_keeps_the_calendar_unknown() -> None:
    fixture = _fixture("greenhouse")
    job = dict(fixture["jobs"][0])
    job.pop("first_published")
    job["updated_at"] = "2026-10-19T11:45:02-04:00"
    board = GreenhouseBoard("synthetic-board", "Synthetic Finance", "synthetic-board")
    result = GreenhouseJobBoardConnector._normalise(board, {"jobs": [job]})
    assert result.jobs[0]["posted_date"] == ""
    assert result.jobs[0][CONTRACT_KEY]["greenhouse"]["updated_at"] == "2026-10-19T11:45:02-04:00"


def test_ashby_publication_date_comes_from_the_published_field() -> None:
    clean, _contradicting = _material("ashby")
    assert clean["posted_date"] == "2026-10-16"
    assert clean[CONTRACT_KEY]["ashby"]["publishedAt"] == "2026-10-16T14:26:30.060+00:00"


def test_smartrecruiters_dates_come_from_the_published_fields() -> None:
    clean, _contradicting = _material("smartrecruiters")
    assert clean["posted_date"] == "2026-10-01"
    published = clean[CONTRACT_KEY]["smartrecruiters"]
    assert published["postedDate"] == "2026-10-03T08:00:00Z"
    assert published["releasedDate"] == "2026-10-01T09:00:00Z"


def test_lever_timestamp_is_transmitted_without_becoming_a_date() -> None:
    clean, _contradicting = _material("lever")
    # ``createdAt`` is a raw timestamp the source did not label as a date:
    # it is transmitted under its own name, and the calendar stays unknown.
    assert clean["posted_date"] == ""
    assert clean[CONTRACT_KEY]["lever"]["createdAt"] == 1791900863876


def test_smartrecruiters_sections_reach_the_description() -> None:
    clean, _contradicting = _material("smartrecruiters")
    description = clean["description_original"]
    assert "Bachelor's degree in Finance or Economics" in description
    assert "Excel mastery" in description
    assert clean[CONTRACT_KEY]["smartrecruiters"]["jobAd.sections"]["qualifications"]


def test_card_attributes_are_transmitted_under_their_own_name() -> None:
    talent = _material("talent_com")
    assert talent[0][CONTRACT_KEY]["talent_com"]["data-job-id"] == "synthetic-job-001"
    assert talent[0][CONTRACT_KEY]["talent_com"]["data-rank"] == "1"
    assert talent[0][CONTRACT_KEY]["talent_com"]["datetime"] == "2026-10-06T15:57:18Z"
    apec = _material("apec")
    assert apec[0][CONTRACT_KEY]["apec"]["data-offer-id"] == "synthetic-offer-001"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_contradiction_between_the_published_field_and_the_text_is_preserved(provider: str) -> None:
    _clean, contradicting = _material(provider)
    conflicts = contradicting[CONFLICTS_KEY]
    assert conflicts, f"{provider} dropped the contradiction between the field and the text"
    contract = [item for item in conflicts if item["kind"] == "contract"]
    assert contract, f"{provider} did not report the contradiction of the contract type"
    conflict = contract[0]
    assert conflict["source_value"] == PUBLISHED_CONTRACT[provider]
    assert conflict["description_value"].upper() in {"CDI", "PERMANENT"}
    # The quote is taken verbatim from the published description.
    assert conflict["quote"] in contradicting["description_original"]
    # The contradiction is reported, never arbitrated: the published value and
    # the published text both stay in the offer.
    assert contradicting["employment_type"] not in {"CDI", "Permanent", "permanent"}
    assert PUBLISHED_CONTRACT[provider] in json.dumps(
        contradicting[CONTRACT_KEY][provider], ensure_ascii=False
    )
    assert "CDI" in contradicting["description_original"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_no_contradiction_is_reported_when_the_text_agrees(provider: str) -> None:
    clean, _contradicting = _material(provider)
    assert clean[CONFLICTS_KEY] == []


def test_duration_contradiction_is_preserved_and_never_arbitrated() -> None:
    job = {"employment_type": "Internship", "duration_months": 6}
    conflicts = detect_source_conflicts(job, "This is a 3-month placement.")
    assert [item["kind"] for item in conflicts] == ["duration"]
    assert conflicts[0]["source_value"] == 6
    assert conflicts[0]["description_value"].strip() == "3-month"
    assert conflicts[0]["quote"] in "This is a 3-month placement."


def test_an_agreeing_duration_is_not_a_contradiction() -> None:
    job = {"employment_type": "Internship", "duration_months": 6}
    assert detect_source_conflicts(job, "This is a 6-month placement.") == []


def test_empty_published_values_are_not_transmitted() -> None:
    published = collect_source_fields("synthetic", {
        "empty": "",
        "blank": "   ",
        "missing": None,
        "empty_list": [],
        "empty_object": {},
        "kept": "value",
    })
    assert published == {"synthetic": {"kept": "value"}}


def test_published_values_are_bounded() -> None:
    published = collect_source_fields("synthetic", {
        "long_text": "x" * (MAX_FIELD_TEXT * 3),
        "long_list": list(range(500)),
        "kept": 1,
    })
    assert len(published["synthetic"]["long_text"]) == MAX_FIELD_TEXT
    assert len(published["synthetic"]["long_list"]) <= 25
    assert published["synthetic"]["kept"] == 1


def test_a_provider_name_is_required() -> None:
    with pytest.raises(ValueError):
        collect_source_fields("not a provider", {"field": "value"})


def test_every_connector_publishes_the_same_contract() -> None:
    canonical = {
        "company", "title", "source_name", "source_id", "official_url", "city", "country",
        "posted_date", "deadline_date", "start_date", "end_date", "duration_months",
        "source_status", "source_verified", "employment_type", "role_level", "requirements",
        "languages_required", "eligibility_requirement", "description_original",
        CONTRACT_KEY, CONFLICTS_KEY,
    }
    for provider in PROVIDERS:
        job = _material(provider)[0]
        missing = canonical - set(job)
        assert not missing, f"{provider} does not publish {sorted(missing)}"


def test_connectors_do_not_decide_the_qualification() -> None:
    """A connector transmits; the admission layer decides.

    The check is structural: no connector may import the qualification or the
    admission rules, and every connector must use the shared admission layer.
    """
    connectors = Path("career/connectors")
    modules = sorted(connectors.glob("*.py")) + [Path("career/discovery.py")]
    for module in modules:
        source = module.read_text(encoding="utf-8")
        assert "qualify_offer" not in source, f"{module} still qualifies an offer"
        assert "classify_internship" not in source, f"{module} still classifies an offer"
        assert "criteria_admit" not in source, f"{module} still admits an offer"
        if module.name in {"public_ats.py", "welcome_jungle.py", "jobteaser.py",
                           "talent_com.py", "apec.py", "discovery.py"}:
            assert "admit_offer" in source, f"{module} does not use the admission layer"


def test_the_transmitted_material_survives_the_admission_layer() -> None:
    """The admission layer decides; it never drops what the source published."""
    from career.exploration import admit_offer
    from career.stage_search import default_brief

    job = _material("lever")[0]
    verdict = admit_offer(job, default_brief())
    decided = verdict["job"]
    assert decided[CONTRACT_KEY] == job[CONTRACT_KEY]
    assert decided[CONFLICTS_KEY] == job[CONFLICTS_KEY]
    assert decided["description_original"] == job["description_original"]


def test_the_published_prerequisites_reach_the_requirements_layer() -> None:
    """The published sections are what the requirements layer reads.

    SmartRecruiters publishes its prerequisites in the ``qualifications``
    section of the advertisement.  When the connector transmits that section,
    the prerequisites are found; when it is dropped, they are lost.
    """
    from career.offer_requirements import analyze_offer

    clean, _contradicting = _material("smartrecruiters")
    analysis = analyze_offer(clean)
    texts = [record["text"] for record in analysis["requirements"]]
    assert "Bachelor's degree in Finance or Economics" in texts
    assert "Excel mastery" in texts
    # Every requirement points at the published text it was read from.
    for record in analysis["requirements"]:
        assert record["source_field"] == "description_original"
    # The section published after the prerequisites is not a prerequisite.
    assert "Start date: 2 March 2027." not in texts


def test_the_published_sections_keep_the_name_the_source_publishes() -> None:
    clean, _contradicting = _material("smartrecruiters")
    description = clean["description_original"]
    assert "Company description" in description
    assert "Job description" in description
    assert "Qualifications" in description
    assert "Additional information" in description
    # The sections are composed in the order the source publishes them.
    assert description.index("Company description") < description.index("Job description")
    assert description.index("Job description") < description.index("Qualifications")
    assert description.index("Qualifications") < description.index("Additional information")


def test_talent_com_reads_the_published_offer_link() -> None:
    """Talent.com publishes ``/view?id=<identifier>``: the identifier is a query.

    A link the connector does not recognise is an offer it transmits nothing
    about, so the published shape is the one that is accepted.
    """
    from career.connectors.talent_com import _is_offer_link

    assert _is_offer_link("/view?id=640740450432454540")
    assert _is_offer_link("/view/640740450432454540")
    assert _is_offer_link("/job/financial-analyst-intern-london")
    assert not _is_offer_link("/jobs")
    assert not _is_offer_link("/viewer")

    clean, _contradicting = _material("talent_com")
    assert clean["official_url"] == "https://www.talent.com/view?id=synthetic-job-001"
    assert clean[CONTRACT_KEY]["talent_com"]["url"] == clean["official_url"]


def test_a_card_that_publishes_a_snippet_transmits_it_as_description() -> None:
    """Talent.com publishes the summary of an offer in its snippet."""
    html = """
    <div class="job-card" data-job-id="synthetic-job-003">
        <h2 class="JobCard_title__X32Qk">Synthetic Snippet Intern</h2>
        <span class="JobCard_company__NmRol">Synthetic Group</span>
        <span class="JobCard_location__nmTtw">London, United Kingdom</span>
        <p class="JobCard_snippet__rqX60">Synthetic published summary of the offer.</p>
        <a href="/view?id=synthetic-job-003"></a>
    </div>"""
    jobs = list(talent_com_module._iter_raw_offers(fetch=FixtureFetch([html])))
    assert len(jobs) == 1
    assert "Synthetic published summary" in jobs[0]["description_original"]
    assert jobs[0]["official_url"] == "https://www.talent.com/view?id=synthetic-job-003"


def test_the_html_connectors_verify_the_server_certificate() -> None:
    """A board that cannot be read securely transmits nothing at all.

    Without a CA bundle, the four HTML connectors fail with an opaque network
    error on every page: the published material never reaches the contract.
    """
    import ssl

    from career.connectors.http import ssl_context

    context = ssl_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True

    for module in (welcome_jungle_module, jobteaser_module, talent_com_module, apec_module):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "context=ssl_context()" in source, (
            f"{module.__name__} reads a public page without verifying the certificate"
        )
