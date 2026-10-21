"""Verification indépendante des 9 critères et des garde-fous de SPEC-SK-06.

Ce script n'appartient pas à la suite de tests : il rejoue les règles de la
mission une par une et affiche une preuve lisible pour chaque point.  Il est
100 % local, déterministe et hors ligne.

Usage :
    .venv/bin/python scripts/verify_sk06_guards.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from career.job_deduplication import (  # noqa: E402
    canonical_company,
    canonicalize_url,
    deduplicate_jobs,
    deduplicate_offers,
    jaro_winkler,
    match_records,
    title_canonical,
    title_concept,
)

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "OK  " if condition else "FAIL"
    print(f"[{mark}] {label}" + (f" -> {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


def offer(**kwargs) -> dict:
    base = {
        "source_name": "greenhouse",
        "source_id": "",
        "company": "Acme",
        "title": "M&A Intern",
        "city": "Paris",
        "country": "France",
        "official_url": "",
    }
    base.update(kwargs)
    return base


print("=" * 78)
print("SPEC-SK-06 — 9 critères de rapprochement")
print("=" * 78)

# 1. Identifiant externe
a = offer(source_name="greenhouse", source_id="4012345", external_id="gh_jid_4012345")
b = offer(source_name="greenhouse", source_id="4012345", external_id="gh_jid_4012345")
decision = match_records(a, b)
check("1. identifiant externe", decision["matches"] and "same_external_id" in decision["reasons"],
      f"reasons={decision['reasons']}")

# 2. URL canonique (paramètres de tracking)
a = offer(official_url="https://www.acme.com/jobs/1?utm_source=linkedin&gclid=x")
b = offer(official_url="http://acme.com/jobs/1/")
check("2. URL canonique", canonicalize_url(a["official_url"]) == canonicalize_url(b["official_url"]),
      canonicalize_url(a["official_url"]))
decision = match_records(a, b)
check("2b. fusion par URL canonique", decision["matches"], f"reasons={decision['reasons']}")

# 3. Entreprise canonique
check("3. entreprise canonique", canonical_company("Acme Corp") == canonical_company("Acme Inc."),
      f"{canonical_company('Acme Corp')} == {canonical_company('Acme Inc.')}")

# 4. Titre canonique (synonymes, casse, bruit)
check("4. titre canonique (synonyme et casse)",
      title_canonical("M&A Intern") == title_canonical("m&a internship")
      and title_canonical("Data Analyst Stage") == title_canonical("Data Analyst Internship"),
      f"{title_canonical('M&A Intern')!r}")

# 5. Lieu
a = offer(city="Paris")
b = offer(city="Lyon")
decision = match_records(a, b)
check("5. lieu (Paris != Lyon)", not decision["matches"] and "city_conflict" in decision["reasons"],
      f"reasons={decision['reasons']}")

# 6. Dates
a = offer(start_date="2025-01-01")
b = offer(start_date="2025-06-01")
decision = match_records(a, b)
check("6. dates incompatibles", not decision["matches"] and "start_date_conflict" in decision["reasons"],
      f"reasons={decision['reasons']}")

# 7. Similarité de texte
score = jaro_winkler("m&a intern", "m&a intern")
check("7. similarité Jaro-Winkler >= 0.92", score >= 0.92, f"score={score:.3f}")

# 8. Traductions
check("8. traduction (concept de rôle)",
      title_concept("Ingénieur logiciel") == title_concept("Software Engineer"),
      f"{title_concept('Ingénieur logiciel')!r}")

# 9. Alias d'entreprise
a = offer(company="Acme Corp")
b = offer(company="Acme Inc.")
decision = match_records(a, b)
check("9. alias d'entreprise", decision["matches"], f"reasons={decision['reasons']}")

print()
print("=" * 78)
print("SPEC-SK-06 — 7 garde-fous non négociables")
print("=" * 78)

# G1. Le score de pertinence utilisateur ne décide jamais
a = offer(source_name="lever", source_id="l1", user_score=100, match_score=100)
b = offer(source_name="greenhouse", source_id="g1", user_score=0, match_score=0)
decision = match_records(a, b)
check("G1. le score utilisateur ne décide jamais", decision["matches"], f"reasons={decision['reasons']}")
offers, report = deduplicate_offers([a, b])
check("G1b. le score ne choisit pas le représentant",
      offers[0].get("source_name") != "lever" or offers[0].get("source_id") != "l1",
      f"représentant={offers[0].get('source_name')}")

# G2. Toutes les provenances sont conservées
records = [
    offer(source_name="greenhouse", source_id="g1", official_url="https://acme.com/jobs/1"),
    offer(source_name="lever", source_id="l1", official_url="https://acme.com/jobs/1"),
    offer(source_name="apec", source_id="a1", official_url="https://acme.com/jobs/1"),
]
groups = deduplicate_jobs(records)
group = groups[0]
check("G2. provenances conservées", len(group["provenances"]) == 3,
      f"provenances={[p['source_name'] for p in group['provenances']]}")
check("G2b. merged_from trace les sources", sorted(group["merged_from"]) == ["apec", "lever"],
      f"merged_from={group['merged_from']}")

# G3. Les contradictions restent visibles
records = [
    offer(source_name="greenhouse", source_id="g1", official_url="https://acme.com/jobs/1", city="Paris"),
    offer(source_name="lever", source_id="l1", official_url="https://acme.com/jobs/1", city="Lyon"),
]
groups = deduplicate_jobs(records)
check("G3. contradictions visibles", "city" in groups[0]["conflicts"],
      f"conflits={list(groups[0]['conflicts'])}")

# G4. La source officielle (SK-01 verified) reste principale
records = [
    offer(source_name="apec", source_id="a1", official_url="https://acme.com/jobs/1",
          source_trust="unverified", title="M&A Intern"),
    offer(source_name="greenhouse", source_id="g1", official_url="https://acme.com/jobs/1",
          source_trust="verified", title="M&A Intern"),
]
offers, report = deduplicate_offers(records)
check("G4. source verified reste principale", offers[0].get("source_name") == "greenhouse",
      f"représentant={offers[0].get('source_name')}")

# G5. Les sources secondaires restent consultables
groups = deduplicate_jobs(records)
check("G5. sources secondaires consultables",
      len(groups[0]["provenances"]) == 2 and groups[0]["sources"] == ["apec", "greenhouse"],
      f"sources={groups[0]['sources']}")

# G6. La traduction ne fusionne pas sur quelques mots communs
a = offer(source_name="greenhouse", source_id="g1", title="Data Analyst")
b = offer(source_name="lever", source_id="l1", title="Data")
decision = match_records(a, b)
check("G6. mots communs ne suffisent pas", not decision["matches"], f"reasons={decision['reasons']}")

# G7. Les rôles différents ne sont jamais fusionnés
a = offer(source_name="greenhouse", source_id="g1", title="Software Engineer")
b = offer(source_name="lever", source_id="l1", title="Product Manager")
decision = match_records(a, b)
check("G7. rôles différents jamais fusionnés", not decision["matches"], f"reasons={decision['reasons']}")
a = offer(source_name="greenhouse", source_id="g1", title="Senior Developer")
b = offer(source_name="lever", source_id="l1", title="Junior Developer")
decision = match_records(a, b)
check("G7b. niveaux différents jamais fusionnés", not decision["matches"], f"reasons={decision['reasons']}")

print()
print("=" * 78)
if FAILURES:
    print(f"{len(FAILURES)} vérification(s) en échec : {FAILURES}")
    sys.exit(1)
print("Toutes les vérifications SPEC-SK-06 sont passées.")
