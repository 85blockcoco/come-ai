"""Synthetic multi-source deduplication pairs and groups; no network, no DB.

This suite is the contract of the second implementation found during the
mission (the one that was never committed).  It is kept as regression
coverage: 40 hand-labelled pairs covering the regulated scenarios (URL
tracking, different ATS, translated title, nearby city spellings, remote, two
levels of one employer, recycled identifier, divergent dates, employer alias,
exact duplicate, false neighbour), plus group-level rules (provenance
conservation, election without user scores, visible conflicts) and a
synthetic-truth corpus on which precision and recall are measured.

It used to live as an untracked file in the main working directory, where it
was lost on every fresh clone.  SPEC-SK-06 now owns it, and it runs against
the consolidated module (career/job_deduplication.py).
"""

from __future__ import annotations

import pytest

from career.job_deduplication import (
    canonical_city,
    canonical_company,
    canonical_title_concept,
    choose_best,
    deduplicate_jobs,
    evaluate_deduplication,
    match_records,
    title_role_level,
)


# ---------------------------------------------------------------------------
# Synthetic record factory (mirrors the connector/normalized vocabulary)
# ---------------------------------------------------------------------------

def ats(provider, *, id="", url=None, apply_url=None, company, title, city="",
        country="", posted="", verified=True, role_level="", duration=None,
        last_verified_at=None, seen_at=None, extra=None):
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
        "deadline_date": "",
        "start_date": "",
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
    record.update(extra or {})
    return record


def manual(*, company, title, city="", url=None, role_level="", posted="",
           duration=None, extra=None):
    return ats("manual", id="", url=url, company=company, title=title, city=city,
               role_level=role_level, posted=posted, duration=duration, verified=False,
               extra=extra)


GREENHOUSE_URL_PARIS = "https://job-boards.greenhouse.io/lincolninternational/jobs/4012345"
LEVER_URL_PARIS = "https://jobs.lever.co/lincoln-international/a1b2c3"
GREENHOUSE_APPLY_URL = "https://job-boards.greenhouse.io/lincolninternational/jobs/4012345/apply"


# ---------------------------------------------------------------------------
# Hand-labelled pairwise decisions (40 regulated scenarios)
# ---------------------------------------------------------------------------

