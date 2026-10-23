"""Tests for the multi-source job deduplication (Mission CVBOOST-07).

Every fixture is synthetic: no real employer, no real offer, no network.
"""

from __future__ import annotations

import copy
import time
from pathlib import Path

import pytest

from career.cv_quality.job_deduplication import (
    DedupReport,
    canonicalize_url,
    company_canonical,
    deduplicate_jobs,
    jaro_winkler,
    location_canonical,
    source_priority,
    title_canonical,
    title_concept,
    title_similarity,
)


def job(**overrides):
    """Build a synthetic offer record."""
    record = {
        "source_name": "greenhouse",
        "source_id": "",
        "official_url": "",
        "company": "Acme",
        "title": "Data Analyst",
        "city": "Paris",
        "country": "France",
        "posted_date": "",
    }
    record.update(overrides)
    return record


# ---------------------------------------------------------------------------
# Canonical URL
# ---------------------------------------------------------------------------

def test_canonicalize_url_forces_https_and_removes_www():
    assert canonicalize_url("http://www.example.com/jobs/1") == "https://example.com/jobs/1"


def test_canonicalize_url_removes_trailing_slash():
    assert canonicalize_url("https://example.com/jobs/1/") == "https://example.com/jobs/1"


def test_canonicalize_url_removes_tracking_parameters():
    canonical = canonicalize_url("https://example.com/jobs/1?utm_source=linkedin&utm_campaign=x&ref=abc&source=news")
    assert canonical == "https://example.com/jobs/1"


def test_canonicalize_url_keeps_and_sorts_meaningful_parameters():
    canonical = canonicalize_url("https://example.com/jobs/1?b=2&a=1")
    assert canonical == "https://example.com/jobs/1?a=1&b=2"


def test_canonicalize_url_removes_fragment():
    assert canonicalize_url("https://example.com/jobs/1#section") == "https://example.com/jobs/1"


def test_canonicalize_url_removes_default_port_only():
    assert canonicalize_url("https://example.com:443/jobs/1") == "https://example.com/jobs/1"
    assert canonicalize_url("https://example.com:8443/jobs/1") == "https://example.com:8443/jobs/1"


def test_canonicalize_url_collapses_duplicate_slashes():
    assert canonicalize_url("https://example.com//jobs//1") == "https://example.com/jobs/1"


def test_canonicalize_url_keeps_non_http_untouched():
    assert canonicalize_url("not-a-url") == "not-a-url"


def test_canonicalize_url_of_empty_value():
    assert canonicalize_url("") == ""


# ---------------------------------------------------------------------------
# Canonical company
# ---------------------------------------------------------------------------

def test_company_canonical_lowercases_and_removes_accents():
    assert company_canonical("Société Générale") == "societegenerale"
    assert company_canonical("Banque  Générale") == "banque generale"


def test_company_canonical_removes_legal_suffixes():
    assert company_canonical("Acme SAS") == "acme"
    assert company_canonical("Acme SA") == "acme"
    assert company_canonical("Acme Ltd") == "acme"
    assert company_canonical("Acme Inc") == "acme"
    assert company_canonical("Acme GmbH") == "acme"
    assert company_canonical("Acme AG") == "acme"
    assert company_canonical("Acme SRL") == "acme"
    assert company_canonical("Acme SpA") == "acme"
    assert company_canonical("Acme BV") == "acme"
    assert company_canonical("Acme NV") == "acme"
    assert company_canonical("Acme PLC") == "acme"


def test_company_canonical_removes_group_suffixes():
    assert company_canonical("Accor Group") == "accor"
    assert company_canonical("Groupe Accor") == "accor"
    assert company_canonical("Goldman Sachs Group") == company_canonical("Goldman Sachs")


def test_company_canonical_applies_known_aliases():
    assert company_canonical("J.P. Morgan") == company_canonical("JPMorgan Chase & Co")


def test_company_canonical_reduces_spaces_and_punctuation():
    assert company_canonical("  Acme   Corp.  ") == "acme"


def test_company_canonical_of_empty_value():
    assert company_canonical("") == ""


# ---------------------------------------------------------------------------
# Canonical title, concepts and similarity
# ---------------------------------------------------------------------------

def test_title_canonical_maps_stage_to_internship():
    assert title_canonical("Stage") == "internship"
    assert title_canonical("Intern") == "internship"


def test_title_canonical_maps_cdi_to_permanent():
    assert title_canonical("CDI") == "permanent"


