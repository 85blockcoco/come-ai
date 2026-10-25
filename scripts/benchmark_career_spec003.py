"""Reproducible, offline performance checks for Career Spec 003.

All offers, profile facts and PDF contents are synthetic. The benchmark uses a
temporary Career database and never contacts public boards or model providers.
Run with ``python scripts/benchmark_career_spec003.py``; add ``--strict`` to
return a failure status when any target is missed.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

# Executing this file by path puts `scripts/` rather than the repository root
# at sys.path[0]; make its imports work from any current directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from career.cv_quality import analyze_cv
from career.cv_quality.parser import extract_text_from_file
from career.service import CareerService
from come_ai_web import create_app


PROFILE = {
    "display_name": "Alex Example",
    "education": "MSc Finance, Example University, 2024–2026",
    "experience": (
        "2023 | Analyst | Synthetic Bank — Automated 500+ reports, reducing time by 30%.\n"
        "2022 | Intern | Example Capital — Reviewed 120 valuations with 25% fewer errors.\n"
        "2021 | Assistant | Example Fund — Processed 80 cases over six months.\n"
        "2020 | Treasurer | Example Society — Managed a EUR 15k budget for 12 months."
    ),
    "skills": "Excel, Python, financial modelling, valuation",
    "languages": "English C1, French B2",
}


def _offer(index: int) -> dict[str, object]:
    return {
        "company": f"Synthetic Bank {index:03}",
        "title": "Corporate Finance Intern",
        "job_family": "Corporate Finance",
        "official_url": f"https://jobs.example.test/spec003/{index}",
        "city": "London",
        "country": "United Kingdom",
        "employment_type": "Internship",
        "start_date": "2027-01-04",
        "end_date": "2027-07-04",
        "duration_months": 6,
        "requirements": "Financial modelling and valuation",
        "languages_required": "English",
        "source_status": "open",
    }


def _write_synthetic_pdf(path: Path) -> None:
    pdf = canvas.Canvas(str(path), pagesize=(595, 842))
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(220, 810, "EXPERIENCE")
    y = 770
    for index in range(4):
        pdf.setFont("Helvetica", 9)
        pdf.drawString(30, y, f"Jan 202{index} - Jun 202{index}")
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(220, y, f"Analyst {index} | Synthetic Bank {index}")
        pdf.setFont("Helvetica", 9)
        pdf.drawString(
            220,
            y - 15,
            f"- Automated {100 + index}+ reports and improved time by {20 + index}%",
        )
        y -= 90
    for heading, value in (
        ("EDUCATION", "MSc Finance 2026"),
        ("SKILLS", "Python, Excel, valuation"),
        ("PROJECTS", "Valuation project covering 500 companies"),
        ("CERTIFICATIONS", "Finance certificate 2025"),
        ("LANGUAGES", "English C1, French B2"),
    ):
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(30, y, heading)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(220, y, value)
        y -= 35
    pdf.save()


def _median_ms(action, repeats: int) -> tuple[float, list[float]]:
    samples: list[float] = []
    for _ in range(repeats):
        started = perf_counter()
        action()
        samples.append((perf_counter() - started) * 1000)
    return median(samples), samples


def _report(name: str, samples: list[float], target_ms: float) -> bool:
    value = median(samples)
    result = "PASS" if value < target_ms else "MISS"
    print(f"{name}: median={value:.1f} ms; runs={[round(sample, 1) for sample in samples]}; target<{target_ms:.0f} ms; {result}")
    return result == "PASS"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if any measured target is missed",
    )
    args = parser.parse_args()

    with TemporaryDirectory(prefix="come-career-spec003-benchmark-") as temporary:
        root = Path(temporary)
        service = CareerService(root, curated_sources=())
        service.update_profile(PROFILE)
        service.update_stage_search(service.get_stage_search()["brief"])

        jobs = [service.import_job(_offer(index)) for index in range(50)]
        kit_samples: list[float] = []
        for _ in range(3):
            started = perf_counter()
            service.create_application_kit(jobs[0]["id"], "en", "corporate_finance")
            kit_samples.append((perf_counter() - started) * 1000)

        with TestClient(create_app(base_dir=root, career_override=service)) as client:
            pipeline_samples: list[float] = []
            for _ in range(7):
                started = perf_counter()
                response = client.get("/api/career/application-pipeline")
                pipeline_samples.append((perf_counter() - started) * 1000)
                if response.status_code != 200:
                    raise RuntimeError(f"Pipeline API returned HTTP {response.status_code}")
            if len(response.json().get("pipeline", [])) != 50:
                raise RuntimeError("Pipeline benchmark did not return 50 synthetic offers")

        jobs.extend(service.import_job(_offer(index)) for index in range(50, 150))
        sprint_samples: list[float] = []
        sprint_result = None
        for _ in range(3):
            started = perf_counter()
            sprint_result = service.get_application_sprint(limit=30)
            sprint_samples.append((perf_counter() - started) * 1000)
        if sprint_result is None or len(sprint_result["queue"]) != 30:
            raise RuntimeError("Sprint benchmark did not build a 30-offer queue")

        pdf = root / "synthetic-career-cv.pdf"
        _write_synthetic_pdf(pdf)
        pdf_samples: list[float] = []
        analysis = None
        for _ in range(7):
            started = perf_counter()
            document = extract_text_from_file(pdf)
            analysis = analyze_cv(document)
            pdf_samples.append((perf_counter() - started) * 1000)
        if analysis is None:
            raise RuntimeError("Synthetic PDF was not analyzed")

        print("Synthetic data only; no network or model provider used.")
        passed = [
            _report("sprint (150 candidates)", sprint_samples, 500),
            _report("application kit", kit_samples, 2_000),
            _report("pipeline API (50 offers)", pipeline_samples, 200),
            _report("PDF text extraction + CV analysis", pdf_samples, 3_000),
        ]
        print(f"PDF experience entries detected: {len(analysis.experiences)}")
        return 1 if args.strict and not all(passed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