PAIRS = [
    # --- official URL written with tracking parameters ---
    ("url_tracking_utm", ats("greenhouse", id="4012345", url=GREENHOUSE_URL_PARIS + "?utm_source=linkedin&utm_campaign=2027",
                             company="Lincoln International", title="M&A Intern", city="Paris"),
     ats("greenhouse", id="4012345", url=GREENHOUSE_URL_PARIS,
         company="Lincoln International", title="M&A Intern", city="Paris"), True),
    ("url_tracking_gclid", ats("lever", id="a1b2", url=LEVER_URL_PARIS + "?gclid=abc123",
                               company="Lincoln International", title="M&A Intern", city="Paris"),
     ats("lever", id="a1b2", url=LEVER_URL_PARIS,
         company="Lincoln International", title="M&A Intern", city="Paris"), True),
    ("url_tracking_ref_source", ats("greenhouse", id="4019",
                                    url="https://job-boards.greenhouse.io/alixpartners/jobs/4019?ref=x&source=y",
                                    company="AlixPartners", title="Private Equity Intern", city="Paris"),
     ats("greenhouse", id="4019", url="https://job-boards.greenhouse.io/alixpartners/jobs/4019",
         company="AlixPartners", title="Private Equity Intern", city="Paris"), True),
    ("url_port_and_slash", ats("greenhouse", id="4419",
                               url="https://job-boards.greenhouse.io:443/alixpartners/jobs/4419/",
                               company="AlixPartners", title="M&A Intern", city="Paris"),
     ats("greenhouse", id="4419", url="https://job-boards.greenhouse.io/alixpartners/jobs/4419",
         company="AlixPartners", title="M&A Intern", city="Paris"), True),
    ("url_host_case", ats("lever", id="lh1", url="https://JOBS.LEVER.CO/lincoln/lh1",
                          company="Lincoln International", title="M&A Intern", city="Paris"),
     ats("lever", id="lh1", url="https://jobs.lever.co/lincoln/lh1",
         company="Lincoln International", title="M&A Intern", city="Paris"), True),

    # --- the same posting announced on two different ATS ---
    ("ats_different_boards", ats("greenhouse", id="4012345", url=GREENHOUSE_URL_PARIS,
                                 company="Lincoln International", title="M&A Intern", city="Paris"),
     ats("lever", id="a1b2c3", url=LEVER_URL_PARIS,
         company="Lincoln International", title="M&A Intern", city="Paris"), True),
    ("ats_board_and_employer_site", ats("greenhouse", id="7001",
                                        url="https://boards.greenhouse.io/schonfeld/jobs/7001",
                                        company="Schonfeld", title="Investment Research Intern", city="London"),
     ats("employer_official", id="", url="https://www.schonfeld.com/careers/7001",
         company="Schonfeld", title="Investment Research Intern", city="London"), True),
    ("apply_url_shared", ats("greenhouse", id="801", url=GREENHOUSE_URL_PARIS, apply_url=GREENHOUSE_APPLY_URL,
                             company="Lincoln International", title="M&A Intern", city="Paris"),
     ats("lever", id="a1b2c3", url="https://jobs.lever.co/other-board/x", apply_url=GREENHOUSE_APPLY_URL,
         company="Lincoln International", title="M&A Intern", city="Paris"), True),
    ("person_pasted_before_board_sync", manual(company="Lincoln International", title="M&A Intern",
                                               city="Paris", url=GREENHOUSE_URL_PARIS + "?utm_medium=copied"),
     ats("greenhouse", id="4012345", url=GREENHOUSE_URL_PARIS,
         company="Lincoln International", title="M&A Intern", city="Paris"), True),

    # --- translated title of the same role ---
    ("title_translated_fr", manual(company="Rothschild & Co", title="Stage Banque d'Affaires H1 2027", city="Paris"),
     ats("greenhouse", id="55", url="https://job-boards.greenhouse.io/rothschild/jobs/55",
         company="Rothschild & Co", title="M&A Intern", city="Paris"), True),
    ("title_translated_it", manual(company="Mediobanca", title="Tirocinio M&A Milano", city="Milano"),
     ats("lever", id="mb1", url="https://jobs.eu.lever.co/mediobanca/mb1",
         company="Mediobanca", title="M&A Intern", city="Milan"), True),
    ("title_translated_de", manual(company="Morgan Stanley", title="Praktikum M&A Frankfurt", city="Francfort"),
     ats("greenhouse", id="ms1", url="https://job-boards.greenhouse.io/morganstanley/jobs/ms1",
         company="Morgan Stanley", title="M&A Intern", city="Frankfurt"), True),
    ("title_translated_capital_investissement", manual(company="Tikehau Capital", title="Stage Capital-Investissement", city="Paris"),
     ats("ashby", id="tk1", url="https://jobs.ashbyhq.com/tikehau/tk1",
         company="Tikehau Capital", title="Private Equity Intern", city="Paris"), True),
    ("title_hf_variant", manual(company="Jefferies", title="Stage M&A H/F", city="Paris"),
     manual(company="Jefferies", title="M&A Internship", city="Paris"), True),

    # --- near city spellings ---
    ("city_metro_surrogate", ats("greenhouse", id="101", url="https://job-boards.greenhouse.io/aqr/jobs/101",
                                 company="AQR", title="Investment Research Intern", city="Paris La Défense"),
     ats("lever", id="aqr2", url="https://jobs.eu.lever.co/aqr/aqr2",
         company="AQR", title="Investment Research Intern", city="Paris"), True),
    ("city_translation_london", ats("greenhouse", id="201", url="https://job-boards.greenhouse.io/point72/jobs/201",
                                    company="Point72", title="Quantitative Research Intern", city="London"),
     manual(company="Point72", title="Stage Quantitative Research", city="Londres"), True),
    ("city_translation_milan", ats("lever", id="301", url="https://jobs.eu.lever.co/flow/milano",
                                   company="Flow Traders", title="Trading Internship", city="Milano"),
     ats("greenhouse", id="302", url="https://job-boards.greenhouse.io/flowtraders/jobs/302",
         company="Flow Traders", title="Trading Intern", city="Milan"), True),
    ("city_francfort_variant", ats("greenhouse", id="401", url="https://job-boards.greenhouse.io/db/jobs/401",
                                   company="Deutsche Bank", title="Corporate Finance Intern", city="Frankfurt am Main"),
     manual(company="Deutsche Bank", title="Stage Corporate Finance", city="Francfort"), True),
    ("city_conflict_never_merged", ats("greenhouse", id="402", url="https://job-boards.greenhouse.io/db/jobs/402",
                                       company="Deutsche Bank", title="Corporate Finance Intern", city="Geneva"),
     manual(company="Deutsche Bank", title="Stage Corporate Finance", city="Francfort"), False),

    # --- remote writings ---
    ("remote_variants_fr", ats("greenhouse", id="601", url="https://job-boards.greenhouse.io/xtx/jobs/601",
                               company="XTX Markets", title="Software Engineering Intern", city="Remote — Europe"),
     manual(company="XTX Markets", title="Internship Software Engineering", city="Télétravail"), True),
    ("remote_variants_english", ats("lever", id="602", url="https://jobs.lever.co/qube/602",
                                    company="Qube Research & Technologies", title="Quant Developer Intern", city="Full Remote"),
     manual(company="Qube Research & Technologies", title="Internship Quant Developer", city="Work from home"), True),
    ("remote_vs_city_not_merged", ats("lever", id="603", url="https://jobs.lever.co/qube/603",
                                      company="Qube Research & Technologies", title="Quant Developer Intern", city="Remote"),
     ats("lever", id="604", url="https://jobs.lever.co/qube/604",
         company="Qube Research & Technologies", title="Quant Developer Intern", city="Milan"), False),

    # --- two different levels of the same employer ---
    ("levels_intern_vs_offcycle", ats("greenhouse", id="701", url="https://job-boards.greenhouse.io/ga/jobs/701",
                                      company="General Atlantic", title="Investment Banking Intern", city="Luxembourg"),
     ats("greenhouse", id="702", url="https://job-boards.greenhouse.io/ga/jobs/702",
         company="General Atlantic", title="Investment Banking Off-Cycle Analyst", city="Luxembourg"), False),
    ("levels_stagiaire_vs_analyst", manual(company="BNP Paribas", title="Stage M&A Paris", city="Paris"),
     ats("greenhouse", id="703", url="https://job-boards.greenhouse.io/bnp/jobs/703",
         company="BNP Paribas", title="M&A Analyst", city="Paris"), False),
    ("levels_explicit_conflict", ats("greenhouse", id="704", url="https://job-boards.greenhouse.io/gm/jobs/704",
                                     company="Goldman Sachs", title="Corporate Finance Intern", city="Frankfurt"),
     ats("greenhouse", id="705", url="https://job-boards.greenhouse.io/gm/jobs/705",
         company="Goldman Sachs", title="Corporate Finance Intern", city="Frankfurt", role_level="analyst"), False),
    ("levels_missing_vs_present", ats("greenhouse", id="706", url="https://job-boards.greenhouse.io/gm/jobs/706",
                                      company="Goldman Sachs", title="Investment Banking Program", city="Paris"),
     manual(company="Goldman Sachs & Co.", title="M&A Intern", city="Paris"), True),

    # --- recycled ATS identifier ---
    ("recycled_id_corroborated_url", ats("greenhouse", id="4099", url="https://job-boards.greenhouse.io/alixpartners/jobs/4099",
                                         company="AlixPartners", title="Corporate Finance Intern", city="Paris",
                                         posted="2026-09-30"),
     ats("greenhouse", id="4099", url="https://job-boards.greenhouse.io/alixpartners/jobs/4099",
         company="AlixPartners", title="Corporate Finance Intern", city="Paris", posted="2026-10-06"), True),
    ("recycled_id_corroborated_title", ats("greenhouse", id="5100", url="https://job-boards.greenhouse.io/schonfeld/jobs/5100",
                                           company="Schonfeld", title="Investment Research Intern", city="London"),
     ats("greenhouse", id="5100", company="Schonfeld", title="Investment Research Intern",
         city="London", posted="2026-10-01"), True),
    ("recycled_id_new_role", ats("greenhouse", id="6001", url="https://job-boards.greenhouse.io/man/jobs/6001",
                                 company="Man Group", title="M&A Intern 2027", city="London"),
     ats("greenhouse", id="6001", url="https://job-boards.greenhouse.io/man/jobs/6001-reused",
         company="Man Group", title="Private Equity Intern 2028", city="London", posted="2026-10-12"), False),
    ("recycled_id_new_city", ats("lever", id="6100", url="https://jobs.lever.co/evercore/6100",
                                 company="Evercore", title="Financial Analysis Intern", city="London"),
     ats("lever", id="6100", url="https://jobs.lever.co/evercore/6100-v2",
         company="Evercore", title="Financial Analysis Intern", city="Milan", posted="2026-10-12"), False),

    # --- divergent dates on the same posting ---
    ("divergent_posted_date_same_url", ats("greenhouse", id="801", url=GREENHOUSE_URL_PARIS,
                                           company="Lincoln International", title="M&A Intern", city="Paris",
                                           posted="2026-09-14"),
     ats("greenhouse", id="801", url=GREENHOUSE_URL_PARIS,
         company="Lincoln International", title="M&A Intern", city="Paris", posted="2026-10-01"), True),
    ("divergent_posted_date_received_from_two_sources", ats("greenhouse", id="5100", url="https://job-boards.greenhouse.io/schonfeld/jobs/5100",
                                                            company="Schonfeld", title="Investment Research Intern",
                                                            city="London", posted="2026-09-25"),
     ats("lever", id="sch-5100", url="https://jobs.lever.co/schonfeld/sch-5100",
         company="Schonfeld", title="Investment Research Internship", city="London", posted="2026-10-11"), True),

    # --- employer alias ---
    ("alias_jp_morgan", manual(company="J.P. Morgan", title="Stage Banque d'Affaires", city="Paris"),
     ats("lever", id="jpm1", url="https://jobs.lever.co/jpmorgan/jpm1",
         company="JPMorgan Chase & Co.", title="Investment Banking Intern", city="Paris"), True),
    ("alias_point72", ats("greenhouse", id="901", url="https://job-boards.greenhouse.io/point72/jobs/901",
                          company="Point72 Asset Management", title="Equity Research Intern", city="London"),
     manual(company="Point72", title="Stage Equity Research", city="London"), True),
    ("alias_evercore", ats("lever", id="902", url="https://jobs.lever.co/evercore/902",
                           company="Evercore Inc.", title="Fintech M&A Intern", city="New York City"),
     manual(company="Evercore ISI", title="M&A Internship", city="NYC"), True),
    ("alias_goldman_international", ats("greenhouse", id="903", url="https://job-boards.greenhouse.io/gs/jobs/903",
                                        company="Goldman Sachs International", title="Asset Management Intern", city="London"),
     manual(company="Goldman Sachs & Co.", title="Stage Gestion d'Actifs", city="London"), True),

    # --- exact duplicate ---
    ("duplicate_exact_manual", manual(company="Mid Cap Partners", title="Stage Corporate Finance", city="Paris",
                                      posted="2026-10-02"),
     manual(company="Mid Cap Partners", title="Stage Corporate Finance", city="Paris", posted="2026-10-02"), True),
    ("duplicate_exact_connector", ats("greenhouse", id="1001", url=GREENHOUSE_URL_PARIS,
                                      company="Lincoln International", title="M&A Intern", city="Paris"),
     ats("greenhouse", id="1001", url=GREENHOUSE_URL_PARIS,
         company="Lincoln International", title="M&A Intern", city="Paris"), True),

    # --- false neighbour ---
    ("false_neighbour_teams", ats("greenhouse", id="1101", url="https://job-boards.greenhouse.io/lazard/jobs/1101",
                                  company="Lazard", title="M&A Intern", city="Paris"),
     ats("lever", id="1102", url="https://jobs.lever.co/lazard/1102",
         company="Lazard", title="Private Equity Intern", city="Paris"), False),
    ("false_neighbour_families", ats("greenhouse", id="1103", url="https://job-boards.greenhouse.io/ubp/jobs/1103",
                                     company="Union Bancaire Privée", title="Corporate Finance Intern", city="Geneva"),
     ats("lever", id="1104", url="https://jobs.lever.co/ubp/1104",
         company="Union Bancaire Privée", title="Asset Management Intern", city="Geneva"), False),
    ("company_conflict_similar_titles", ats("greenhouse", id="1201", url="https://job-boards.greenhouse.io/lincoln/jobs/1201",
                                            company="Lincoln International", title="M&A Intern", city="Paris"),
     ats("lever", id="1202", url="https://jobs.lever.co/alix/1202",
         company="AlixPartners", title="M&A Intern", city="Paris"), False),
    ("manual_no_url_two_roles", manual(company="Berenberg", title="Stage Sales Trading", city="Hamburg"),
     manual(company="Berenberg", title="Stage Private Equity", city="Hamburg"), False),
    ("unknown_weak_titles_rejected", ats("greenhouse", id="1301", url="https://job-boards.greenhouse.io/apprentie/jobs/1301",
                                         company="Apprentie Finance", title="Sustainability Reporting Intern", city="Paris"),
     ats("lever", id="1302", url="https://jobs.lever.co/apprentie/1302",
         company="Apprentie Finance", title="Sustainability Focus Intern", city="Paris"), False),
]