def test_title_canonical_maps_alternance_to_apprenticeship():
    assert title_canonical("Alternance") == "apprenticeship"
    assert title_canonical("Apprentissage") == "apprenticeship"


def test_title_canonical_removes_accents_punctuation_and_gender_marker():
    assert title_canonical("Développeur H/F (CDI)") == "developpeur permanent"


def test_title_concept_maps_translated_titles():
    assert title_concept("Data Analyst") == "data_analyst"
    assert title_concept("Analyste de données") == "data_analyst"
    assert title_concept("M&A Intern") == "investment_banking"
    assert title_concept("Fusion-Acquisition") == "investment_banking"


def test_title_similarity_matches_translated_titles():
    assert title_similarity("Data Analyst", "Analyste de données") >= 0.92


def test_title_similarity_matches_aliases():
    assert title_similarity("M&A Intern", "Stage Fusion-Acquisition") >= 0.92


def test_title_similarity_separates_different_roles():
    assert title_similarity("Data Analyst", "Data Engineer") < 0.92


def test_title_similarity_separates_contract_levels():
    assert title_similarity("M&A Intern", "M&A Analyst") < 0.92


def test_title_similarity_of_identical_titles():
    assert title_similarity("Data Analyst", "data analyst") == pytest.approx(1.0)


def test_title_similarity_of_empty_title():
    assert title_similarity("", "Data Analyst") == 0.0


# ---------------------------------------------------------------------------
# Canonical location
# ---------------------------------------------------------------------------

def test_location_canonical_uses_iso_country_and_normalised_city():
    assert location_canonical("Paris", "France") == "paris,fr"
    assert location_canonical("Genève", "Switzerland") == "geneva,ch"


def test_location_canonical_unifies_remote_offers():
    assert location_canonical("Remote — Europe", "") == "remote"
    assert location_canonical("Télétravail", "France") == "remote"


def test_location_canonical_unifies_city_aliases():
    assert location_canonical("Paris La Défense", "France") == location_canonical("Paris", "France")
    assert location_canonical("Londres", "UK") == "london,gb"


# ---------------------------------------------------------------------------
# Jaro-Winkler
# ---------------------------------------------------------------------------

def test_jaro_winkler_reference_values():
    assert jaro_winkler("MARTHA", "MARHTA") == pytest.approx(0.9611, abs=1e-4)
    assert jaro_winkler("DIXON", "DICKSONX") == pytest.approx(0.8133, abs=1e-4)
    assert jaro_winkler("JELLYFISH", "SMELLYFISH") == pytest.approx(0.8963, abs=1e-4)


def test_jaro_winkler_edge_cases():
    assert jaro_winkler("same", "same") == 1.0
    assert jaro_winkler("", "same") == 0.0
    assert jaro_winkler("abc", "xyz") == 0.0


# ---------------------------------------------------------------------------
# Source priority
# ---------------------------------------------------------------------------

def test_source_priority_follows_the_mission_order():
    assert source_priority("ashby") > source_priority("greenhouse")
    assert source_priority("greenhouse") > source_priority("lever")
    assert source_priority("lever") > source_priority("welcome_jungle")
    assert source_priority("welcome_jungle") > source_priority("jobteaser")
    assert source_priority("jobteaser") > source_priority("talent.com")
    assert source_priority("talent.com") > source_priority("apec")


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def test_deduplicate_jobs_on_empty_input():
    offers, report = deduplicate_jobs([])
    assert offers == []
    assert report.merged_count == 0
    assert report.clusters == []
    assert report.representatives == []


def test_deduplicate_jobs_keeps_a_single_offer():
    offers, report = deduplicate_jobs([job(source_id="1")])
    assert len(offers) == 1
    assert offers[0]["merged_from"] == []
    assert report.merged_count == 0
    assert report.merged_clusters == 0


def test_deduplicate_jobs_merges_the_same_url_with_tracking_parameters():
    offers, report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="1", official_url="https://boards.greenhouse.io/acme/jobs/1?utm_source=linkedin"),
        job(source_name="greenhouse", source_id="2", official_url="https://boards.greenhouse.io/acme/jobs/1"),
    ])
    assert len(offers) == 1
    assert report.merged_count == 1
    assert offers[0]["merged_from"] == ["greenhouse"]


def test_deduplicate_jobs_merges_the_same_external_id_across_sources():
    offers, report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="1", external_id="gh_jid_123", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="ashby", source_id="9", external_id="gh_jid_123", official_url="https://jobs.ashbyhq.com/acme/9"),
    ])
    assert len(offers) == 1
    assert report.merged_count == 1
    assert offers[0]["source_name"] == "ashby"
    assert offers[0]["merged_from"] == ["greenhouse"]


