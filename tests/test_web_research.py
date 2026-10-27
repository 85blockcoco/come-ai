"""SPEC-018 — offline coverage for the Career web researcher.

Every fixture is synthetic: ``acme.test``, synthetic GitHub JSON and a fake
search provider.  No test performs a network request, and the injectable clock
makes the 24 h cache deterministic.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.router import create_career_router
from career.service import CareerService
from career.web_evidence import (
    EvidenceNotVerifiable,
    WebEvidenceCenter,
    make_evidence,
    normalize_excerpt,
)
from career.web_research import WebResearcher
from career.web_sources import (
    STACK_ALIASES,
    VALUE_ALIASES,
    NullSearchProvider,
    RobotsRules,
    SearchHit,
    UrllibWebTransport,
    WebDocument,
    WebSourceError,
    build_search_queries,
    is_public_http_url,
    parse_html,
    parse_robots,
    stack_terms,
)
from workspace_core import UserFacingError

NOW = datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)

HOME_HTML = """<html><head><title>Acme Robotics</title>
<meta name="description" content="Autonomous fleet software"></head><body>
<h1>Acme Robotics</h1>
<p>We build autonomous robots with Python and Kubernetes. Our stack also uses k8s and PostgreSQL.</p>
<p>We value innovation, collaboration and work-life balance.</p>
<a href="https://github.com/acme-robotics">Our GitHub</a>
<script>const secret = "never quoted";</script>
</body></html>"""

ABOUT_HTML = """<html><head><title>About Acme</title></head><body>
<p>Our teams use Python, Docker and Terraform.</p>
<p>We believe in inclusion and transparency.</p>
</body></html>"""

CAREERS_HTML = """<html><head><title>Careers at Acme</title></head><body>
<p>Join us: we learn every day and we ship robots.</p>
</body></html>"""


class MutableClock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **kwargs: float) -> None:
        self.moment += timedelta(**kwargs)


class FakeTransport:
    """Injected transport: deterministic documents, no socket."""

    def __init__(self, pages: dict[str, object]) -> None:
        self.pages = dict(pages)
        self.calls: list[str] = []

    def fetch(self, url: str, *, timeout_seconds: int = 8) -> WebDocument:
        _ = timeout_seconds
        self.calls.append(url)
        value = self.pages.get(url)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise WebSourceError("Cette page publique n’existe pas (404).", code="404")
        content_type, text = value if isinstance(value, tuple) else ("text/html; charset=utf-8", str(value))
        return WebDocument(
            url=url,
            final_url=url,
            status_code=200,
            content_type=content_type,
            text=text,
            fetched_at="2026-10-22T10:00:00Z",
        )


class FakeSearch:
    def __init__(self, hits: list[SearchHit], *, available: bool = True) -> None:
        self.hits = hits
        self.available = available
        self.calls = 0

    def search(self, query: str, *, limit: int = 5) -> list[SearchHit]:
        _ = query
        self.calls += 1
        if not self.available:
            raise WebSourceError("Le moteur de recherche est hors ligne.", code="offline", retryable=True)
        return self.hits[: max(0, limit)]


def site_pages() -> dict[str, object]:
    org = {
        "login": "acme-robotics",
        "html_url": "https://github.com/acme-robotics",
        "description": "Open robotics platform",
    }
    repos = [
        {
            "name": "fleet",
            "html_url": "https://github.com/acme-robotics/fleet",
            "description": "Fleet manager",
            "language": "Python",
            "stargazers_count": 120,
            "topics": ["robotics"],
            "pushed_at": "2026-10-20T10:00:00Z",
            "updated_at": "2026-10-20T10:00:00Z",
        },
        {
            "name": "sim",
            "html_url": "https://github.com/acme-robotics/sim",
            "description": "Fleet simulator",
            "language": "Rust",
            "stargazers_count": 40,
            "topics": [],
            "pushed_at": "2026-09-01T10:00:00Z",
            "updated_at": "2026-09-01T10:00:00Z",
        },
    ]
    return {
        "https://acme.test/robots.txt": ("text/plain; charset=utf-8", "User-agent: *\nAllow: /\n"),
        "https://acme.test/": ("text/html; charset=utf-8", HOME_HTML),
        "https://acme.test/about": ("text/html; charset=utf-8", ABOUT_HTML),
        "https://acme.test/careers": ("text/html; charset=utf-8", CAREERS_HTML),
        "https://api.github.com/orgs/acme-robotics": ("application/json", json.dumps(org)),
        "https://api.github.com/orgs/acme-robotics/repos?per_page=20&sort=pushed": (
            "application/json",
            json.dumps(repos),
        ),
        "https://api.github.com/repos/acme-robotics/fleet/releases?per_page=3": (
            "application/json",
            json.dumps(
                [
                    {
                        "name": "v2.0",
                        "tag_name": "v2.0",
                        "published_at": "2026-10-01T00:00:00Z",
                        "html_url": "https://github.com/acme-robotics/fleet/releases/v2.0",
                    }
                ]
            ),
        ),
        "https://api.github.com/repos/acme-robotics/sim/releases?per_page=3": ("application/json", "[]"),
    }


def search_hits() -> list[SearchHit]:
    return [
        SearchHit(
            title="Acme Robotics raises Series B",
            url="https://news.example.test/acme-series-b",
            excerpt="Acme Robotics announced a Series B to expand its autonomous fleet.",
            date="2026-10-15",
        ),
        SearchHit(
            title="Acme open-sources fleet simulator",
            url="https://news.example.test/acme-simulator",
            excerpt="The simulator is written in Rust and used by robotics teams.",
            date=None,
        ),
    ]


def an_offer(**updates: object) -> dict[str, object]:
    offer: dict[str, object] = {
        "id": "job-1",
        "company": "Acme Robotics",
        "title": "Robotics Intern",
        "city": "Paris",
        "official_url": "https://acme.test/jobs/42",
        "description_original": "Build autonomous fleet software with Python.",
    }
    offer.update(updates)
    return offer


def build_researcher(
    tmp_path: Path,
    *,
    pages: dict[str, object] | None = None,
    search: object | None = None,
    clock: MutableClock | None = None,
    ttl_hours: float = 24,
) -> tuple[WebResearcher, FakeTransport, FakeSearch]:
    fake = FakeTransport(site_pages() if pages is None else pages)
    fake_search = FakeSearch(search_hits()) if search is None else search
    researcher = WebResearcher(
        cache_dir=tmp_path / "web-research",
        transport=fake,
        search_provider=fake_search,
        clock=clock or MutableClock(NOW),
        ttl_hours=ttl_hours,
    )
    return researcher, fake, fake_search  # type: ignore[return-value]


# --- 1. Facts and their proof -------------------------------------------------


def test_stack_and_values_are_extracted_with_quotable_evidence(tmp_path: Path) -> None:
    researcher, _, _ = build_researcher(tmp_path)
    facts = researcher.research(an_offer())

    assert facts.status == "ok"
    assert {"python", "kubernetes", "postgresql", "docker", "terraform"} <= set(facts.stack)
    assert {"innovation", "collaboration", "équilibre", "inclusion", "transparence"} <= set(facts.values)
    assert facts.evidence_ids
    assert len(facts.evidence_ids) == len(set(facts.evidence_ids))

    page_text = {
        "https://acme.test/": normalize_excerpt(parse_html(HOME_HTML, "https://acme.test/").text),
        "https://acme.test/about": normalize_excerpt(parse_html(ABOUT_HTML, "https://acme.test/about").text),
        "https://acme.test/careers": normalize_excerpt(parse_html(CAREERS_HTML, "https://acme.test/careers").text),
    }
    for item in facts.evidence:
        assert item["excerpt"]
        if item["source_kind"] == "company_site":
            assert item["excerpt"] in page_text[item["url"]], "a site excerpt must be verbatim"


def test_every_stack_and_value_term_has_a_matching_evidence_item(tmp_path: Path) -> None:
    researcher, _, _ = build_researcher(tmp_path)
    facts = researcher.research(an_offer())

    stack_evidence = [item for item in facts.evidence if item["fact_kind"] == "stack"]
    value_evidence = [item for item in facts.evidence if item["fact_kind"] == "values"]
    for term in facts.stack:
        aliases = STACK_ALIASES[term]
        assert any(
            any(alias in item["excerpt"].lower() for alias in aliases) for item in stack_evidence
        ), f"stack term {term!r} has no quoted evidence"
    for term in facts.values:
        aliases = VALUE_ALIASES[term]
        assert any(
            any(alias in item["excerpt"].lower() for alias in aliases) for item in value_evidence
        ), f"value {term!r} has no quoted evidence"
    assert all(item["id"] in facts.evidence_ids for item in facts.evidence)


def test_github_summary_uses_only_public_fields(tmp_path: Path) -> None:
    researcher, _, _ = build_researcher(tmp_path)
    facts = researcher.research(an_offer())

    summary = facts.repos_summary
    assert summary["org"] == "acme-robotics"
    assert summary["repo_count"] == 2
    assert summary["languages"] == {"Python": 1, "Rust": 1}
    assert [repo["name"] for repo in summary["top_repos"]] == ["fleet", "sim"]
    assert summary["recent_releases"][0]["name"] == "v2.0"
    assert any(item["source_kind"] == "github" for item in facts.evidence)


def test_news_never_invents_a_missing_date(tmp_path: Path) -> None:
    researcher, _, _ = build_researcher(tmp_path)
    facts = researcher.research(an_offer())

    assert [hit.title for hit in facts.recent_news] == [
        "Acme Robotics raises Series B",
        "Acme open-sources fleet simulator",
    ]
    assert facts.recent_news[0].date == "2026-10-15"
    assert facts.recent_news[1].date is None
    assert all(hit.url.startswith("https://") for hit in facts.recent_news)


def test_confidence_stays_bounded_and_reflects_evidence(tmp_path: Path) -> None:
    researcher, _, _ = build_researcher(tmp_path)
    facts = researcher.research(an_offer())
    assert 0.0 < facts.confidence <= 0.95

    empty_pages: dict[str, object] = {"https://acme.test/robots.txt": ("text/plain", "User-agent: *\n")}
    offline, _, _ = build_researcher(
        tmp_path / "empty", pages=empty_pages, search=NullSearchProvider()
    )
    empty = offline.research(an_offer())
    assert empty.confidence == 0.0
    assert empty.stack == []
    assert empty.values == []


# --- 2. Cache and offline behaviour -------------------------------------------


def test_cache_is_reused_without_network_for_24_hours(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    researcher, fake, _ = build_researcher(tmp_path, clock=clock)
    first = researcher.research(an_offer())
    calls_after_first = len(fake.calls)

    clock.advance(hours=1)
    second = researcher.research(an_offer())

    assert len(fake.calls) == calls_after_first
    assert second.from_cache is True
    assert second.status == "cached"
    assert second.evidence_ids == first.evidence_ids
    assert second.stack == first.stack


def test_cache_expires_after_24_hours(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    researcher, fake, _ = build_researcher(tmp_path, clock=clock)
    researcher.research(an_offer())
    calls_after_first = len(fake.calls)

    clock.advance(hours=25)
    refreshed = researcher.research(an_offer())

    assert len(fake.calls) > calls_after_first
    assert refreshed.from_cache is False
    assert refreshed.status == "ok"


def test_refresh_forces_a_new_read_even_when_fresh(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    researcher, fake, _ = build_researcher(tmp_path, clock=clock)
    researcher.research(an_offer())
    calls_after_first = len(fake.calls)

    researcher.research(an_offer(), refresh=True)
    assert len(fake.calls) > calls_after_first


def test_offline_after_expiry_reuses_the_stale_cache(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    researcher, fake, fake_search = build_researcher(tmp_path, clock=clock)
    first = researcher.research(an_offer())

    clock.advance(hours=25)
    fake.pages = {}
    fake_search.available = False
    stale = researcher.research(an_offer())

    assert stale.from_cache is True
    assert stale.stale is True
    assert stale.status == "cached"
    assert stale.evidence_ids == first.evidence_ids
    assert stale.stack == first.stack
    assert any("cache" in warning for warning in stale.warnings)


def test_offline_without_cache_returns_an_explicit_offline_result(tmp_path: Path) -> None:
    researcher, _, _ = build_researcher(
        tmp_path,
        pages={},
        search=NullSearchProvider(),
    )
    facts = researcher.research(an_offer())

    assert facts.status == "offline"
    assert facts.confidence == 0.0
    assert facts.evidence_ids == []
    assert facts.stack == [] and facts.values == []
    assert facts.warnings


def test_freshness_moves_from_not_found_to_fresh_to_stale(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    researcher, _, _ = build_researcher(tmp_path, clock=clock)

    missing = researcher.freshness(an_offer())
    assert missing["available"] is False
    assert missing["status"] == "not_found"

    researcher.research(an_offer())
    fresh = researcher.freshness(an_offer())
    assert fresh["available"] is True
    assert fresh["status"] == "fresh"
    assert fresh["fresh"] is True
    assert fresh["evidence_count"] > 0

    clock.advance(hours=25)
    stale = researcher.freshness(an_offer())
    assert stale["status"] == "stale"
    assert stale["stale"] is True
    assert stale["age_seconds"] >= 24 * 3600


# --- 3. robots.txt ------------------------------------------------------------


def test_robots_disallow_is_honoured(tmp_path: Path) -> None:
    pages = site_pages()
    pages["https://acme.test/robots.txt"] = ("text/plain", "User-agent: *\nDisallow: /about\n")
    researcher, fake, _ = build_researcher(tmp_path, pages=pages)

    facts = researcher.research(an_offer())

    assert "https://acme.test/about" not in fake.calls
    assert not any(item["url"].endswith("/about") for item in facts.evidence)
    assert "docker" not in facts.stack
    assert "python" in facts.stack


def test_unreachable_robots_does_not_block_the_usual_case(tmp_path: Path) -> None:
    pages = site_pages()
    pages["https://acme.test/robots.txt"] = WebSourceError("offline", code="offline")
    researcher, _, _ = build_researcher(tmp_path, pages=pages)

    facts = researcher.research(an_offer())
    assert "python" in facts.stack


def test_robots_parser_uses_longest_match_and_allow_ties() -> None:
    rules = parse_robots(
        """
        User-agent: *
        Disallow: /private
        Allow: /private/public
        Disallow: /same
        Allow: /same
        Crawl-delay: 2
        """
    )
    assert rules.allows("/private/secret") is False
    assert rules.allows("/private/public/page") is True
    assert rules.allows("/same") is True
    assert rules.allows("/elsewhere") is True
    assert rules.crawl_delay == 2.0


def test_robots_rules_directly() -> None:
    rules = RobotsRules(allow=("/ok/*",), disallow=("/ok/private",))
    assert rules.allows("/ok/page") is True
    assert rules.allows("/ok/private/x") is False


# --- 4. Transport guard and HTML ---------------------------------------------


def test_transport_refuses_private_or_plain_http_urls_before_any_socket() -> None:
    transport = UrllibWebTransport()
    for url, code in [
        ("http://127.0.0.1/private", "invalid_url"),
        ("https://localhost/admin", "invalid_url"),
        ("https://192.168.1.10/", "invalid_url"),
    ]:
        with pytest.raises(WebSourceError) as caught:
            transport.fetch(url)
        assert caught.value.code == code
    assert is_public_http_url("https://example.test/page") is True
    assert is_public_http_url("https://127.0.0.1/") is False
    assert is_public_http_url("ftp://example.test/") is False
    assert is_public_http_url("https://user:pass@example.test/") is False


def test_html_parser_drops_scripts_and_decodes_entities() -> None:
    page = parse_html(
        '<html><head><title>A &amp; B</title><meta name="description" content="D &amp; E"></head>'
        '<body><script>secret()</script><style>.x{}</style><p>R&amp;D team</p>'
        '<a href="/team">Team</a></body></html>',
        "https://acme.test/",
    )
    assert page.title == "A & B"
    assert page.description == "D & E"
    assert "secret" not in page.text
    assert "R&D team" in page.text
    assert "https://acme.test/team" in page.links


def test_malformed_html_is_tolerated() -> None:
    page = parse_html("<div><p>Hello <b>world", "https://acme.test/")
    assert "Hello" in page.text


# --- 5. Evidence contract -----------------------------------------------------


def test_evidence_refuses_an_excerpt_absent_from_its_source() -> None:
    with pytest.raises(EvidenceNotVerifiable):
        make_evidence(
            url="https://acme.test/about",
            title="About",
            excerpt="We use COBOL on mainframes.",
            source_kind="company_site",
            fact_kind="stack",
            retrieved_at="2026-10-22T10:00:00Z",
            confidence=0.6,
            source_text=ABOUT_HTML,
        )


def test_evidence_ids_are_deterministic_and_deduplicated() -> None:
    first = make_evidence(
        url="https://acme.test/about",
        title="About",
        excerpt="We use Python.",
        source_kind="company_site",
        fact_kind="stack",
        retrieved_at="2026-10-22T10:00:00Z",
        confidence=0.6,
    )
    second = make_evidence(
        url="https://acme.test/about#team",
        title="About",
        excerpt="We   use Python.",
        source_kind="company_site",
        fact_kind="stack",
        retrieved_at="2026-10-23T10:00:00Z",
        confidence=0.9,
    )
    assert first.id == second.id

    center = WebEvidenceCenter()
    assert center.add(first) is True
    assert center.add(second) is False
    assert center.ids == [first.id]
    assert center.by_fact() == {"stack": [first.id]}


def test_two_runs_on_the_same_pages_produce_the_same_ids(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    first_researcher, _, _ = build_researcher(tmp_path / "a", clock=clock)
    second_researcher, _, _ = build_researcher(tmp_path / "b", clock=clock)
    one = first_researcher.research(an_offer())
    two = second_researcher.research(an_offer())
    assert one.stack == two.stack
    assert one.values == two.values
    assert one.evidence_ids == two.evidence_ids


# --- 6. Detection helpers -----------------------------------------------------


def test_stack_detection_handles_aliases_and_word_boundaries() -> None:
    terms = stack_terms("We deploy with k8s, postgres and golang. The frontend is TypeScript.")
    assert {"kubernetes", "postgresql", "go", "typescript"} <= set(terms)
    assert "java" not in terms
    assert "javascript" not in terms


def test_search_queries_are_built_only_from_the_offer() -> None:
    queries = build_search_queries({"company": "Acme Robotics", "city": "Paris", "title": "Robotics Intern"})
    assert 1 <= len(queries) <= 3
    assert all("Acme Robotics" in query for query in queries)
    assert build_search_queries({}) == []


def test_missing_github_org_is_not_an_error(tmp_path: Path) -> None:
    pages = site_pages()
    pages.pop("https://api.github.com/orgs/acme-robotics")
    researcher, _, _ = build_researcher(tmp_path, pages=pages)
    facts = researcher.research(an_offer())
    assert facts.repos_summary == {}
    assert "python" in facts.stack
    assert facts.status in {"ok", "partial"}


def test_missing_site_page_is_skipped_not_filled_in(tmp_path: Path) -> None:
    pages = site_pages()
    pages.pop("https://acme.test/careers")
    researcher, _, _ = build_researcher(tmp_path, pages=pages)
    facts = researcher.research(an_offer())
    assert not any(item["url"].endswith("/careers") for item in facts.evidence)


# --- 7. User-provided sheet ---------------------------------------------------


def test_provide_merges_a_user_sheet_and_labels_it_user_provided(tmp_path: Path) -> None:
    researcher, _, _ = build_researcher(tmp_path)
    researcher.research(an_offer())

    updated = researcher.provide(
        an_offer(),
        {
            "company": "Acme Robotics",
            "stack": ["Excel"],
            "values": ["rigueur"],
            "notes": "Rencontré au forum des écoles.",
            "sources": [
                {
                    "url": "https://acme.test/careers",
                    "title": "Careers",
                    "excerpt": "Join us: we learn every day",
                    "fact_kind": "about",
                }
            ],
            "news": [
                {
                    "title": "Note interne",
                    "url": "https://acme.test/blog/post",
                    "date": "2026-10-20",
                    "excerpt": "Une note publiée par l’entreprise.",
                }
            ],
        },
    )

    assert updated.stack[0] == "Excel"
    assert updated.values[0] == "rigueur"
    assert updated.confidence >= 0.8
    assert updated.provided_at
    assert any(item["source_kind"] == "user_provided" for item in updated.evidence)
    assert any(item["url"].startswith("user:") and item["verifiable"] is False for item in updated.evidence)
    assert any(item["url"] == "https://acme.test/careers" for item in updated.evidence)

    freshness = researcher.freshness(an_offer())
    assert freshness["available"] is True
    assert freshness["provided_at"] == updated.provided_at
    assert freshness["status"] == "fresh"


def test_provide_works_offline_without_any_cache(tmp_path: Path) -> None:
    researcher, _, _ = build_researcher(tmp_path, pages={}, search=NullSearchProvider())

    updated = researcher.provide(an_offer(), {"stack": ["Python"], "notes": "Fiche personnelle."})

    assert updated.stack == ["Python"]
    assert updated.status == "ok"
    assert researcher.freshness(an_offer())["available"] is True


def test_provide_ignores_an_empty_source_with_a_clear_warning(tmp_path: Path) -> None:
    researcher, _, _ = build_researcher(tmp_path, pages={}, search=NullSearchProvider())
    updated = researcher.provide(
        an_offer(),
        {"sources": [{"url": "https://acme.test/empty", "title": "", "excerpt": "", "fact_kind": "about"}]},
    )
    assert any("ignorée" in warning for warning in updated.warnings)


# --- 8. HTTP API --------------------------------------------------------------


def build_client(service: CareerService, researcher: WebResearcher) -> TestClient:
    app = FastAPI()
    app.include_router(create_career_router(service, web_researcher=researcher))

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


def synthetic_job(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "company": "Acme Robotics",
        "title": "Robotics Intern",
        "source_name": "manual",
        "official_url": "https://acme.test/jobs/42",
        "city": "Paris",
        "country": "France",
        "description_original": "Build autonomous fleet software.",
    }
    payload.update(updates)
    return payload


def test_api_exposes_research_freshness_and_provide(tmp_path: Path) -> None:
    service = CareerService(tmp_path / "career-data")
    job = service.import_job(synthetic_job())
    researcher, _, _ = build_researcher(tmp_path)
    client = build_client(service, researcher)

    before = client.get(f"/api/career/web/research/{job['id']}/freshness")
    assert before.status_code == 200
    assert before.json()["available"] is False

    research = client.get(f"/api/career/web/research/{job['id']}")
    assert research.status_code == 200
    payload = research.json()
    assert payload["company"] == "Acme Robotics"
    assert "python" in payload["stack"]
    assert payload["evidence_ids"]
    assert all("url" in item and "excerpt" in item for item in payload["evidence"])

    provided = client.post(
        f"/api/career/web/research/{job['id']}/provide",
        json={"notes": "Fiche entreprise vérifiée à la main.", "stack": ["Excel"]},
    )
    assert provided.status_code == 200
    assert provided.json()["stack"][0] == "Excel"
    assert provided.json()["provided_at"]

    after = client.get(f"/api/career/web/research/{job['id']}/freshness")
    assert after.status_code == 200
    assert after.json()["available"] is True
    assert after.json()["provided_at"] == provided.json()["provided_at"]

    alias = client.get(f"/web/research/{job['id']}")
    assert alias.status_code == 200


def test_api_unknown_offer_is_a_user_facing_error(tmp_path: Path) -> None:
    service = CareerService(tmp_path / "career-data")
    researcher, _, _ = build_researcher(tmp_path)
    client = build_client(service, researcher)

    response = client.get("/api/career/web/research/does-not-exist")
    assert response.status_code == 400