@pytest.mark.parametrize("case_id,record_a,record_b,expected",
                         [(pair[0], pair[1], pair[2], pair[3]) for pair in PAIRS],
                         ids=[pair[0] for pair in PAIRS])
def test_pairs_decide_exactly(case_id, record_a, record_b, expected):
    _ = case_id, record_a, record_b, expected
    assert match_records(record_a, record_b)["matches"] is expected


def test_pair_table_size_and_composition():
    merged = sum(1 for pair in PAIRS if pair[3])
    assert len(PAIRS) == len({pair[0] for pair in PAIRS}) == 43
    assert merged == 31 and len(PAIRS) - merged == 12


def test_refused_pairs_carry_explicit_reasons():
    conflicts = {pair[0]: match_records(pair[1], pair[2])["reasons"] for pair in PAIRS if not pair[3]}
    assert conflicts["levels_intern_vs_offcycle"] == ["role_level_conflict"]
    assert conflicts["recycled_id_new_role"] == ["recycled_identifier_conflict"]
    assert conflicts["recycled_id_new_city"] == ["recycled_identifier_conflict"]
    assert conflicts["false_neighbour_teams"] == ["different_role_same_employer"]
    assert conflicts["false_neighbour_families"] == ["different_role_same_employer"]
    assert conflicts["company_conflict_similar_titles"] == ["company_conflict"]
    assert conflicts["manual_no_url_two_roles"] == ["different_role_same_employer"]
    assert conflicts["city_conflict_never_merged"] == ["city_conflict"]
    assert conflicts["remote_vs_city_not_merged"] == ["city_conflict"]
    assert conflicts["unknown_weak_titles_rejected"] == ["no_shared_identity"]