def test_deduplicate_jobs_merges_two_records_of_the_same_source():
    offers, report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="1", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="greenhouse", source_id="1", official_url="https://boards.greenhouse.io/acme/jobs/1?utm_campaign=x"),
    ])
    assert len(offers) == 1
    assert report.merged_count == 1


def test_deduplicate_jobs_merges_the_same_offer_on_three_sources():
    offers, report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="1", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="lever", source_id="2", official_url="https://jobs.lever.co/acme/2"),
        job(source_name="apec", source_id="3", official_url="https://www.apec.fr/candidature/3"),
    ])
    assert len(offers) == 1
    assert report.merged_count == 2
    assert sorted(offers[0]["merged_from"]) == ["apec", "lever"]


def test_deduplicate_jobs_merges_translated_titles():
    offers, report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="1", title="Data Analyst", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="lever", source_id="2", title="Analyste de données", official_url="https://jobs.lever.co/acme/2"),
    ])
    assert len(offers) == 1
    assert report.merged_count == 1


def test_deduplicate_jobs_merges_title_synonyms():
    offers, _report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="1", title="Stage en finance", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="lever", source_id="2", title="Finance Internship", official_url="https://jobs.lever.co/acme/2"),
    ])
    assert len(offers) == 1


def test_deduplicate_jobs_merges_companies_with_different_suffixes():
    offers, _report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="1", company="Acme SAS", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="lever", source_id="2", company="ACME Ltd", official_url="https://jobs.lever.co/acme/2"),
    ])
    assert len(offers) == 1


def test_deduplicate_jobs_keeps_two_different_roles_apart():
    offers, report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="1", title="M&A Intern", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="lever", source_id="2", title="M&A Analyst", official_url="https://jobs.lever.co/acme/2"),
    ])
    assert len(offers) == 2
    assert report.merged_count == 0


def test_deduplicate_jobs_keeps_two_locations_apart():
    offers, _report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="1", city="Paris", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="lever", source_id="2", city="London", official_url="https://jobs.lever.co/acme/2"),
    ])
    assert len(offers) == 2


def test_deduplicate_jobs_keeps_two_companies_apart():
    offers, _report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="1", company="Acme", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="lever", source_id="2", company="Globex", official_url="https://jobs.lever.co/globex/2"),
    ])
    assert len(offers) == 2


def test_deduplicate_jobs_keeps_different_cohorts_apart():
    offers, _report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="1", title="Stage Finance H1 2027", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="lever", source_id="2", title="Stage Finance H2 2027", official_url="https://jobs.lever.co/acme/2"),
    ])
    assert len(offers) == 2


def test_deduplicate_jobs_keeps_remote_and_onsite_apart():
    offers, _report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="1", city="Remote", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="lever", source_id="2", city="Paris", official_url="https://jobs.lever.co/acme/2"),
    ])
    assert len(offers) == 2


def test_deduplicate_jobs_does_not_merge_a_recycled_identifier():
    offers, _report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="6001", title="M&A Intern 2027", city="London", official_url="https://boards.greenhouse.io/acme/jobs/6001"),
        job(source_name="greenhouse", source_id="6001", title="Private Equity Intern 2028", city="London", official_url="https://boards.greenhouse.io/acme/jobs/6001-reused"),
    ])
    assert len(offers) == 2


def test_deduplicate_jobs_keeps_the_most_recent_offer_of_a_cluster():
    offers, _report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="1", posted_date="2026-09-01", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="greenhouse", source_id="2", posted_date="2026-10-12", official_url="https://boards.greenhouse.io/acme/jobs/1"),
    ])
    assert len(offers) == 1
    assert offers[0]["posted_date"] == "2026-10-12"


def test_deduplicate_jobs_prefers_the_highest_priority_source():
    offers, _report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="1", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="ashby", source_id="2", official_url="https://jobs.ashbyhq.com/acme/2"),
    ])
    assert len(offers) == 1
    assert offers[0]["source_name"] == "ashby"
    assert offers[0]["merged_from"] == ["greenhouse"]


def test_deduplicate_jobs_traces_merged_from_on_every_merged_offer():
    offers, _report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="1", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="lever", source_id="2", official_url="https://jobs.lever.co/acme/2"),
    ])
    assert all("merged_from" in offer for offer in offers)
    assert offers[0]["merged_from"] == ["lever"]


