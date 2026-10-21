"""Adversarial regression suite for SPEC-SK-06 (multi-source deduplication).

This suite was written during the revalidation of the mission: it attacks the
non-negotiable guardrails of SPEC-SK-06 from the outside, with the payloads a
real connector produces (a city written with its region, a country written in
the local spelling, a relevance score carried by one record only).

Every case is synthetic: no network call, no database, no personal data.
"""

from __future__ import annotations

import copy
import itertools

import pytest

from career.job_deduplication import (
    MERGED_PROVENANCES_FIELD,
    USER_SCORE_FIELDS,
    USER_SIDE_FIELDS,
    USER_STATE_FIELDS,
    canonical_city,
    deduplicate_jobs,
    deduplicate_offers,
    location_canonical,
    match_records,
    title_role_level,
)


# ---------------------------------------------------------------------------
# Synthetic record factory (mirrors the connector vocabulary)
# ---------------------------------------------------------------------------

def offer(
    source: str,
    *,
    id: str = "",
    url: str = "",
    company: str = "Acme",
    title: str = "Corporate Finance Intern",
    city: str = "Paris",
    country: str = "France",
    posted: str = "2026-01-01",
    start_date: str = "",
    external_id: str = "",
    role_level: str = "",
    verified: bool = True,
    extra: dict | None = None,
) -> dict:
    record = {
        "company": company,
        "title": title,
        "source_name": source,
        "source_id": id,
        "official_url": url,
        "apply_url": "",
        "city": city,
        "country": country,
        "posted_date": posted,
        "start_date": start_date,
        "external_id": external_id,
        "role_level": role_level,
        "source_verified": verified,
    }
    record.update(extra or {})
    return record


def identity(record: dict) -> str:
    """Return a stable identity of a record, independent of its position."""
    return f"{record.get('source_name', '')}:{record.get('source_id', '')}"


def partition(records: list[dict]) -> list[frozenset[str]]:
    """Return the grouping of the records, by content and not by position."""
    groups = deduplicate_jobs([dict(record) for record in records])
    partitions = [
        frozenset(identity(view["record"]) for view in group["provenances"])
        for group in groups
    ]
    return sorted(partitions, key=lambda members: sorted(members))


# ---------------------------------------------------------------------------
# Guardrail: the relevance score of the user never decides
# ---------------------------------------------------------------------------

def test_the_presence_of_a_relevance_field_never_changes_the_representative():
    """A record that carries a relevance score must not be elected because of it.

    Two records of the same quality are the only ones that can be separated by
    the completeness tie-break: a relevance score must not even count as a
    fact about the offer.
    """
    baseline = [
        offer("employer", id="a"),
        offer("employer", id="b"),
    ]
    scored = [
        dict(baseline[0]),
        {**baseline[1], "user_score": 3},
    ]
    assert deduplicate_jobs(baseline)[0]["best"]["source_id"] == "a"
    assert deduplicate_jobs(scored)[0]["best"]["source_id"] == "a"


def test_a_relevance_score_never_changes_the_representative_in_any_position():
    """Whether the score is on the first or on the second record changes nothing."""
    baseline = [offer("employer", id="a"), offer("employer", id="b")]
    expected = deduplicate_jobs(baseline)[0]["best"]["source_id"]
    for index in (0, 1):
        scored = [dict(record) for record in baseline]
        scored[index]["user_score"] = 99
        assert deduplicate_jobs(scored)[0]["best"]["source_id"] == expected
        scored[index]["relevance"] = "perfect"
        assert deduplicate_jobs(scored)[0]["best"]["source_id"] == expected


def test_a_personal_note_never_changes_the_representative():
    """A note, a shortlist or an application belong to the reader, not to the offer."""
    baseline = [offer("employer", id="a"), offer("employer", id="b")]
    expected = deduplicate_jobs(baseline)[0]["best"]["source_id"]
    for field in sorted(USER_STATE_FIELDS):
        if field in {"note", "notes", "user_notes"}:
            continue
        annotated = [dict(record) for record in baseline]
        annotated[1][field] = "2026-02-01"
        assert deduplicate_jobs(annotated)[0]["best"]["source_id"] == expected