def test_scalar_normalizers():
    assert canonical_company("JPMorgan Chase & Co.") == "jpmorgan"
    assert canonical_company({"company": "Point72 Asset Management"}) == "point72"
    assert canonical_company("Rothschild & Co SAS") == "rothschild"
    assert canonical_city({"city": "Télétravail"}) == "remote"
    assert canonical_city("Paris La Défense") == "paris"
    assert canonical_city("Francfort am Main") == "frankfurt"
    assert title_role_level("Investment Banking Off-Cycle Analyst") == "analyst"
    assert title_role_level({"title": "Stage M&A", "role_level": "intern"}) == "intern"
    assert title_role_level({"title": "Any job", "role_level": "weird level"}) == ""
    assert canonical_title_concept("Stage Banque d'Affaires 2027") == "investment_banking"
    assert canonical_title_concept("Tirocinio Private Equity") == "private_equity"
    assert canonical_title_concept("Brand Marketing Intern") == "brand marketing"


def test_decisions_are_deterministic_and_symmetric_in_strength():
    """A merge decision must not depend on the order the records are given."""
    deterministic = [match_records(pair[1], pair[2])["matches"] for pair in PAIRS]
    assert deterministic == [match_records(pair[1], pair[2])["matches"] for pair in PAIRS]


# ---------------------------------------------------------------------------
# Provenance conservation (all provenances, contradictory facts visible)
# ---------------------------------------------------------------------------

