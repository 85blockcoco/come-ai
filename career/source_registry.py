"""Versioned public-source evidence; inert on import, no private preferences.

Only sources identified from an official employer page and actually fetched
may enter this registry. The verification is historical evidence, not a promise
that a source will always remain available. Runtime exploration reports its
own success, failure and consultation time.
"""
from __future__ import annotations

# Filled only with evidence from bounded public-source qualification.
CURATED_SOURCES: tuple[dict[str, str], ...] = (
    {
        "id": "registry:greenhouse:lincolninternational", "provider": "greenhouse", "company": "Lincoln International",
        "board_token": "lincolninternational", "public_url": "https://job-boards.greenhouse.io/lincolninternational",
        "provenance_url": "https://www.lincolninternational.com/careers-and-culture/careers/campus-early-careers/",
        "verified_at": "2026-10-14T08:33:28.564290+00:00",
    },
    {
        "id": "registry:greenhouse:alixpartners", "provider": "greenhouse", "company": "AlixPartners",
        "board_token": "alixpartners", "public_url": "https://job-boards.greenhouse.io/alixpartners",
        "provenance_url": "https://www.alixpartners.com/careers/apply-now/?gh_jid=7810004003",
        "verified_at": "2026-10-14T08:33:29.254479+00:00",
    },
    {
        "id": "registry:greenhouse:schonfeld", "provider": "greenhouse", "company": "Schonfeld",
        "board_token": "schonfeld", "public_url": "https://job-boards.greenhouse.io/schonfeld",
        "provenance_url": "https://www.schonfeld.com/careers/",
        "verified_at": "2026-10-13T22:06:00.294468+00:00",
    },
    {
        "id": "registry:greenhouse:point72", "provider": "greenhouse", "company": "Point72",
        "board_token": "point72", "public_url": "https://job-boards.greenhouse.io/point72",
        "provenance_url": "https://careers.point72.com/",
        "verified_at": "2026-10-13T22:06:01.434039+00:00",
    },
    {
        "id": "registry:greenhouse:quberesearchandtechnologies", "provider": "greenhouse",
        "company": "Qube Research & Technologies", "board_token": "quberesearchandtechnologies",
        "public_url": "https://job-boards.greenhouse.io/quberesearchandtechnologies",
        "provenance_url": "https://www.qube-rt.com/careers/",
        "verified_at": "2026-10-13T22:08:35.723249+00:00",
    },
    {
        "id": "registry:greenhouse:flowtraders", "provider": "greenhouse", "company": "Flow Traders",
        "board_token": "flowtraders", "public_url": "https://job-boards.greenhouse.io/flowtraders",
        "provenance_url": "https://www.flowtraders.com/careers/job-search/",
        "verified_at": "2026-10-13T22:08:34.591648+00:00",
    },
    {
        "id": "registry:greenhouse:xtxmarketstechnologies", "provider": "greenhouse", "company": "XTX Markets",
        "board_token": "xtxmarketstechnologies", "public_url": "https://job-boards.greenhouse.io/xtxmarketstechnologies",
        "provenance_url": "https://www.xtxmarkets.com/careers/",
        "verified_at": "2026-10-13T22:08:00.802790+00:00",
    },
    {
        "id": "registry:greenhouse:optiverus", "provider": "greenhouse", "company": "Optiver",
        "board_token": "optiverus", "public_url": "https://job-boards.greenhouse.io/optiverus",
        "provenance_url": "https://www.optiver.com/join-us/jobs/risk-finance-and-legal/singapore/market-risk-internship-2027-singapore/apply",
        "verified_at": "2026-10-13T22:10:48.919382+00:00",
    },
)