def test_the_relevance_vocabulary_is_part_of_the_user_side_vocabulary():
    assert USER_SIDE_FIELDS >= USER_SCORE_FIELDS
    assert USER_SIDE_FIELDS >= {"notes", "shortlisted", "applied"}


# ---------------------------------------------------------------------------
# Guardrail: the location of the offer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Paris", "paris"),
    ("Paris, France", "paris"),
    ("Paris, Île-de-France", "paris"),
    ("PARIS", "paris"),
    ("Paris La Défense", "paris"),
    ("75001 Paris", "paris"),
    ("Paris (75)", "paris"),
    ("Berlin, Germany", "berlin"),
    ("Amsterdam, Noord-Holland", "amsterdam"),
    ("Lyon, Auvergne-Rhône-Alpes", "lyon"),
    ("Berlin Germany", "berlin"),
    ("10 rue de Rivoli, Paris", "paris"),
    ("Remote", "remote"),
])
def test_a_city_written_with_its_region_is_the_same_city(raw: str, expected: str):
    """The region never contradicts another source: it is not part of the city."""
    assert canonical_city(raw) == expected


def test_an_offer_published_with_its_region_is_the_same_offer():
    """The same offer, written "Paris, France" by one board and "Paris" by
    another one, is one offer and not two."""
    board = offer("greenhouse", id="1", url="https://boards.greenhouse.io/acme/jobs/1",
                  city="Paris, France")
    employer = offer("employer", id="e1", url="https://careers.acme.com/jobs/1",
                     city="Paris", title="Corporate Finance Internship")
    decision = match_records(board, employer)
    assert decision["matches"] is True
    assert decision["reasons"] == ["same_role_concept"]


def test_an_unknown_country_stays_unknown_and_never_contradicts():
    """A country that is not in the table must not be reduced to a prefix."""
    assert location_canonical("Amsterdam", "Nederland") == "amsterdam,nl"
    assert location_canonical("Amsterdam", "Freedonia") == "amsterdam"
    left = offer("greenhouse", id="1", city="Amsterdam", country="Freedonia")
    right = offer("lever", id="2", city="Amsterdam", country="Freedonia")
    assert match_records(left, right)["matches"] is True


def test_two_different_known_countries_still_refuse_to_merge():
    """A real country difference is still a contradiction."""
    left = offer("greenhouse", id="1", city="Paris", country="France")
    right = offer("lever", id="2", city="Paris", country="Germany")
    decision = match_records(left, right)
    assert decision["matches"] is False
    assert decision["reasons"] == ["city_conflict"]


def test_two_different_cities_still_refuse_to_merge():
    left = offer("greenhouse", id="1", city="Paris")
    right = offer("lever", id="2", city="Lyon")
    assert match_records(left, right)["reasons"] == ["city_conflict"]


# ---------------------------------------------------------------------------
# Guardrail: two different roles are never merged
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("left_title, right_title", [
    ("Stagiaire Data Analyst", "Apprenti Data Analyst"),
    ("Senior Data Analyst", "Junior Data Analyst"),
    ("Data Analyst CDI", "Data Analyst CDD"),
    ("Financial Analyst Director", "Financial Analyst"),
    ("Data Analyst Intern 2027", "Data Analyst Intern 2028"),
])
def test_two_different_roles_are_never_merged(left_title: str, right_title: str):
    left = offer("greenhouse", id="1", title=left_title)
    right = offer("lever", id="2", title=right_title)
    decision = match_records(left, right)
    assert decision["matches"] is False
    assert decision["reasons"][0] in {"role_level_conflict", "cohort_conflict"}


def test_the_role_level_is_read_before_the_analyst_marker():
    assert title_role_level("Financial Analyst Director") == "experienced"
    assert title_role_level("Financial Analyst") == "analyst"