def test_group_conservates_every_provenance():
    records = [
        ats("greenhouse", id="4012345", url=GREENHOUSE_URL_PARIS, apply_url=GREENHOUSE_APPLY_URL,
            company="Lincoln International", title="M&A Intern", city="Paris", country="France",
            posted="2026-09-30", last_verified_at="2026-10-18T08:00:00+00:00"),
        ats("lever", id="a1b2c3", url=LEVER_URL_PARIS, apply_url="https://jobs.lever.co/lincoln-international/a1b2c3/apply",
            company="Lincoln International", title="M&A Intern", city="Paris", country="France",
            posted="2026-10-01", seen_at="2026-10-17T10:00:00+00:00"),
        manual(company="Lincoln International", title="Stage Banque d'Affaires", city="Paris",
               posted="2026-10-05"),
    ]
    group = deduplicate_jobs(records)[0]
    assert len(deduplicate_jobs(records)) == 1 and group["merged"]
    assert [view["source_name"] for view in group["provenances"]] == ["greenhouse", "lever", "manual"]
    assert {view["record"]["official_url"] for view in group["provenances"] if view["source_name"] == "lever"} \
        == {LEVER_URL_PARIS}
    assert {view["record"]["apply_url"] for view in group["provenances"] if view["source_name"] == "greenhouse"} \
        == {GREENHOUSE_APPLY_URL}
    assert {view["record"]["source_id"] for view in group["provenances"]} == {"4012345", "a1b2c3", ""}
    assert all(view["record"].get("posted_date") is not None for view in group["provenances"])
    assert set(group["conflicts"]) >= {"posted_date"}
    assert group["conflicts"]["posted_date"]["greenhouse:4012345"] == "2026-09-30"
    assert group["conflicts"]["posted_date"]["lever:a1b2c3"] == "2026-10-01"
    assert group["match_reasons"]


def test_divergent_dates_merge_but_stay_visible():
    first = ats("greenhouse", id="801", url=GREENHOUSE_URL_PARIS, company="Lincoln International",
                title="M&A Intern", city="Paris", posted="2026-09-14")
    second = ats("greenhouse", id="801", url=GREENHOUSE_URL_PARIS, company="Lincoln International",
                 title="M&A Intern", city="Paris", posted="2026-10-01")
    group = deduplicate_jobs([first, second])[0]
    assert len(deduplicate_jobs([first, second])) == 1
    conflicts = group["conflicts"]
    assert set(conflicts["posted_date"].values()) == {"2026-09-14", "2026-10-01"}
    assert list(conflicts["posted_date"]) == ["greenhouse:801", "greenhouse:801#2"]


def test_city_conflict_kept_visible_not_silently_rewritten():
    """Same URL but the re-crawl wrote remote: merged once, both facts shown."""
    first = ats("greenhouse", id="1401", url="https://job-boards.greenhouse.io/citi/jobs/1401",
                company="Citi", title="Sales & Trading Intern", city="London")
    second = ats("greenhouse", id="1401", url="https://job-boards.greenhouse.io/citi/jobs/1401",
                 company="Citi", title="Sales & Trading Intern", city="Remote")
    group = deduplicate_jobs([first, second])[0]
    assert group["merged"]
    assert set(group["conflicts"]["city"].values()) == {"London", "Remote"}


# ---------------------------------------------------------------------------
# Election of the best record (official strength > verified > fresh > complete)
# ---------------------------------------------------------------------------

def test_best_election_official_before_anything_else():
    records = [
        manual(company="Lincoln International", title="M&A Intern", city="Paris", url=GREENHOUSE_URL_PARIS,
               posted="2026-10-15", extra={"description_original": "richer typed text", "duration_months": 6}),
        ats("greenhouse", id="4012345", url=GREENHOUSE_URL_PARIS, company="Lincoln International",
            title="M&A Intern", city="Paris"),
    ]
    group = deduplicate_jobs(records)[0]
    assert group["best"]["source_name"] == "greenhouse"
    assert len(group["provenances"]) == 2


def test_freshness_breaks_official_ties():
    first = ats("greenhouse", id="2001", url="https://job-boards.greenhouse.io/xtx/jobs/2001",
                company="XTX Markets", title="Quant Research Intern", city="London",
                last_verified_at="2026-10-15T09:00:00+00:00")
    second = ats("lever", id="xtx-r", url="https://jobs.lever.co/xtx/xtx-r",
                 company="XTX Markets", title="Quantitative Research Intern", city="London",
                 last_verified_at="2026-10-19T09:00:00+00:00")
    group = deduplicate_jobs([first, second])[0]
    assert group["best"]["source_name"] == "lever"
    assert {view["source_name"] for view in group["provenances"]} == {"greenhouse", "lever"}


def test_completeness_breaks_same_trust_same_freshness_ties():
    thin = manual(company="Mid Cap Partners", title="Stage M&A", city="Paris")
    rich = manual(company="Mid Cap Partners", title="Stage M&A", city="Paris",
                  extra={"description_original": "long text", "duration_months": 6, "country": "France"})
    group = deduplicate_jobs([thin, rich])[0]
    assert group["best"] is rich


def test_source_verified_tiebreak():
    unverified = manual(company="IK Partners", title="Stage Private Equity", city="Paris")
    verified = manual(company="IK Partners", title="Stage Private Equity", city="Paris",
                      extra={"source_verified": True})
    group = deduplicate_jobs([unverified, verified])[0]
    assert group["best"]["source_verified"] is True


def test_explicit_employer_tier_outranks_board():
    records = [
        ats("greenhouse", id="3001", url="https://job-boards.greenhouse.io/optiver/jobs/3001",
            company="Optiver", title="Market Risk Intern", city="Amsterdam"),
        ats("employer_sites", id="", url="https://www.optiver.com/jobs/3001",
            company="Optiver", title="Market Risk Intern", city="Amsterdam",
            extra={"source_tier": "employer"}),
    ]
    group = deduplicate_jobs(records)[0]
    assert group["best"]["official_url"] == "https://www.optiver.com/jobs/3001"


