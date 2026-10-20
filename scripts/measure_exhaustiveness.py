#!/usr/bin/env python3
"""Mesure d'exhaustivité des résumés d'offres — garde-fou CI.

Calcule, pour chaque offre stockée en base, le taux de champs renseignés
dans le résumé local (produit `application_prep.summarize_offer`) vs ce qui
est disponible sur la page originale (description_original). Un seuil minimal
est imposé : tout lot qui fait baisser le taux global échoue la CI.

Champs mesurés (7) : dates, contrat, lieu, études, rémunération, missions, conditions.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

# ----- Regex de détection "sur la page" (lexique large, sans inventer) -----

MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|"
    "spring|summer|fall|autumn|winter"
)

DATE_RANGE_RE = re.compile(
    rf"\b(?:{MONTHS})\b\s+20\d{{2}}\s*[-–—]\s*(?:{MONTHS})\b\s+20\d{{2}}", re.I
)
START_KW_RE = re.compile(
    rf"(?:start(?:ing|s)?|begin(?:s|ning)?|d[ée]but|commenc\w*|from|as soon as possible)\s*[:\\-]?\s*(?:(?:in|from|on|en|de|du|le)\s+)?(?:{MONTHS})\b", re.I
)
DURATION_BROAD_RE = re.compile(
    r"\b\d{1,2}\s*(?:[-–]\s*\d{1,2}\s*)?(?:weeks?|semesters?|quarters?|mois|semestres?|trimestres?)\b", re.I
)
DEADLINE_RE = re.compile(
    r"(?:apply by|deadline|applications?\s+close|closing\s+date|date\s+limite|submit\s+(?:your\s+)?application\s+(?:by|before)|applications?\s+open\s+until)", re.I
)
EDU_RE = re.compile(
    r"\b(?:master(?:'s)?|mba|bachelor(?:'s)?|bsc|msc|ph\.?d|phd|doctorate|undergraduate|graduate\s+(?:degree|programme|program)?|business\s+school|engineering\s+degree|university\s+degree|dipl[oô]me|licence|master\s+of\s+science|bachelor\s+of\s+science|[ée]cole\s+de\s+commerce|cfa|student\s+in|enrolled\s+in|[ée]tudiant\s+en)\b", re.I
)
REM_RE = re.compile(
    r"(?:(?:salary|salaries|compensation|r[ée]mun[ée]ration|base\s+pay|pay\s+range|salary\s+range|salaire)\b|(?:\s?(?:€|\$|£|¥))|(?:\b\d{1,3}(?:[,\s]\d{3})*\s*(?:k|K)?\s*(?:€|\$|£|¥)))", re.I
)
MIS_RE = re.compile(
    r"^\s*(?:[-–—*•\d.\s]{0,12})(?P<h>your\s+mission|what\s+you(?:'ll|’ll|\s+will)\s+(?:do|be\s+doing)|missions?|responsibilities|principales\s+missions|responsabilit[ée]s|t[âa]ches?\s+principales|your\s+responsibilities|about\s+the\s+role|role\s+description|your\s+tasks)\s*[:\\-–]?\s*$", re.I | re.M
)
COND_RE = re.compile(
    r"(?:what\s+we\s+(?:offer|can\s+offer|provide)|our\s+(?:offer|benefits|perks)|(?<!cost[/-])\bbenefits\b|\bperks?\b|why\s+(?:you\s+should|should\s+you|join)|working\s+(?:hours|schedule)|conditions?\s+of\s+employment|t[ée]l[ée]travail|remote\s+work|work\s+from\s+home|hybrid\s+work|flexible\s+hours)", re.I
)
HTML_RE = re.compile(r"</?(?:p|li|ul|ol|div|br|strong|em|h[1-6]|span|table|tr|td|b|i)\b|&nbsp;|&|&#\d+;", re.I)


def field_present_in_fiche(summary: dict[str, Any], field: str) -> bool:
    """Le champ est-il renseigné dans le résumé produit par l'app ?"""
    if field == "dates":
        return bool(summary.get("start_month") or summary.get("duration_min_months"))
    if field == "contrat":
        return summary.get("contract_type", "unknown") != "unknown"
    if field == "lieu":
        return bool(summary.get("city") and summary.get("country"))
    if field == "etudes":
        return bool(summary.get("education_level"))
    if field == "remuneration":
        return bool(summary.get("remuneration"))
    if field == "missions":
        return bool(summary.get("missions"))
    if field == "conditions":
        return bool(summary.get("conditions"))
    return False


def field_present_on_page(job: dict[str, Any], field: str) -> bool:
    """Le champ est-il détectable dans la description originale ?"""
    desc = job.get("description_original") or ""
    if field == "dates":
        return (
            bool(job.get("posted_date") or job.get("start_date") or job.get("end_date") or job.get("deadline_date") or job.get("duration_months"))
            or bool(DATE_RANGE_RE.search(desc))
            or bool(START_KW_RE.search(desc))
        )
    if field == "contrat":
        return bool(job.get("employment_type", "").strip())
    if field == "lieu":
        city = job.get("city") or ""
        country = job.get("country") or ""
        return bool(city) and bool(country) and country in city
    if field == "etudes":
        return bool(EDU_RE.search(desc))
    if field == "remuneration":
        return bool(REM_RE.search(desc))
    if field == "missions":
        return bool(MIS_RE.search(desc))
    if field == "conditions":
        return bool(COND_RE.search(desc))
    if field == "html_residual":
        return bool(HTML_RE.search(desc))
    return False


