"""Tests for ATS connectors (SPEC-038)."""

from __future__ import annotations


import pytest

from career.connectors.ats_registry import detect_ats, load_banks_list, ats_for_bank
from career.connectors.ats_generic import parse_job, AtsJob, fetch_html


# ---------- registry: URL -> ATS ----------

CASES = [
    ("https://company.myworkdayjobs.com/en-US/jobs", "workday"),
    ("https://wd5.myworkdayjobs.com/External", "workday"),
    ("https://workday.com/careers", "workday"),
    ("https://career.successfactors.com/career", "successfactors"),
    ("https://successfactors.com/jobs", "successfactors"),
    ("https://boards.greenhouse.io/acme/jobs/123", "greenhouse"),
    ("https://boards-api.greenhouse.io/v1/boards/acme/jobs/123", "greenhouse"),
    ("https://greenhouse.io/jobs/1", "greenhouse"),
    ("https://company.taleo.net/careersection", "taleo"),
    ("https://taleo.net/jobs", "taleo"),
    ("https://www.smartrecruiters.com/Acme/123", "smartrecruiters"),
    ("https://api.smartrecruiters.com/v1/companies/Acme/postings/123", "smartrecruiters"),
    ("https://smartrecruiters.com/jobs", "smartrecruiters"),
    ("https://camejobs.com/job/123", "cameo"),
    ("https://aplica.ai/jobs/123", "aplica"),
    ("https://jobs.lever.co/acme/123", "lever"),
    ("https://lever.co/jobs", "lever"),
    ("https://jobs.ashbyhq.com/acme/123", "ashby"),
    ("https://ashbyhq.com/jobs", "ashby"),
    ("https://example.com/careers", "unknown"),
    ("", "unknown"),
    ("https://www.google.com", "unknown"),
    ("https://linkedin.com/jobs", "unknown"),
]


@pytest.mark.parametrize("url,expected", CASES)
def test_detect_ats(url, expected) -> None:
    assert detect_ats(url).name == expected


def test_detect_ats_confidence_unknown() -> None:
    assert detect_ats("https://example.com").confidence == 0.0


def test_detect_ats_confidence_known() -> None:
    assert detect_ats("https://boards.greenhouse.io/x").confidence == 1.0


def test_load_banks_list_default() -> None:
    banks = load_banks_list()
    assert isinstance(banks, list)
    assert len(banks) >= 1
    assert "name" in banks[0]
    assert "career_url" in banks[0]


def test_load_banks_list_missing(tmp_path) -> None:
    assert load_banks_list(tmp_path / "nope.json") == []


def test_load_banks_list_invalid(tmp_path) -> None:
    p = tmp_path / "b.json"
    p.write_text("{bad", encoding="utf-8")
    assert load_banks_list(p) == []


def test_ats_for_bank() -> None:
    bank = {"name": "X", "career_url": "https://boards.greenhouse.io/x/jobs/1"}
    p = ats_for_bank(bank)
    assert p.name == "greenhouse"


# ---------- parsing ----------

JSONLD_HTML = """
<html><head><title>x</title></head><body>
<script type="application/ld+json">
{"@type":"JobPosting","title":"Stage M&A","description":"Analyse financière",
 "jobLocation":{"address":{"addressLocality":"Paris","addressCountry":"FR"}},
 "occupationalCategory":"Finance"}
</script>
</body></html>
"""


def test_parse_jsonld() -> None:
    job = parse_job(JSONLD_HTML, "https://example.com/job/1")
    assert job.title == "Stage M&A"
    assert "Paris" in job.location
    assert job.department == "Finance"
    assert "Analyse" in job.description


def test_parse_jsonld_list() -> None:
    html = """
    <script type="application/ld+json">[{"@type":"JobPosting","title":"T","description":"D",
      "jobLocation":{"address":{"addressLocality":"Lyon","addressCountry":"FR"}}}]</script>
    """
    job = parse_job(html, "https://example.com/job/2")
    assert job.title == "T"
    assert "Lyon" in job.location


GREENHOUSE_HTML = """
<html><body>
<script>window.gh = {"title":"Stage Data","location":{"name":"Paris, FR"},
 "departments":[{"name":"Data"}],"content":"Build models"}</script>
</body></html>
"""


def test_parse_greenhouse_embedded() -> None:
    # Need the marker boards-api.greenhouse.io in html
    html = GREENHOUSE_HTML.replace("window.gh", "x boards-api.greenhouse.io")
    job = parse_job(html, "https://boards.greenhouse.io/acme/jobs/1")
    assert job.title == "Stage Data"
    assert job.location == "Paris, FR"
    assert job.department == "Data"
    assert job.description == "Build models"


SMARTRECRUITERS_HTML = """
<html><body>
x smartrecruiters.com {"name":"Stage M&A","location":{"city":"Paris","country":"FR"},
 "department":{"label":"Finance"},"jobAd":{"sections":{"jobDescription":{"text":"Analyse"}}}}
</body></html>
"""


def test_parse_smartrecruiters_embedded() -> None:
    job = parse_job(SMARTRECRUITERS_HTML, "https://www.smartrecruiters.com/acme/1")
    assert job.title == "Stage M&A"
    assert "Paris" in job.location
    assert job.department == "Finance"
    assert job.description == "Analyse"


FALLBACK_HTML = "<html><head><title>Stage Finance - Acme</title><meta name=\"description\" content=\"Offre de stage\"></head><body></body></html>"


def test_parse_fallback_title_meta() -> None:
    job = parse_job(FALLBACK_HTML, "https://example.com/job/3")
    assert job.title == "Stage Finance - Acme"
    assert job.description == "Offre de stage"


def test_parse_empty_html() -> None:
    job = parse_job("", "https://example.com/job/4")
    assert job.title == ""
    assert job.platform == "unknown" or isinstance(job.platform, str)


def test_parse_job_platform_set() -> None:
    job = parse_job(JSONLD_HTML, "https://boards.greenhouse.io/acme/jobs/9")
    assert job.platform == "greenhouse"


def test_atsjob_dataclass() -> None:
    j = AtsJob(title="t", location="l", department="d", description="desc", url="u", platform="p")
    assert j.title == "t"


def test_to_dict() -> None:
    from career.connectors.ats_generic import to_dict
    j = AtsJob(title="t")
    d = to_dict(j)
    assert d["title"] == "t"


# ---------- fetch_html (mocked) ----------

def test_fetch_html_invalid_scheme() -> None:
    with pytest.raises(ValueError):
        fetch_html("ftp://example.com")


def test_fetch_html_429(monkeypatch) -> None:
    import urllib.error

    def fake_urlopen(req, timeout=10, context=None):
        raise urllib.error.HTTPError(url="u", code=429, msg="too many", hdrs={}, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        fetch_html("https://example.com/x")


# ---------- banks list ----------

def test_banks_list_has_ats_field() -> None:
    banks = load_banks_list()
    for b in banks:
        assert "ats" in b


def test_banks_list_count() -> None:
    banks = load_banks_list()
    assert len(banks) >= 3


def test_detect_ats_case_insensitive() -> None:
    assert detect_ats("https://BOARDS.GREENHOUSE.IO/x").name == "greenhouse"


def test_detect_ats_trailing_slash() -> None:
    assert detect_ats("https://jobs.lever.co/acme/123/").name == "lever"


def test_parse_job_jsonld_missing_fields() -> None:
    html = '<script type="application/ld+json">{"@type":"JobPosting","title":"T"}</script>'
    job = parse_job(html, "https://example.com/j")
    assert job.title == "T"
    assert job.location == ""