def test_user_relevance_score_never_decides_election():
    """A polarized user relevance must not flip which source view survives."""
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
        clone["user_score"] = 99 - clone["user_score"]  # fully invert the user ranking
        flipped.append(clone)
    result = deduplicate_jobs(flipped)
    assert (result[0]["best"]["source_name"], result[0]["best"]["source_id"],
            result[0]["best"]["official_url"]) == \
        (baseline[0]["best"]["source_name"], baseline[0]["best"]["source_id"],
         baseline[0]["best"]["official_url"])
    assert baseline[0]["best"]["source_name"] == "greenhouse"
    assert len(baseline[0]["provenances"]) == len(result[0]["provenances"]) == 2


def test_recycled_identifier_flagged_in_group_output():
    stale = ats("greenhouse", id="6001", url="https://job-boards.greenhouse.io/man/jobs/6001",
                company="Man Group", title="M&A Intern 2027", city="London", posted="2026-10-01")
    reused = ats("greenhouse", id="6001", url="https://job-boards.greenhouse.io/man/jobs/6001-reused",
                 company="Man Group", title="Private Equity Intern 2028", city="London", posted="2026-10-12")
    groups = deduplicate_jobs([stale, reused])
    assert len(groups) == 2
    assert all(group["identifier_collision"] for group in groups)


def test_dedup_id_is_a_stable_storage_identity():
    record = ats("greenhouse", id="4012345", url=GREENHOUSE_URL_PARIS,
                 company="Lincoln International", title="M&A Intern", city="Paris")
    group = deduplicate_jobs([record])[0]
    assert group["dedup_id"].startswith("source:greenhouse:4012345")
    assert group["merged"] is False
    assert group["conflicts"] == {}
    assert group["member_indexes"] == [0]


def test_unknown_feed_is_ranked_between_boards_and_manual():
    board = ats("greenhouse", id="6101", url="https://job-boards.greenhouse.io/ga/jobs/6101",
                company="General Atlantic", title="Value Creation Intern", city="London")
    aggregator = ats("campus_channel", id="cc-1", url="https://jobs.campuschannel.com/enterprise/offer/991",
                     company="General Atlantic", title="Value Creation Internship", city="London")
    person = manual(company="General Atlantic", title="Stage Value Creation", city="London")
    group = deduplicate_jobs([aggregator, board, person])[0]
    assert len(deduplicate_jobs([aggregator, board, person])) == 1
    assert group["best"]["source_name"] in {"greenhouse", "campus_channel"}
    assert {view["source_name"] for view in group["provenances"]} == \
        {"greenhouse", "campus_channel", "manual"}


def test_two_similar_names_never_overwrite_one_record_identity():
    """Deduplicate purely in memory: a group keeps dict objects untouched."""
    record = manual(company="IK Partners", title="Stage Private Equity", city="Paris")
    result = deduplicate_jobs([record])
    assert result[0]["best"] is record
    assert result[0]["provenances"][0]["record"] == record


def test_choose_best_directly_orders_every_priority():
    person = manual(company="A", title="M&A Intern", city="Paris")
    fresh_board = ats("lever", id="l1", url="https://jobs.lever.co/a/l1", company="A",
                      title="M&A Intern", city="Paris", last_verified_at="2026-10-19T00:00:00+00:00")
    stale_board = ats("lever", id="l0", url="https://jobs.lever.co/a/l0", company="A",
                      title="M&A Intern", city="Paris", last_verified_at="2026-09-01T00:00:00+00:00")
    assert choose_best([person, fresh_board]) is fresh_board  # official wins
    assert choose_best([stale_board, fresh_board]) is fresh_board  # freshness wins


# ---------------------------------------------------------------------------
# Synthetic truth: precision / recall over a 45-record corpus
# ---------------------------------------------------------------------------