def test_deduplicate_jobs_reports_clusters_and_representatives():
    offers, report = deduplicate_jobs([
        job(source_name="greenhouse", source_id="1", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="lever", source_id="2", official_url="https://jobs.lever.co/acme/2"),
        job(source_name="apec", source_id="3", title="Consulting Intern", city="Paris", official_url="https://www.apec.fr/candidature/3"),
    ])
    assert isinstance(report, DedupReport)
    assert report.total_count == 3
    assert report.unique_count == len(offers) == 2
    assert report.merged_count == 1
    assert len(report.clusters) == 1
    assert report.clusters[0]["size"] == 2
    assert report.clusters[0]["sources"] == ["greenhouse", "lever"]
    assert report.clusters[0]["reasons"]
    assert len(report.representatives) == 2


def test_deduplicate_jobs_is_deterministic():
    offers = [
        job(source_name="greenhouse", source_id="1", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="lever", source_id="2", official_url="https://jobs.lever.co/acme/2"),
        job(source_name="apec", source_id="3", title="Consulting Intern", official_url="https://www.apec.fr/candidature/3"),
    ]
    first, first_report = deduplicate_jobs(offers)
    second, second_report = deduplicate_jobs(offers)
    assert first == second
    assert first_report == second_report


def test_deduplicate_jobs_does_not_modify_the_input():
    offers = [
        job(source_name="greenhouse", source_id="1", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="lever", source_id="2", official_url="https://jobs.lever.co/acme/2"),
    ]
    snapshot = copy.deepcopy(offers)
    deduplicate_jobs(offers)
    assert offers == snapshot


def test_deduplicate_jobs_survives_incomplete_records():
    offers, report = deduplicate_jobs([
        {"title": "Data Analyst"},
        {"source_name": "greenhouse"},
        {},
    ])
    assert len(offers) == 3
    assert report.merged_count == 0


def test_deduplicate_jobs_ignores_the_order_of_the_sources():
    base = [
        job(source_name="greenhouse", source_id="1", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="lever", source_id="2", official_url="https://jobs.lever.co/acme/2"),
    ]
    forward, _ = deduplicate_jobs(base)
    backward, _ = deduplicate_jobs(list(reversed(base)))
    assert len(forward) == len(backward) == 1
    assert forward[0]["merged_from"] == backward[0]["merged_from"]


def test_deduplicate_jobs_handles_five_hundred_offers_quickly():
    cities = ["Paris", "London", "Milan", "Luxembourg", "Frankfurt", "Geneva"]
    titles = ["Data Analyst", "M&A Intern", "Consulting Intern", "Private Equity Intern",
              "Asset Management Intern", "Corporate Finance Intern", "Audit Intern", "Quant Intern"]
    offers = []
    for index in range(250):
        company = f"Company {index}"
        city = cities[index % len(cities)]
        title = titles[index % len(titles)]
        for source in ("greenhouse", "lever"):
            offers.append(job(
                source_name=source,
                source_id=f"{source}-{index}",
                company=company,
                city=city,
                title=title,
                official_url=f"https://example.org/{source}/{index}",
            ))
    assert len(offers) == 500
    started = time.perf_counter()
    unique, report = deduplicate_jobs(offers)
    elapsed = (time.perf_counter() - started) * 1000
    assert report.total_count == 500
    assert report.merged_count == 250
    assert len(unique) == 250
    assert elapsed < 200, f"500 offres dédupliquées en {elapsed:.0f} ms"


# ---------------------------------------------------------------------------
# Integration in the discovery flow
# ---------------------------------------------------------------------------

def test_discover_stage_offers_deduplicates_the_multi_source_collection():
    from career.discovery import discover_stage_offers

    offers, report = discover_stage_offers([
        job(source_name="greenhouse", source_id="1", official_url="https://boards.greenhouse.io/acme/jobs/1"),
        job(source_name="lever", source_id="2", official_url="https://jobs.lever.co/acme/2"),
        job(source_name="apec", source_id="3", title="Consulting Intern", official_url="https://www.apec.fr/candidature/3"),
    ])
    assert len(offers) == 2
    assert report.merged_count == 1