def test_two_editions_of_the_same_programme_are_never_merged():
    left = offer("greenhouse", id="1", start_date="2026-06-01")
    right = offer("lever", id="2", start_date="2027-01-05")
    assert match_records(left, right)["reasons"] == ["start_date_conflict"]


def test_a_recycled_identifier_keeps_two_offers_apart():
    left = offer("greenhouse", id="1", title="Data Analyst Intern")
    right = offer("greenhouse", id="1", title="Data Engineer Intern")
    assert match_records(left, right)["reasons"] == ["recycled_identifier_conflict"]


def test_a_translation_on_generic_words_only_is_refused():
    left = offer("greenhouse", id="1", title="Stage")
    right = offer("lever", id="2", title="Intern")
    assert match_records(left, right)["reasons"] == ["translation_common_words_only"]


def test_two_employers_are_never_merged():
    left = offer("greenhouse", id="1", company="Acme")
    right = offer("lever", id="2", company="Globex")
    assert match_records(left, right)["reasons"] == ["company_conflict"]


# ---------------------------------------------------------------------------
# Guardrail: the decision is pure, symmetric and independent of the order
# ---------------------------------------------------------------------------

def test_the_decision_is_symmetric():
    left = offer("greenhouse", id="1", url="https://boards.greenhouse.io/acme/jobs/1")
    right = offer("employer", id="2", url="https://careers.acme.com/jobs/1",
                  title="Corporate Finance Internship")
    assert match_records(left, right)["matches"] == match_records(right, left)["matches"]


def test_the_records_received_are_never_modified():
    left = offer("greenhouse", id="1", url="https://boards.greenhouse.io/acme/jobs/1")
    right = offer("employer", id="2", url="https://careers.acme.com/jobs/1",
                  title="Corporate Finance Internship")
    snapshot = copy.deepcopy((left, right))
    deduplicate_jobs([left, right])
    assert (left, right) == snapshot


def test_the_grouping_does_not_depend_on_the_order_of_the_records():
    records = [
        offer("greenhouse", id="1", url="https://boards.greenhouse.io/acme/jobs/1",
              title="Data Analyst Intern"),
        offer("lever", id="2", url="https://jobs.lever.co/acme/2",
              title="Data Analyst Internship"),
        offer("apec", id="3", city="Lyon", title="Data Analyst Intern"),
        offer("greenhouse", id="4", url="https://boards.greenhouse.io/globex/jobs/4",
              company="Globex", title="Senior Data Analyst"),
        offer("ashby", id="5", url="https://jobs.ashbyhq.com/globex/5",
              company="Globex", title="Senior Data Analyst"),
        offer("greenhouse", id="6", url="https://boards.greenhouse.io/initech/jobs/6",
              company="Initech", title="Product Manager Intern", city="Berlin"),
    ]
    expected = partition(records)
    assert len(expected) == 4
    for permutation in itertools.permutations(range(len(records))):
        shuffled = [records[index] for index in permutation]
        assert partition(shuffled) == expected


# ---------------------------------------------------------------------------
# Guardrail: every proof of the merge stays visible
# ---------------------------------------------------------------------------

def test_every_provenance_and_every_contradiction_stays_visible():
    records = [
        offer("greenhouse", id="1", url="https://boards.greenhouse.io/acme/jobs/1",
              posted="2026-01-01", city="Paris", external_id="X-1"),
        offer("employer", id="2", url="https://careers.acme.com/jobs/1",
              title="Corporate Finance Internship", posted="2026-02-01", city="Lyon",
              external_id="X-1"),
    ]
    groups = deduplicate_jobs(records)
    assert len(groups) == 1
    group = groups[0]
    assert len(group["provenances"]) == 2
    # The employer page stays the primary source, the board is absorbed.
    assert group["best"]["source_name"] == "employer"
    assert group["merged_from"] == ["greenhouse"]
    assert "posted_date" in group["conflicts"]
    assert "city" in group["conflicts"]
    assert {view["source_name"] for view in group["provenances"]} == {"greenhouse", "employer"}