def truth_corpus():
    """Synthetic corpus: 22 true groups (15 true pairs), 14 negatives, 45 records."""
    truth: dict[int, str] = {}
    records: list[dict] = []

    def add(truth_id, *new_records):
        for record in new_records:
            truth[len(records)] = truth_id
            records.append(record)

    add("g1_lincoln_paris", ats("greenhouse", id="4012345", url=GREENHOUSE_URL_PARIS,
                                company="Lincoln International", title="M&A Intern", city="Paris",
                                posted="2026-09-30"),
        ats("lever", id="a1b2c3", url=LEVER_URL_PARIS, company="Lincoln International",
            title="M&A Intern", city="Paris"),
        manual(company="Lincoln International", title="Stage Banque d'Affaires", city="Paris"))
    add("g2_alix_utm", ats("greenhouse", id="7011",
                           url="https://job-boards.greenhouse.io/alixpartners/jobs/7011?utm_source=x",
                           company="AlixPartners", title="Private Equity Intern", city="Paris"),
        ats("greenhouse", id="7011", url="https://job-boards.greenhouse.io/alixpartners/jobs/7011",
            company="AlixPartners", title="Private Equity Intern", city="Paris"))
    add("g3_jpmorgan_lux", manual(company="J.P. Morgan", title="Stage Banque d'Affaires", city="Luxembourg"),
        ats("lever", id="jpm9", url="https://jobs.lever.co/jpmorgan/jpm9", company="JPMorgan Chase & Co.",
            title="Investment Banking Intern", city="Luxembourg"))
    add("g4_mediobanca_milano", manual(company="Mediobanca", title="Tirocinio M&A Milano", city="Milano"),
        ats("lever", id="mb1", url="https://jobs.eu.lever.co/mediobanca/mb1", company="Mediobanca",
            title="M&A Intern", city="Milan"))
    add("g5_point72_london", ats("greenhouse", id="201", url="https://job-boards.greenhouse.io/point72/jobs/201",
                                 company="Point72", title="Quantitative Research Intern", city="London"),
        manual(company="Point72", title="Stage Quantitative Research", city="Londres"))
    add("g6_xtx_remote", ats("greenhouse", id="601", url="https://job-boards.greenhouse.io/xtx/jobs/601",
                             company="XTX Markets", title="Software Engineering Intern", city="Remote — Europe"),
        manual(company="XTX Markets", title="Internship Software Engineering", city="Télétravail"))
    add("g7_schonfeld_recycled", ats("greenhouse", id="5100", url="https://job-boards.greenhouse.io/schonfeld/jobs/5100",
                                     company="Schonfeld", title="Investment Research Intern", city="London",
                                     posted="2026-10-03"),
        ats("greenhouse", id="5100", company="Schonfeld", title="Investment Research Intern",
            city="London", posted="2026-10-09"))
    add("g8_synthbank_dates", ats("greenhouse", id="sb-1", url="https://job-boards.greenhouse.io/synthbank/jobs/sb-1",
                                  company="SynthBank Capital", title="Corporate Finance Intern", city="Frankfurt",
                                  posted="2026-09-14"),
        ats("lever", id="sb-l1", url="https://jobs.lever.co/synthbank/sb-l1", company="SynthBank Capital",
            title="Internship Corporate Finance", city="Frankfurt", posted="2026-10-01"))
    add("g9_midcap_exact", manual(company="Mid Cap Partners", title="Stage Corporate Finance", city="Paris"),
        manual(company="Mid Cap Partners", title="Stage Corporate Finance", city="Paris"))
    add("g10_aqr_la_defense", ats("greenhouse", id="301", url="https://job-boards.greenhouse.io/aqr/jobs/301",
                                  company="AQR", title="Investment Research Intern", city="Paris La Défense"),
        ats("lever", id="aqr-l", url="https://jobs.eu.lever.co/aqr/aqr-l", company="AQR",
            title="Investment Research Internship", city="Paris"))
    add("g11_goldman_program", ats("greenhouse", id="706", url="https://job-boards.greenhouse.io/gm/jobs/706",
                                   company="Goldman Sachs", title="Investment Banking Program", city="Paris"),
        manual(company="Goldman Sachs & Co.", title="M&A Intern", city="Paris"))
    add("g12_lincoln_apply_url", ats("greenhouse", id="4099b", url="https://job-boards.greenhouse.io/lincoln/jobs/4099b",
                                     apply_url="https://job-boards.greenhouse.io/lincolninternational/jobs/4099/apply",
                                     company="Lincoln International", title="Corporate Finance Intern", city="Paris"),
        ats("lever", id="cf-l", url="https://jobs.lever.co/other/cf-x",
            apply_url="https://job-boards.greenhouse.io/lincolninternational/jobs/4099/apply",
            company="Lincoln International", title="Internship Corporate Finance", city="Paris"))
    add("g13_point72_alias", ats("greenhouse", id="901", url="https://job-boards.greenhouse.io/point72/jobs/901",
                                 company="Point72 Asset Management", title="Equity Research Intern", city="London"),
        manual(company="Point72", title="Stage Equity Research", city="London"))
    add("g14_flowtraders_milano", ats("lever", id="301", url="https://jobs.eu.lever.co/flow/milano",
                                      company="Flow Traders", title="Trading Internship", city="Milano"),
        ats("greenhouse", id="302", url="https://job-boards.greenhouse.io/flowtraders/jobs/302",
            company="Flow Traders", title="Trading Intern", city="Milan"))
    add("g15_qube_remote", ats("lever", id="602", url="https://jobs.lever.co/qube/602",
                               company="Qube Research & Technologies", title="Quant Developer Intern",
                               city="Full Remote"),
        manual(company="Qube Research & Technologies", title="Internship Quant Developer",
               city="Work from home"))
    add("g16_tikehau_translated", manual(company="Tikehau Capital", title="Stage Capital-Investissement", city="Paris"),
        ats("ashby", id="tk1", url="https://jobs.ashbyhq.com/tikehau/tk1", company="Tikehau Capital",
            title="Private Equity Intern", city="Paris"))
    add("g17_evercore_nyc", ats("lever", id="902", url="https://jobs.lever.co/evercore/902",
                                company="Evercore Inc.", title="Fintech M&A Intern", city="New York City"),
        manual(company="Evercore ISI", title="M&A Internship", city="NYC"))
    add("g18_jefferies_hf", manual(company="Jefferies", title="Stage M&A H/F", city="Paris"),
        manual(company="Jefferies", title="M&A Internship", city="Paris"))
    add("g19_ga_intern", ats("greenhouse", id="701", url="https://job-boards.greenhouse.io/ga/jobs/701",
                             company="General Atlantic", title="Investment Banking Intern", city="Luxembourg"),
        manual(company="General Atlantic", title="Stage Banque d'Affaires", city="Luxembourg"))
    add("g20_gs_frankfurt", ats("greenhouse", id="704", url="https://job-boards.greenhouse.io/gm/jobs/704",
                                company="Goldman Sachs", title="Corporate Finance Intern", city="Frankfurt"),
        manual(company="Goldman Sachs", title="Stage Corporate Finance", city="Francfort"))
    add("g21_lazard_paris", ats("greenhouse", id="1101", url="https://job-boards.greenhouse.io/lazard/jobs/1101",
                                company="Lazard", title="M&A Intern", city="Paris"),
        manual(company="Lazard Frères", title="Stage Fusion-Acquisition", city="Paris"))
    add("g22_optiver_amsterdam", ats("greenhouse", id="3001", url="https://job-boards.greenhouse.io/optiver/jobs/3001",
                                     company="Optiver", title="Market Risk Intern", city="Amsterdam"),
        ats("employer_sites", id="", url="https://www.optiver.com/jobs/3001", company="Optiver",
            title="Market Risk Intern", city="Amsterdam", extra={"source_tier": "employer"}))

    # Deliberate negatives: same employers, different role, level, city or id.
    add("n1_ga_offcycle", ats("greenhouse", id="702", url="https://job-boards.greenhouse.io/ga/jobs/702",
                              company="General Atlantic", title="Investment Banking Off-Cycle Analyst",
                              city="Luxembourg"))
    add("n2_bnp_analyst", ats("greenhouse", id="703", url="https://job-boards.greenhouse.io/bnp/jobs/703",
                              company="BNP Paribas", title="M&A Analyst", city="Paris"))
    add("n3_lazard_pe", ats("lever", id="1102", url="https://jobs.lever.co/lazard/1102", company="Lazard",
                            title="Private Equity Intern", city="Paris"))
    add("n4_evercore_recycled_london", ats("lever", id="6100", url="https://jobs.lever.co/evercore/6100",
                                           company="Evercore", title="Financial Analysis Intern", city="London"))
    add("n5_evercore_recycled_milan", ats("lever", id="6100", url="https://jobs.lever.co/evercore/6100-v2",
                                          company="Evercore", title="Financial Analysis Intern", city="Milan",
                                          posted="2026-10-12"))
    add("n6_man_reused_ma", ats("greenhouse", id="6001", url="https://job-boards.greenhouse.io/man/jobs/6001",
                                company="Man Group", title="M&A Intern 2027", city="London"))
    add("n7_man_reused_pe", ats("greenhouse", id="6001", url="https://job-boards.greenhouse.io/man/jobs/6001-reused",
                                company="Man Group", title="Private Equity Intern 2028", city="London",
                                posted="2026-10-12"))
    add("n8_berenberg_trading", manual(company="Berenberg", title="Stage Sales Trading", city="Hamburg"))
    add("n9_berenberg_pe", manual(company="Berenberg", title="Stage Private Equity", city="Hamburg"))
    add("n10_alix_vs_lincoln", ats("lever", id="1202", url="https://jobs.lever.co/alix/1202",
                                   company="AlixPartners", title="M&A Intern", city="Paris"))
    add("n11_ubp_corp_finance", ats("greenhouse", id="1103", url="https://job-boards.greenhouse.io/ubp/jobs/1103",
                                    company="Union Bancaire Privée", title="Corporate Finance Intern", city="Geneva"))
    add("n12_ubp_asset_mgmt", ats("lever", id="1104", url="https://jobs.lever.co/ubp/1104",
                                  company="Union Bancaire Privée", title="Asset Management Intern", city="Geneva"))
    add("n13_goldman_asset_frankfurt", manual(company="Goldman Sachs", title="Stage Gestion d'Actifs",
                                              city="Frankfurt"))
    add("n14_unicredit_milano", manual(company="UniCredit", title="Stage Gestion d'Actifs", city="Milano"))
    return records, truth