def test_deduplicate_jobs_is_exact_on_a_synthetic_corpus():
    """Precision and recall measured against the known truth of a corpus."""
    from career.cv_quality import job_deduplication as module

    corpus = [
        # The same offer on four boards (one French title).
        (job(source_name="greenhouse", source_id="1", title="Data Analyst", official_url="https://boards.greenhouse.io/acme/jobs/1"), "A"),
        (job(source_name="lever", source_id="2", title="Data Analyst", official_url="https://jobs.lever.co/acme/2"), "A"),
        (job(source_name="jobteaser", source_id="3", title="Analyste de données", official_url="https://www.jobteaser.com/fr/3"), "A"),
        (job(source_name="apec", source_id="4", title="Analyste de donnees", official_url="https://www.apec.fr/candidature/4"), "A"),
        # The same offer on three boards (two synonyms).
        (job(source_name="ashby", source_id="5", title="M&A Intern", city="London", country="UK", official_url="https://jobs.ashbyhq.com/globex/5"), "B"),
        (job(source_name="talent.com", source_id="6", title="Stage M&A", city="Londres", country="UK", official_url="https://www.talent.com/jobs/6"), "B"),
        (job(source_name="greenhouse", source_id="7", title="M and A Intern", city="London", country="United Kingdom", official_url="https://boards.greenhouse.io/globex/jobs/7"), "B"),
        # The same offer, same URL, one tracking parameter apart.
        (job(source_name="greenhouse", source_id="8", title="Audit Intern", official_url="https://boards.greenhouse.io/initech/jobs/8"), "C"),
        (job(source_name="greenhouse", source_id="9", title="Audit Intern", official_url="https://boards.greenhouse.io/initech/jobs/8?utm_source=linkedin"), "C"),
        # Distinct offers.
        (job(source_name="greenhouse", source_id="10", title="Data Engineer", official_url="https://boards.greenhouse.io/acme/jobs/10"), "D"),
        (job(source_name="greenhouse", source_id="11", title="Data Analyst", city="London", country="UK", official_url="https://boards.greenhouse.io/acme/jobs/11"), "E"),
        (job(source_name="greenhouse", source_id="12", title="M&A Analyst", official_url="https://boards.greenhouse.io/acme/jobs/12"), "F"),
        (job(source_name="greenhouse", source_id="13", company="Globex", title="Private Equity Intern", official_url="https://boards.greenhouse.io/globex/jobs/13"), "G"),
        (job(source_name="greenhouse", source_id="14", company="Initech", title="Consulting Intern", official_url="https://boards.greenhouse.io/initech/jobs/14"), "H"),
        (job(source_name="greenhouse", source_id="15", company="Initech", title="Corporate Finance Intern", city="London", country="UK", official_url="https://boards.greenhouse.io/initech/jobs/15"), "I"),
        (job(source_name="greenhouse", source_id="16", company="Umbrella", title="Quant Intern", city="London", country="UK", official_url="https://boards.greenhouse.io/umbrella/jobs/16"), "J"),
        (job(source_name="greenhouse", source_id="17", company="Stark", title="Data Analyst", official_url="https://boards.greenhouse.io/stark/jobs/17"), "K"),
    ]
    labels = [label for _offer, label in corpus]
    offers = [offer for offer, _label in corpus]

    unique, report = deduplicate_jobs(offers)
    # 17 offers, three clusters of 4, 3 and 2 offers, eight singletons.
    assert len(unique) == 11

    identities = [module._build_record(index, offer).identity for index, offer in enumerate(offers)]
    predicted: dict[str, set[str]] = {identity: {identity} for identity in identities}
    for cluster in report.clusters:
        members = set(cluster["member_ids"])
        for identity in members:
            predicted[identity] = members

    truth: dict[str, set[str]] = {identity: {identity} for identity in identities}
    for identity, label in zip(identities, labels):
        truth[identity] = {other for other, other_label in zip(identities, labels) if other_label == label}

    true_pairs = set()
    predicted_pairs = set()
    for members in truth.values():
        for left in members:
            for right in members:
                if left < right:
                    true_pairs.add((left, right))
    for members in predicted.values():
        for left in members:
            for right in members:
                if left < right:
                    predicted_pairs.add((left, right))

    true_positive = len(true_pairs & predicted_pairs)
    precision = true_positive / len(predicted_pairs)
    recall = true_positive / len(true_pairs)
    assert precision == 1.0, sorted(predicted_pairs - true_pairs)
    assert recall == 1.0, sorted(true_pairs - predicted_pairs)


def test_deduplication_module_stays_offline():
    source = Path(__file__).resolve().parents[1] / "career" / "cv_quality" / "job_deduplication.py"
    text = source.read_text(encoding="utf-8")
    assert "urllib.request" not in text
    assert "socket" not in text
    assert "requests" not in text