def load_jobs(db_path: Path) -> list[dict[str, Any]]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    jobs = [dict(r) for r in con.execute("SELECT * FROM jobs")]
    con.close()
    return jobs


def import_summarize():
    """Import dynamique de application_prep.summarize_offer depuis le repo."""
    import importlib.util
    import types
    ROOT = Path(__file__).resolve().parent.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    pkg = types.ModuleType("careerpkg")
    pkg.__path__ = [str(ROOT / "career")]
    sys.modules["careerpkg"] = pkg
    spec = importlib.util.spec_from_file_location("careerpkg.application_prep", ROOT / "career" / "application_prep.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["careerpkg.application_prep"] = mod
    spec.loader.exec_module(mod)
    return mod.summarize_offer


def measure(db_path: Path, threshold: float = 55.0) -> dict[str, Any]:
    jobs = load_jobs(db_path)
    summarize = import_summarize()

    FIELDS = ["dates", "contrat", "lieu", "etudes", "remuneration", "missions", "conditions"]
    N = len(jobs)
    if N == 0:
        return {"error": "Aucune offre en base", "threshold": threshold}

    stats = {f: {"fiche": 0, "page": 0, "missing_on_fiche": []} for f in FIELDS}

    for job in jobs:
        summary = summarize(job)
        for f in FIELDS:
            in_fiche = field_present_in_fiche(summary, f)
            on_page = field_present_on_page(job, f)
            if in_fiche:
                stats[f]["fiche"] += 1
            if on_page:
                stats[f]["page"] += 1
            if not in_fiche:
                stats[f]["missing_on_fiche"].append({
                    "id": job["id"],
                    "company": job["company"],
                    "title": job["title"],
                    "on_page": on_page,
                })

    # Scores
    per_field = {}
    for f in FIELDS:
        fiche_pct = 100 * stats[f]["fiche"] / N
        page_pct = 100 * stats[f]["page"] / N
        per_field[f] = {"fiche_pct": round(fiche_pct, 1), "page_pct": round(page_pct, 1)}

    total_fiche = sum(s["fiche"] for s in stats.values())
    total_page = sum(s["page"] for s in stats.values())
    global_fiche_pct = round(100 * total_fiche / (7 * N), 1)
    global_page_pct = round(100 * total_page / (7 * N), 1)
    gap = round(global_page_pct - global_fiche_pct, 1)

    # Top 3 pires / meilleures (score fiche sur 7)
    scored = []
    for job in jobs:
        s = summarize(job)
        score = sum(1 for f in FIELDS if field_present_in_fiche(s, f))
        scored.append({"job": job, "score": score, "page_score": sum(1 for f in FIELDS if field_present_on_page(job, f))})
    worst = sorted(scored, key=lambda x: (x["score"], x["page_score"], len(job.get("description_original") or "")))[:3]
    best = sorted(scored, key=lambda x: (-x["score"], -x["page_score"], -len(job.get("description_original") or "")))[:3]

    passed = global_fiche_pct >= threshold
    return {
        "N_offres": N,
        "global": {"fiche_pct": global_fiche_pct, "page_pct": global_page_pct, "gap": gap},
        "per_field": per_field,
        "worst_offers": [{"company": x["job"]["company"], "title": x["job"]["title"], "score": x["score"], "missing": [f for f in FIELDS if not field_present_in_fiche(summarize(x["job"]), f)]} for x in worst],
        "best_offers": [{"company": x["job"]["company"], "title": x["job"]["title"], "score": x["score"]} for x in best],
        "threshold": threshold,
        "passed": passed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mesure d'exhaustivité des résumés d'offres (garde-fou CI).")
    parser.add_argument("--db", default="career_data/career.sqlite3", help="Chemin vers la base Career.")
    parser.add_argument("--threshold", type=float, default=55.0, help="Seuil minimal global fiche % (défaut 55%).")
    parser.add_argument("--output", help="Écrire le rapport JSON dans ce fichier.")
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve()
    if not db_path.is_file():
        print(f"Base introuvable : {db_path}", file=sys.stderr)
        return 2

    report = measure(db_path, args.threshold)
    if "error" in report:
        print(report["error"], file=sys.stderr)
        return 2

    # Sortie console lisible
    g = report["global"]
    print(f"\n{'Champ':20} {'Fiche':>7} {'Page':>7}  Gap")
    for f, v in report["per_field"].items():
        gap_f = round(v["page_pct"] - v["fiche_pct"], 1)
        print(f"{f:20} {v['fiche_pct']:6.1f}% {v['page_pct']:6.1f}%  {gap_f:+.1f}")
    print(f"\nGLOBAL : fiche {g['fiche_pct']:.1f}%  | page {g['page_pct']:.1f}%  | gap {g['gap']:+.1f} pts  | seuil {report['threshold']:.1f}%  -> {'PASS' if report['passed'] else 'FAIL'}")
    print("\n3 PIRES :")
    for x in report["worst_offers"]:
        print(f"  {x['company']} — {x['title']}  (score {x['score']}/7, manque : {', '.join(x['missing'])})")
    print("\n3 MEILLEURES :")
    for x in report["best_offers"]:
        print(f"  {x['company']} — {x['title']}  (score {x['score']}/7)")

    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())