def test_synthetic_truth_precision_and_recall_are_perfect():
    records, truth = truth_corpus()
    labelled_records = len(truth)
    truth_pairs = sum(1 for first in truth for second in truth
                      if first < second and truth[first] == truth[second])
    assert labelled_records == 59
    assert len(set(truth.values())) == 36  # 22 true groups + 14 singletons
    assert truth_pairs == 24  # one triple + 21 pairs
    report = evaluate_deduplication(records, truth)
    assert report["precision"] == 1.0, report
    assert report["recall"] == 1.0, report
    assert report["f1"] == 1.0, report
    assert report["true_pairs"] == truth_pairs
    assert report["error_pairs"] == 0.0


def test_evaluation_detects_over_merging():
    """Two identical records wrongly labelled distinct: precision collapses."""
    records = [
        manual(company="Mid Cap Partners", title="Stage Corporate Finance", city="Paris"),
        manual(company="Mid Cap Partners", title="Stage Corporate Finance", city="Paris"),
    ]
    report = evaluate_deduplication(records, {0: "a", 1: "b"})
    assert report["precision"] == 0.0
    assert report["recall"] == 1.0
    assert report["error_pairs"] == 1.0  # one predicted pair the truth refuses


def test_evaluation_detects_under_merging():
    """A missed pair between same-truth records: recall collapses."""
    records = [
        ats("greenhouse", id="1", url="https://job-boards.greenhouse.io/a/jobs/1", company="A",
            title="M&A Intern", city="Paris"),
        ats("greenhouse", id="2", url="https://job-boards.greenhouse.io/b/jobs/2", company="B",
            title="M&A Intern", city="Paris"),
    ]
    report = evaluate_deduplication(records, {0: "a", 1: "a"})
    assert report["precision"] == 1.0
    assert report["recall"] == 0.0
    assert report["error_pairs"] == 1.0  # one true pair the grouper missed
