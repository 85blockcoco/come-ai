"""SPEC-SK-06 — Multi-source job deduplication with proof retention.

The synthetic corpus lives in ``tests/fixtures/job_deduplication/``:

- ``pairs.json``: 112 hand-labelled pairs (70 merges, 41 refusals) covering
  the regulated scenarios — tracking parameters, two ATS boards, employer
  page, translated titles, near city spellings, remote, role levels,
  recycled identifiers, reopened postings, incompatible dates, company
  aliases and the non-negotiable guards;
- ``groups.json``: 14 group-level cases (provenance conservation, visible
  contradictions, election of the representative, identifier collision);
- ``truth_corpus.json``: 59 labelled records in 36 groups used to measure the
  precision and the recall of the grouper.

Everything is local, deterministic and offline: no network, no database, no
model, no clock.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import pytest

from career.job_deduplication import (
    CONCEPT_MATCH_SIMILARITY,
    DedupReport,
    MERGED_FROM_FIELD,
    TITLE_SIMILARITY_THRESHOLD,
    TRUST_RANK,
    TRUST_STATUSES,
    USER_SCORE_FIELDS,
    canonical_city,
    canonical_company,
    canonical_title_concept,
    canonicalize_url,
    choose_best,
    company_canonical,
    deduplicate_jobs,
    deduplicate_offers,
    evaluate_deduplication,
    jaro_winkler,
    location_canonical,
    match_records,
    source_priority,
    title_canonical,
    title_concept,
    title_contract,
    title_role_level,
    title_seniority,
    title_similarity,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "job_deduplication"

GH = "https://job-boards.greenhouse.io/lincolninternational/jobs/4012345"
LV = "https://jobs.lever.co/lincoln-international/a1b2c3"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


PAIRS = _load("pairs.json")["cases"]
GROUPS = _load("groups.json")["cases"]
TRUTH = _load("truth_corpus.json")


def ats(provider, *, id="", url=None, apply_url=None, company="", title="", city="",
        country="", posted="", start_date="", verified=True, role_level="",
        duration=None, last_verified_at=None, seen_at=None, trust=None, extra=None):
    """Build a synthetic offer, with the vocabulary of the connectors."""
    record = {
        "company": company,
        "title": title,
        "source_name": provider,
        "source_id": id,
        "official_url": url or "",
        "apply_url": apply_url or "",
        "city": city,
        "country": country,
        "posted_date": posted,
        "start_date": start_date,
        "end_date": "",
        "duration_months": duration,
        "source_status": "open",
        "source_verified": verified,
        "employment_type": "",
        "role_level": role_level,
        "description_original": "",
    }
    if last_verified_at:
        record["last_verified_at"] = last_verified_at
    if seen_at:
        record["seen_at"] = seen_at
    if trust:
        record["source_trust"] = trust
    record.update(extra or {})
    return record


def manual(*, company="", title="", city="", country="", url=None, role_level="",
           posted="", start_date="", trust=None, extra=None):
    """Build a synthetic offer pasted by a person."""
    return ats("manual", id="", url=url, company=company, title=title, city=city,
               country=country, posted=posted, start_date=start_date, role_level=role_level,
               verified=False, trust=trust, extra=extra)


# ---------------------------------------------------------------------------
# 1. The pair corpus
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", PAIRS, ids=[case["id"] for case in PAIRS])
def test_pair_corpus_decides_exactly(case):
    decision = match_records(case["a"], case["b"])
    assert decision["matches"] is case["expect_match"], decision
    assert decision["reasons"][0] == case["expect_reason"], decision
    if not case["expect_match"]:
        assert decision["conflicts"] == [case["expect_reason"]], decision
    else:
        assert decision["conflicts"] == [], decision


def test_pair_corpus_is_large_enough_and_covers_the_scenarios():
    assert len(PAIRS) >= 100
    assert len({case["id"] for case in PAIRS}) == len(PAIRS)
    categories = {case["category"] for case in PAIRS}
    assert categories >= {
        "exact_duplicate", "url_tracking", "employer_page", "translation",
        "different_role", "city_conflict", "company_alias", "reopening",
        "incompatible_dates", "recycled_identifier", "role_level", "guard",
    }
    merged = sum(1 for case in PAIRS if case["expect_match"])
    assert merged >= 50 and len(PAIRS) - merged >= 30


def test_the_decision_does_not_depend_on_the_order_of_the_records():
    for case in PAIRS:
        forward = match_records(case["a"], case["b"])
        backward = match_records(case["b"], case["a"])
        assert forward["matches"] == backward["matches"], case["id"]
        assert forward["reasons"][0] == backward["reasons"][0], case["id"]


def test_the_decision_is_deterministic():
    for case in PAIRS:
        first = match_records(case["a"], case["b"])
        second = match_records(case["a"], case["b"])
        assert first == second, case["id"]


# ---------------------------------------------------------------------------
# 2. The group corpus
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", GROUPS, ids=[case["id"] for case in GROUPS])
def test_group_corpus_behaves_exactly(case):
    groups = deduplicate_jobs(case["records"])
    assert len(groups) == case["expect_groups"], case["id"]
    group = groups[0]
    if case["expect_representative_source"] is not None:
        assert group["best"]["source_name"] == case["expect_representative_source"], case["id"]
    if case["expect_merged_from"] is not None:
        assert group["merged_from"] == case["expect_merged_from"], case["id"]
    if case["expect_conflict_fields"] is not None:
        assert sorted(group["conflicts"]) == sorted(case["expect_conflict_fields"]), case["id"]
    if case["expect_identifier_collision"] is not None:
        assert any(item["identifier_collision"] for item in groups) is case["expect_identifier_collision"], case["id"]
    if case["expect_sources"] is not None:
        assert group["sources"] == case["expect_sources"], case["id"]


def test_every_provenance_stays_consultable():
    records = [
        ats("greenhouse", id="4012345", url=GH, apply_url=GH + "/apply",
            company="Lincoln International", title="M&A Intern", city="Paris", country="France",
            posted="2026-09-30", last_verified_at="2026-10-18T08:00:00+00:00"),
        ats("lever", id="a1b2c3", url=LV,
            apply_url="https://jobs.lever.co/lincoln-international/a1b2c3/apply",
            company="Lincoln International", title="M&A Intern", city="Paris", country="France",
            posted="2026-10-01", seen_at="2026-10-17T10:00:00+00:00"),
        manual(company="Lincoln International", title="Stage Banque d'Affaires", city="Paris",
               posted="2026-10-05"),
    ]
    group = deduplicate_jobs(records)[0]
    assert group["merged"] is True
    assert [view["source_name"] for view in group["provenances"]] == ["greenhouse", "lever", "manual"]
    assert {view["source_id"] for view in group["provenances"]} == {"4012345", "a1b2c3", ""}
    assert all(view["record"] is not None for view in group["provenances"])
    assert group["merged_from"] == ["lever", "manual"]
    assert group["sources"] == ["greenhouse", "lever", "manual"]
    assert group["match_reasons"]


def test_every_record_of_a_group_keeps_its_own_facts():
    records = [
        ats("greenhouse", id="1", url="https://job-boards.greenhouse.io/acme/jobs/1",
            company="Acme", title="Corporate Finance Intern", city="Paris", posted="2026-09-14"),
        ats("lever", id="2", url="https://jobs.lever.co/acme/2",
            company="Acme", title="Corporate Finance Internship", city="Paris", posted="2026-10-01"),
    ]
    group = deduplicate_jobs(records)[0]
    assert {view["record"]["source_name"] for view in group["provenances"]} == {"greenhouse", "lever"}
    assert group["conflicts"]["posted_date"] == {"greenhouse:1": "2026-09-14", "lever:2": "2026-10-01"}


def test_the_deduplication_never_modifies_the_received_records():
    records = [
        ats("greenhouse", id="1", url="https://job-boards.greenhouse.io/acme/jobs/1",
            company="Acme", title="Corporate Finance Intern", city="Paris"),
        ats("lever", id="2", url="https://jobs.lever.co/acme/2",
            company="Acme", title="Corporate Finance Internship", city="Paris"),
    ]
    snapshot = copy.deepcopy(records)
    deduplicate_jobs(records)
    assert records == snapshot


def test_the_deduplication_is_deterministic_and_order_independent():
    records = [
        ats("greenhouse", id="1", url="https://job-boards.greenhouse.io/acme/jobs/1",
            company="Acme", title="Corporate Finance Intern", city="Paris"),
        ats("lever", id="2", url="https://jobs.lever.co/acme/2",
            company="Acme", title="Corporate Finance Internship", city="Paris"),
    ]
    first = deduplicate_jobs(records)
    second = deduplicate_jobs(records)
    assert first == second
    backward = deduplicate_jobs(list(reversed(records)))
    assert len(backward) == len(first) == 1
    assert backward[0]["merged_from"] == first[0]["merged_from"]


# ---------------------------------------------------------------------------
# 3. The labelled corpus: precision and recall
# ---------------------------------------------------------------------------

def test_the_labelled_corpus_is_measures_exactly():
    labels = TRUTH["labels"]
    truth = {index: label for index, label in enumerate(labels)}
    true_pairs = sum(
        1 for first in truth for second in truth
        if first < second and truth[first] == truth[second]
    )
    assert len(truth) == 59
    assert len(set(truth.values())) == 36
    assert true_pairs == 24

    report = evaluate_deduplication(TRUTH["records"], truth)
    assert report["precision"] == 1.0, report
    assert report["recall"] == 1.0, report
    assert report["f1"] == 1.0, report
    assert report["true_pairs"] == float(true_pairs)
    assert report["error_pairs"] == 0.0


def test_the_evaluation_detects_an_over_merge():
    report = evaluate_deduplication(
        [
            manual(company="Mid Cap Partners", title="Stage Corporate Finance", city="Paris"),
            manual(company="Mid Cap Partners", title="Stage Corporate Finance", city="Paris"),
        ],
        {0: "a", 1: "b"},
    )
    assert report["precision"] == 0.0
    assert report["recall"] == 1.0
    assert report["error_pairs"] == 1.0


def test_the_evaluation_detects_a_missed_merge():
    report = evaluate_deduplication(
        [
            ats("greenhouse", id="1", url="https://job-boards.greenhouse.io/a/jobs/1",
                company="A", title="M&A Intern", city="Paris"),
            ats("greenhouse", id="2", url="https://job-boards.greenhouse.io/b/jobs/2",
                company="B", title="M&A Intern", city="Paris"),
        ],
        {0: "a", 1: "a"},
    )
    assert report["precision"] == 1.0
    assert report["recall"] == 0.0
    assert report["error_pairs"] == 1.0


# ---------------------------------------------------------------------------
# 4. The non-negotiable guards
# ---------------------------------------------------------------------------

def test_the_user_relevance_score_never_decides_the_election():
    base = [
        ats("greenhouse", id="5001", url="https://job-boards.greenhouse.io/xtx/jobs/5001",
            company="XTX Markets", title="Software Engineering Intern", city="Amsterdam",
            extra={"user_score": 18}),
        ats("lever", id="xtx-swe", url="https://jobs.lever.co/xtx/xtx-swe",
            company="XTX Markets", title="Software Engineering Internship", city="Amsterdam",
            extra={"user_score": 97, "relevance": "perfect", "match_score": 100}),
    ]
    baseline = deduplicate_jobs([dict(record) for record in base])
    flipped = []
    for record in base:
        clone = dict(record)
        clone["user_score"] = 99 - clone["user_score"]
        flipped.append(clone)
    result = deduplicate_jobs(flipped)
    assert (result[0]["best"]["source_name"], result[0]["best"]["source_id"]) == (
        baseline[0]["best"]["source_name"], baseline[0]["best"]["source_id"],
    )
    assert baseline[0]["best"]["source_name"] == "greenhouse"
    assert len(baseline[0]["provenances"]) == len(result[0]["provenances"]) == 2


def test_the_user_relevance_fields_are_never_read_by_the_decision():
    """The relevance fields are part of the vocabulary, never of the weight."""
    assert USER_SCORE_FIELDS >= {"user_score", "relevance", "match_score"}
    without = deduplicate_jobs([
        ats("greenhouse", id="1", url="https://job-boards.greenhouse.io/acme/jobs/1",
            company="Acme", title="Corporate Finance Intern", city="Paris"),
        ats("lever", id="2", url="https://jobs.lever.co/acme/2",
            company="Acme", title="Corporate Finance Internship", city="Paris"),
    ])
    with_scores = deduplicate_jobs([
        ats("greenhouse", id="1", url="https://job-boards.greenhouse.io/acme/jobs/1",
            company="Acme", title="Corporate Finance Intern", city="Paris",
            extra={"user_score": 1}),
        ats("lever", id="2", url="https://jobs.lever.co/acme/2",
            company="Acme", title="Corporate Finance Internship", city="Paris",
            extra={"user_score": 100}),
    ])
    assert without[0]["best"]["source_name"] == with_scores[0]["best"]["source_name"]


def test_the_official_source_stays_the_primary_one():
    records = [
        ats("greenhouse", id="1", url="https://job-boards.greenhouse.io/acme/jobs/1",
            company="Acme", title="Corporate Finance Intern", city="Paris",
            trust="verified", posted="2026-01-01"),
        ats("employer_official", id="", url="https://www.acme.com/careers/1",
            company="Acme", title="Corporate Finance Intern", city="Paris",
            trust="unverified", posted="2026-10-20"),
        ats("campus_channel", id="3", url="https://jobs.campuschannel.com/acme/3",
            company="Acme", title="Corporate Finance Internship", city="Paris",
            trust="missing", posted="2026-10-21"),
    ]
    group = deduplicate_jobs(records)[0]
    assert group["best"]["source_trust"] == "verified"
    assert group["best"]["source_name"] == "greenhouse"
    assert set(group["sources"]) == {"greenhouse", "employer_official", "campus_channel"}


def test_the_trust_vocabulary_is_the_one_of_the_source_trust_contract():
    assert TRUST_STATUSES == ("verified", "unverified", "contradictory", "missing")
    assert TRUST_RANK["verified"] > TRUST_RANK["unverified"] > TRUST_RANK["missing"] > TRUST_RANK["contradictory"]


def test_a_contradictory_source_never_becomes_the_representative():
    records = [
        ats("lookalike", id="1", url="https://boards.greenhouse.io.acme.test/jobs/1",
            company="Acme", title="Corporate Finance Intern", city="Paris",
            trust="contradictory", posted="2026-10-22"),
        ats("greenhouse", id="2", url="https://job-boards.greenhouse.io/acme/jobs/2",
            company="Acme", title="Corporate Finance Internship", city="Paris",
            trust="unverified", posted="2026-01-01"),
    ]
    group = deduplicate_jobs(records)[0]
    assert group["best"]["source_name"] == "greenhouse"


def test_the_secondary_sources_stay_consultable():
    records = [
        ats("greenhouse", id="1", url="https://job-boards.greenhouse.io/acme/jobs/1",
            company="Acme", title="Corporate Finance Intern", city="Paris"),
        ats("apec", id="2", url="https://www.apec.fr/candidature/2",
            company="Acme", title="Corporate Finance Internship", city="Paris"),
    ]
    group = deduplicate_jobs(records)[0]
    assert len(group["provenances"]) == 2
    secondary = [view for view in group["provenances"] if not view["is_representative"]]
    assert [view["source_name"] for view in secondary] == ["apec"]
    assert secondary[0]["record"]["official_url"] == "https://www.apec.fr/candidature/2"


def test_the_contradictions_stay_visible_in_the_group():
    records = [
        ats("greenhouse", id="1401", url="https://job-boards.greenhouse.io/citi/jobs/1401",
            company="Citi", title="Sales & Trading Intern", city="London"),
        ats("greenhouse", id="1401", url="https://job-boards.greenhouse.io/citi/jobs/1401",
            company="Citi", title="Sales & Trading Intern", city="Remote"),
    ]
    group = deduplicate_jobs(records)[0]
    assert group["merged"] is True
    assert set(group["conflicts"]["city"].values()) == {"London", "Remote"}


def test_two_different_roles_of_the_same_employer_are_never_merged():
    records = [
        ats("greenhouse", id="701", url="https://job-boards.greenhouse.io/ga/jobs/701",
            company="General Atlantic", title="Investment Banking Intern", city="Luxembourg"),
        ats("greenhouse", id="702", url="https://job-boards.greenhouse.io/ga/jobs/702",
            company="General Atlantic", title="Investment Banking Off-Cycle Analyst", city="Luxembourg"),
    ]
    groups = deduplicate_jobs(records)
    assert len(groups) == 2
    assert all(group["merged"] is False for group in groups)


def test_a_translation_is_never_merged_on_a_few_common_words_only():
    decision = match_records(
        manual(company="Unknown Employer", title="Stage Juridique", city="Paris"),
        ats("greenhouse", id="600", url="https://job-boards.greenhouse.io/unknown/jobs/600",
            company="Unknown Employer", title="Legal Intern", city="Paris"),
    )
    assert decision["matches"] is False
    assert decision["reasons"] == ["translation_common_words_only"]


# ---------------------------------------------------------------------------
# 5. The normalisers
# ---------------------------------------------------------------------------

def test_canonicalize_url():
    assert canonicalize_url("http://www.Example.com/jobs/1?utm_source=x") == "https://example.com/jobs/1"
    assert canonicalize_url("https://example.com/jobs/1/") == "https://example.com/jobs/1"
    assert canonicalize_url("https://example.com/jobs//1") == "https://example.com/jobs/1"
    assert canonicalize_url("https://example.com/jobs/1#apply") == "https://example.com/jobs/1"
    assert canonicalize_url("https://example.com:443/jobs/1") == "https://example.com/jobs/1"
    assert canonicalize_url("https://example.com/jobs/1?b=2&a=1") == "https://example.com/jobs/1?a=1&b=2"
    assert canonicalize_url("not a url") == "not a url"
    assert canonicalize_url("") == ""


def test_company_canonical():
    assert company_canonical("JPMorgan Chase & Co.") == "jpmorgan"
    assert company_canonical({"company": "Point72 Asset Management"}) == "point72"
    assert company_canonical("Rothschild & Co SAS") == "rothschild"
    assert company_canonical("Evercore ISI") == "evercore"
    assert company_canonical("Deutsche Bank AG") == "deutschebank"
    assert canonical_company("Bureau Veritas") == "bureau veritas"


def test_city_and_location_canonical():
    assert canonical_city("Paris La Défense") == "paris"
    assert canonical_city("Télétravail") == "remote"
    assert canonical_city({"city": "Francfort am Main"}) == "frankfurt"
    assert canonical_city("Londres") == "london"
    assert location_canonical("Paris", "France") == "paris,fr"
    assert location_canonical("Remote", "") == "remote"


def test_title_canonical_and_concepts():
    assert title_canonical("Stagiaire M&A") == "internship m a"
    assert title_canonical("Alternance Finance") == "apprenticeship finance"
    assert title_concept("Stage Banque d'Affaires") == "investment_banking"
    assert title_concept("Stage Capital-Investissement") == "private_equity"
    assert title_concept("Stage Gestion d'Actifs") == "asset_management"
    assert title_concept("Stage Recherche d'Investissement") == "asset_management"
    assert title_concept("Stage Developpeur") == "software_engineering"
    assert title_concept("Stage Juridique") == ""
    assert canonical_title_concept("Brand Marketing Intern") == "brand marketing"
    assert canonical_title_concept("Tirocinio Private Equity") == "private_equity"


def test_title_role_level():
    assert title_role_level("Investment Banking Off-Cycle Analyst") == "analyst"
    assert title_role_level({"title": "Stage M&A", "role_level": "intern"}) == "intern"
    assert title_role_level({"title": "Any job", "role_level": "weird level"}) == ""
    assert title_role_level("Senior Developer") == "experienced"
    assert title_role_level("Junior Developer") == "junior"
    assert title_role_level("Corporate Finance Intern") == "intern"
    assert title_contract("CDI") == "permanent"
    assert title_seniority("Data Analyst") == "analyst"


def test_title_similarity():
    assert title_similarity("M&A Intern", "M&A Intern") == 1.0
    assert title_similarity("Stage Banque d'Affaires", "M&A Intern") >= CONCEPT_MATCH_SIMILARITY
    assert title_similarity("M&A Intern", "Private Equity Intern") < TITLE_SIMILARITY_THRESHOLD
    assert title_similarity("Corporate Finance Intern", "Corporate Finance Analyst") < TITLE_SIMILARITY_THRESHOLD


def test_jaro_winkler():
    assert jaro_winkler("", "") == 0.0
    assert jaro_winkler("abc", "abc") == 1.0
    assert jaro_winkler("MARTHA", "MARHTA") == pytest.approx(0.961111, rel=1e-4)
    assert 0.0 <= jaro_winkler("kitten", "sitting") <= 1.0


def test_source_priority():
    assert source_priority("ashby") > source_priority("greenhouse") > source_priority("lever")
    assert source_priority("manual") < source_priority("apec")
    assert source_priority("unknown feed") > source_priority("manual")


# ---------------------------------------------------------------------------
# 6. The public API and its audit trail
# ---------------------------------------------------------------------------

def test_deduplicate_jobs_on_an_empty_collection():
    assert deduplicate_jobs([]) == []
    offers, report = deduplicate_offers([])
    assert offers == []
    assert report.total_count == 0 and report.unique_count == 0 and report.merged_count == 0


def test_deduplicate_offers_traces_the_sources_of_every_merged_offer():
    offers, report = deduplicate_offers([
        ats("greenhouse", id="1", url="https://job-boards.greenhouse.io/acme/jobs/1",
            company="Acme", title="M&A Intern", city="Paris"),
        ats("lever", id="2", url="https://jobs.lever.co/acme/2",
            company="Acme", title="M&A Intern", city="Paris"),
        ats("apec", id="3", url="https://www.apec.fr/candidature/3",
            company="Acme", title="Consulting Intern", city="Paris"),
    ])
    assert isinstance(report, DedupReport)
    assert report.total_count == 3
    assert report.unique_count == len(offers) == 2
    assert report.merged_count == 1
    assert report.merged_clusters == 1
    assert len(report.representatives) == 2
    assert report.clusters[0]["size"] == 2
    assert report.clusters[0]["sources"] == ["greenhouse", "lever"]
    assert report.clusters[0]["reasons"]
    assert MERGED_FROM_FIELD in offers[0]
    assert offers[0]["merged_from"] == ["lever"]


def test_deduplicate_offers_never_modifies_the_received_records():
    records = [
        ats("greenhouse", id="1", url="https://job-boards.greenhouse.io/acme/jobs/1",
            company="Acme", title="M&A Intern", city="Paris"),
        ats("lever", id="2", url="https://jobs.lever.co/acme/2",
            company="Acme", title="M&A Intern", city="Paris"),
    ]
    snapshot = copy.deepcopy(records)
    deduplicate_offers(records)
    assert records == snapshot


def test_deduplicate_offers_survives_incomplete_records():
    offers, report = deduplicate_offers([
        {"title": "Data Analyst"},
        {"source_name": "greenhouse"},
        {},
    ])
    assert len(offers) == 3
    assert report.merged_count == 0


def test_the_embedding_hook_is_optional_and_additive():
    records = [
        ats("greenhouse", id="1", url="https://job-boards.greenhouse.io/acme/jobs/1",
            company="Acme", title="Analyste de donnees", city="Paris"),
        ats("lever", id="2", url="https://jobs.lever.co/acme/2",
            company="Acme", title="Analyste financier", city="Paris"),
    ]
    assert len(deduplicate_jobs(records)) == 2
    hooked = deduplicate_jobs(records, text_similarity=lambda left, right: 1.0)
    assert len(hooked) == 1


def test_the_module_stays_offline():
    source = Path(__file__).resolve().parents[1] / "career" / "job_deduplication.py"
    text = source.read_text(encoding="utf-8")
    for forbidden in ("urllib.request", "socket", "requests", "http.client"):
        assert forbidden not in text


def _timed_deduplication(records):
    """Return the deduplicated offers and the elapsed time, in milliseconds."""
    started = time.perf_counter()
    offers, report = deduplicate_offers(records)
    return offers, report, (time.perf_counter() - started) * 1000


def _best_timed_deduplication(records, attempts=3):
    """Keep the fastest equivalent run, excluding scheduler interruptions.

    CI runners can pause a process between the two perf-counter reads.  The
    operation is deterministic, so repeated runs must return identical data;
    the minimum of three measures the algorithm rather than a host pause.
    """
    runs = [_timed_deduplication(records) for _ in range(attempts)]
    first_offers, first_report, _ = runs[0]
    assert all(offers == first_offers and report == first_report for offers, report, _ in runs[1:])
    return first_offers, first_report, min(elapsed for _, _, elapsed in runs)


def _synthetic_collection(size):
    """Build a synthetic collection of ``size`` offers published twice."""
    cities = ["Paris", "London", "Milan", "Luxembourg", "Frankfurt", "Geneva"]
    titles = ["Data Analyst", "M&A Intern", "Consulting Intern", "Private Equity Intern",
              "Asset Management Intern", "Corporate Finance Intern", "Audit Intern", "Quant Intern"]
    records = []
    for index in range(size):
        company = f"Company {index}"
        city = cities[index % len(cities)]
        title = titles[index % len(titles)]
        for source in ("greenhouse", "lever"):
            records.append(ats(source, id=f"{source}-{index}", company=company, city=city,
                               title=title, url=f"https://example.org/{source}/{index}"))
    return records


def test_five_hundred_offers_are_deduplicated_quickly():
    """The grouper stays fast on a realistic collection.

    The bound is checked twice: an absolute ceiling (a pathological blow-up
    is caught on any machine) and a growth ratio (a quadratic grouper is
    caught whatever the speed of the machine).  The ratio is the meaningful
    one: an absolute threshold only measures the speed of the reviewer.
    """
    records = _synthetic_collection(250)
    assert len(records) == 500
    offers, report, elapsed = _best_timed_deduplication(records)
    assert report.total_count == 500
    assert report.merged_count == 250
    assert len(offers) == 250
    assert elapsed < 1500, f"500 offres dédupliquées en {elapsed:.0f} ms"

    small_records = _synthetic_collection(60)
    _, _, small_elapsed = _best_timed_deduplication(small_records)
    _, _, large_elapsed = _best_timed_deduplication(_synthetic_collection(240))
    assert large_elapsed < small_elapsed * 10 + 100, (
        f"la déduplication ne croît pas linéairement : "
        f"{small_elapsed:.0f} ms pour 120 offres, {large_elapsed:.0f} ms pour 480"
    )


# ---------------------------------------------------------------------------
# 7. The entry point of the discovery flow
# ---------------------------------------------------------------------------

def test_discover_stage_offers_deduplicates_the_multi_source_collection():
    from career.discovery import discover_stage_offers

    offers, report = discover_stage_offers([
        ats("greenhouse", id="1", url="https://job-boards.greenhouse.io/acme/jobs/1",
            company="Acme", title="M&A Intern", city="Paris"),
        ats("lever", id="2", url="https://jobs.lever.co/acme/2",
            company="Acme", title="M&A Intern", city="Paris"),
        ats("apec", id="3", url="https://www.apec.fr/candidature/3",
            company="Acme", title="Consulting Intern", city="Paris"),
    ])
    assert len(offers) == 2
    assert report.merged_count == 1
    assert report.clusters[0]["sources"] == ["greenhouse", "lever"]


def test_choose_best_orders_every_priority():
    person = manual(company="A", title="M&A Intern", city="Paris")
    fresh_board = ats("lever", id="l1", url="https://jobs.lever.co/a/l1", company="A",
                       title="M&A Intern", city="Paris",
                       last_verified_at="2026-10-19T00:00:00+00:00")
    stale_board = ats("lever", id="l0", url="https://jobs.lever.co/a/l0", company="A",
                      title="M&A Intern", city="Paris",
                      last_verified_at="2026-09-01T00:00:00+00:00")
    assert choose_best([person, fresh_board]) is fresh_board
    assert choose_best([stale_board, fresh_board]) is fresh_board


def test_choose_best_refuses_an_empty_group():
    with pytest.raises(ValueError):
        choose_best([])
