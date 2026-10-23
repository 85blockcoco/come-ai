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
    {
        "id": "registry:greenhouse:mangroup", "provider": "greenhouse", "company": "Man Group",
        "board_token": "mangroup", "public_url": "https://job-boards.greenhouse.io/mangroup",
        "provenance_url": "https://www.man.com/careers",
        "verified_at": "2026-10-18T10:14:39+00:00",
    },
    {
        "id": "registry:greenhouse:aqr", "provider": "greenhouse", "company": "AQR",
        "board_token": "aqr", "public_url": "https://job-boards.greenhouse.io/aqr",
        "provenance_url": "https://careers.aqr.com/",
        "verified_at": "2026-10-18T10:14:39+00:00",
    },
    {
        "id": "registry:greenhouse:robinhood", "provider": "greenhouse", "company": "Robinhood",
        "board_token": "robinhood", "public_url": "https://job-boards.greenhouse.io/robinhood",
        "provenance_url": "https://careers.robinhood.com/",
        "verified_at": "2026-10-18T10:14:39+00:00",
    },
    {
        "id": "registry:greenhouse:generalatlantic", "provider": "greenhouse", "company": "General Atlantic",
        "board_token": "generalatlantic", "public_url": "https://job-boards.greenhouse.io/generalatlantic",
        "provenance_url": "https://www.generalatlantic.com/careers/",
        "verified_at": "2026-10-18T10:14:39+00:00",
    },
    {
        "id": "registry:lever:qonto", "provider": "lever", "company": "Qonto",
        "board_token": "qonto", "public_url": "https://jobs.lever.co/qonto",
        "provenance_url": "https://qonto.com/fr/careers",
        "verified_at": "2026-10-18T10:14:39+00:00",
    },
    {
        "id": "registry:greenhouse:doctolib", "provider": "greenhouse", "company": "Doctolib",
        "board_token": "doctolib", "public_url": "https://job-boards.greenhouse.io/doctolib",
        "provenance_url": "https://careers.doctolib.com/jobs/",
        "verified_at": "2026-10-18T12:41:15+00:00",
    },
    {
        "id": "registry:lever:pigment", "provider": "lever", "company": "Pigment",
        "board_token": "pigment", "public_url": "https://jobs.lever.co/pigment",
        "provenance_url": "https://www.pigment.com/careers",
        "verified_at": "2026-10-18T12:41:15+00:00",
    },
    {
        "id": "registry:ashby:oaknorth", "provider": "ashby", "company": "OakNorth",
        "board_token": "oaknorth", "public_url": "https://jobs.ashbyhq.com/oaknorth",
        "provenance_url": "https://www.oaknorth.com/careers/",
        "verified_at": "2026-10-18T12:41:15+00:00",
    },
    {
        "id": "registry:greenhouse:monzo", "provider": "greenhouse", "company": "Monzo",
        "board_token": "monzo", "public_url": "https://boards.greenhouse.io/monzo",
        "provenance_url": "https://monzo.com/careers/",
        "verified_at": "2026-10-18T12:41:15+00:00",
    },
    {
        "id": "registry:ashby:thought-machine", "provider": "ashby", "company": "Thought Machine",
        "board_token": "thought-machine", "public_url": "https://jobs.ashbyhq.com/thought-machine",
        "provenance_url": "https://www.thoughtmachine.net/careers",
        "verified_at": "2026-10-18T12:41:15+00:00",
    },
    {
        "id": "registry:ashby:alan", "provider": "ashby", "company": "Alan",
        "board_token": "alan", "public_url": "https://jobs.ashbyhq.com/alan",
        "provenance_url": "https://alan.com/careers",
        "verified_at": "2026-10-18T12:41:15+00:00",
    },
    {
        "id": "registry:lever:contentsquare", "provider": "lever", "company": "Contentsquare",
        "board_token": "contentsquare", "public_url": "https://jobs.lever.co/contentsquare",
        "provenance_url": "https://contentsquare.com/careers/",
        "verified_at": "2026-10-18T12:41:15+00:00",
    },
    {
        "id": "registry:greenhouse:dataiku", "provider": "greenhouse", "company": "Dataiku",
        "board_token": "dataiku", "public_url": "https://job-boards.greenhouse.io/dataiku",
        "provenance_url": "https://www.dataiku.com/careers/",
        "verified_at": "2026-10-18T12:41:15+00:00",
    },
    # New sources added for CVBOOST-06 (verified 2026-10-20)
    {
        "id": "registry:welcome_jungle:finance_internships", "provider": "welcome_jungle", "company": "Welcome to the Jungle",
        "board_token": "finance-internships-europe", "public_url": "https://www.welcometothejungle.com/fr/jobs?query=stage%20finance&refinementList%5Boffice.country_code%5D%5B%5D=GB&refinementList%5Boffice.country_code%5D%5B%5D=DE&refinementList%5Boffice.country_code%5D%5B%5D=NL&refinementList%5Boffice.country_code%5D%5B%5D=BE&refinementList%5Boffice.country_code%5D%5B%5D=LU&refinementList%5Boffice.country_code%5D%5B%5D=CH&refinementList%5Boffice.country_code%5D%5B%5D=IE&refinementList%5Boffice.country_code%5D%5B%5D=ES&refinementList%5Boffice.country_code%5D%5B%5D=IT&refinementList%5Boffice.country_code%5D%5B%5D=PT",
        "provenance_url": "https://www.welcometothejungle.com/fr/jobs",
        "verified_at": "2026-10-20T00:00:00+00:00",
    },
    {
        "id": "registry:jobteaser:finance_internships", "provider": "jobteaser", "company": "JobTeaser",
        "board_token": "finance-internships-europe", "public_url": "https://www.jobteaser.com/en/jobs?query=finance%20internship&contract_type=internship&countries%5B%5D=GB&countries%5B%5D=DE&countries%5B%5D=NL&countries%5B%5D=BE&countries%5B%5D=LU&countries%5B%5D=CH&countries%5B%5D=IE&countries%5B%5D=ES&countries%5B%5D=IT&countries%5B%5D=PT",
        "provenance_url": "https://www.jobteaser.com/en/jobs",
        "verified_at": "2026-10-20T00:00:00+00:00",
    },
    {
        "id": "registry:talent_com:finance_internships", "provider": "talent_com", "company": "Talent.com",
        "board_token": "finance-internships-europe", "public_url": "https://www.talent.com/jobs?k=finance%20internship&l=Europe&contract=internship",
        "provenance_url": "https://www.talent.com",
        "verified_at": "2026-10-20T00:00:00+00:00",
    },
    {
        "id": "registry:apec:finance_internships", "provider": "apec", "company": "APEC",
        "board_token": "finance-internships-international", "public_url": "https://www.apec.fr/candidat/recherche-emploi.html?motsCles=stage%20finance&typeContrat=STAGE&secteurActivite=BANQUE_ASSURANCE_FINANCE&region=INTERNATIONAL",
        "provenance_url": "https://www.apec.fr",
        "verified_at": "2026-10-20T00:00:00+00:00",
    },
    {
        "id": "registry:recruitee:bunq", "provider": "recruitee", "company": "bunq",
        "board_token": "bunq", "public_url": "https://careers.bunq.com/",
        "provenance_url": "https://www.bunq.com/careers",
        "conditions": "Flux public Recruitee sans clé ; photographie temporelle sans promesse.",
        "verified_at": "2026-10-20T10:30:00+00:00",
    },
    {
        "id": "registry:smartrecruiters:experian", "provider": "smartrecruiters", "company": "Experian",
        "company_identifier": "Experian", "public_url": "https://jobs.smartrecruiters.com/Experian",
        "provenance_url": "https://jobs.experian.com/",
        "conditions": "API posting publique sans clé ; pagination bornée côté client.",
        "verified_at": "2026-10-20T10:30:00+00:00",
    },
)