# ---------------------------------------------------------------------------
# Guardrail: a shared link is not a proof when the roles are different
# ---------------------------------------------------------------------------

LANDING_PAGE = "https://careers.acme.com/careers"


def test_a_shared_landing_page_never_merges_two_different_roles():
    """A careers landing page hosts several postings: they must stay apart.

    Before the fix, five roles published under the same link were merged into
    a single offer, which destroyed four real postings.
    """
    records = [
        offer("greenhouse", id=str(index), url=LANDING_PAGE, title=title)
        for index, title in enumerate([
            "Software Engineer", "Product Manager", "Data Scientist",
            "Sales Intern", "HR Manager",
        ])
    ]
    groups = deduplicate_jobs(records)
    assert len(groups) == 5
    assert all(not group["merged"] for group in groups)
    assert len({group["best"]["title"] for group in groups}) == 5


def test_a_shared_link_never_overrides_a_known_role_conflict():
    """Two known business concepts that differ are two different jobs."""
    left = offer("greenhouse", id="1", url=LANDING_PAGE, title="Data Analyst")
    right = offer("greenhouse", id="2", url=LANDING_PAGE, title="Financial Analyst")
    decision = match_records(left, right)
    assert decision["matches"] is False
    assert decision["reasons"] == ["different_role_same_employer"]


def test_a_shared_link_without_a_title_is_still_a_duplicate():
    """A board may publish a posting without its title: the link then decides."""
    left = offer("greenhouse", id="1", url=LANDING_PAGE, title="")
    right = offer("greenhouse", id="2", url=LANDING_PAGE, title="Data Analyst")
    decision = match_records(left, right)
    assert decision["matches"] is True
    assert decision["reasons"] == ["canonical_url_match"]


def test_a_shared_link_still_merges_the_same_role_written_twice():
    left = offer("greenhouse", id="1", url=LANDING_PAGE, title="Data Analyst")
    right = offer("greenhouse", id="2", url=LANDING_PAGE, title="Analyste de donnees")
    decision = match_records(left, right)
    assert decision["matches"] is True
    assert decision["reasons"] == ["canonical_url_match"]


# ---------------------------------------------------------------------------
# Guardrail: the trace of a merged offer opens with the official source
# ---------------------------------------------------------------------------

def test_the_official_source_opens_the_trace_of_a_merged_group():
    """The elected representative is the first provenance of the group."""
    records = [
        offer("greenhouse", id="1", url="https://boards.greenhouse.io/acme/jobs/1",
              title="Data Analyst Intern", extra={"source_trust": "unverified"}),
        offer("employer", id="2", url="https://careers.acme.com/jobs/1",
              title="Data Analyst Internship", extra={"source_trust": "verified"}),
        offer("lever", id="3", url="https://jobs.lever.co/acme/3",
              title="Data Analyst Internship", extra={"source_trust": "unverified"}),
    ]
    group = deduplicate_jobs(records)[0]
    assert group["best"]["source_name"] == "employer"
    assert group["provenances"][0]["is_representative"] is True
    assert group["provenances"][0]["source_name"] == "employer"


def test_the_merged_offer_carries_every_provenance():
    """A merged offer stays traceable: every source keeps its link."""
    offers, report = deduplicate_offers([
        offer("greenhouse", id="1", url="https://boards.greenhouse.io/acme/jobs/1",
              title="Data Analyst Intern"),
        offer("lever", id="2", url="https://jobs.lever.co/acme/2",
              title="Data Analyst Internship"),
    ])
    assert len(offers) == 1
    merged = offers[0]
    assert merged["merged_from"] == ["lever"]
    assert merged["merge_count"] == 1
    provenances = merged[MERGED_PROVENANCES_FIELD]
    assert [view["source_name"] for view in provenances] == ["greenhouse", "lever"]
    assert {view["official_url"] for view in provenances} == {
        "https://boards.greenhouse.io/acme/jobs/1",
        "https://jobs.lever.co/acme/2",
    }
    assert sum(1 for view in provenances if view["is_representative"]) == 1
    assert report.clusters[0]["size"] == 2
