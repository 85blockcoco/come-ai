from pathlib import Path

from reportlab.pdfgen import canvas

from career.cv_quality import analyze_cv
from career.cv_quality.parser import (
    VisualBlock,
    extract_text_from_file,
    reconstruct_reading_order,
)


def test_reading_order_associates_left_dates_with_right_descriptions() -> None:
    blocks = [
        VisualBlock("EXPERIENCE", 220, 20, 300, 32),
        VisualBlock("Jan 2022 - Jun 2022", 30, 60, 125, 72),
        VisualBlock("Analyst | Bank A", 220, 60, 330, 72),
        VisualBlock("- Automated 500+ files", 220, 78, 380, 90),
        VisualBlock("Jan 2021 - Jun 2021", 30, 120, 125, 132),
        VisualBlock("Intern | Bank B", 220, 120, 330, 132),
    ]

    text = reconstruct_reading_order(blocks)

    assert "Jan 2022 - Jun 2022 | Analyst | Bank A" in text
    assert text.index("Bank A") < text.index("Bank B")


def _make_two_column_cv(path: Path) -> None:
    pdf = canvas.Canvas(str(path), pagesize=(595, 842))
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(220, 810, "EXPERIENCE")
    y = 770
    for index in range(5):
        pdf.setFont("Helvetica", 9)
        pdf.drawString(30, y, f"Jan 202{index} - Jun 202{index}")
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(220, y, f"Analyst {index} | Synthetic Bank {index}")
        pdf.setFont("Helvetica", 9)
        pdf.drawString(220, y - 15, f"- Automated {100 + index}+ files and reduced time by 8{index}%")
        pdf.drawString(220, y - 28, f"- Reviewed {20 + index} reports over 6 months")
        y -= 90
    for heading, value in (
        ("EDUCATION", "MSc Finance 2026"),
        ("SKILLS", "Python, Excel, SQL"),
        ("LANGUAGES", "French, English"),
        ("PROJECTS", "Quant project 1000 observations"),
        ("CERTIFICATIONS", "CFA mock certification"),
    ):
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(30, y, heading)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(220, y, value)
        y -= 35
    pdf.save()


def test_two_column_canva_equivalent_detects_at_least_four_experiences(
    tmp_path: Path,
) -> None:
    path = tmp_path / "two-column.pdf"
    _make_two_column_cv(path)

    document = extract_text_from_file(path)
    analysis = analyze_cv(document)

    assert len(analysis.experiences) >= 4
    assert all(item.start_date for item in analysis.experiences[:4])
    assert sum(item.has_quantified_result for item in analysis.experiences) >= 4
    codes = {finding.code for finding in analysis.findings}
    assert "TABLE_DETECTED" not in codes
    assert "MISSING_SECTION" not in codes


def _make_floating_boxes_cv(path: Path) -> None:
    pdf = canvas.Canvas(str(path), pagesize=(595, 842))
    # Draw deliberately out of logical order, as Canva text boxes often are.
    for index in reversed(range(4)):
        y = 760 - index * 105
        pdf.setFont("Helvetica", 9)
        pdf.drawString(230, y - 18, f"- Processed {200 + index}+ records with {70 + index}% improvement")
        pdf.drawString(25, y, f"Feb 202{index} - Aug 202{index}")
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(230, y, f"Associate {index} | Floating Co {index}")
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(230, 805, "EXPERIENCE")
    y = 310
    for heading, value in (
        ("EDUCATION", "MSc Finance 2026"),
        ("SKILLS", "Python Excel"),
        ("LANGUAGES", "French English"),
        ("PROJECTS", "Model tested on 1000 rows"),
        ("CERTIFICATIONS", "Certificate 2025"),
    ):
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(25, y, heading)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(230, y, value)
        y -= 32
    pdf.save()


def _make_multi_page_cv(path: Path) -> None:
    pdf = canvas.Canvas(str(path), pagesize=(595, 842))
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(210, 805, "EXPERIENCE")
    for index, y in enumerate((750, 600)):
        pdf.setFont("Helvetica", 9)
        pdf.drawString(25, y, f"Mar 202{index} - Sep 202{index}")
        pdf.drawString(210, y, f"Analyst {index} | Multi Co {index}")
        pdf.drawString(210, y - 18, f"- Reviewed {300 + index}+ items and improved quality by 6{index}%")
    pdf.showPage()
    for index, y in ((2, 780), (3, 630)):
        pdf.setFont("Helvetica", 9)
        pdf.drawString(25, y, f"Mar 202{index} - Sep 202{index}")
        pdf.drawString(210, y, f"Analyst {index} | Multi Co {index}")
        pdf.drawString(210, y - 18, f"- Reviewed {300 + index}+ items and improved quality by 6{index}%")
    y = 430
    for heading, value in (
        ("EDUCATION", "MSc Finance 2026"),
        ("SKILLS", "Python Excel"),
        ("LANGUAGES", "French English"),
        ("PROJECTS", "Project with 900 observations"),
        ("CERTIFICATIONS", "Certificate 2025"),
    ):
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(25, y, heading)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(210, y, value)
        y -= 32
    pdf.save()


def test_floating_text_boxes_are_grouped_by_visual_position(tmp_path: Path) -> None:
    path = tmp_path / "floating-boxes.pdf"
    _make_floating_boxes_cv(path)
    analysis = analyze_cv(extract_text_from_file(path))
    assert len(analysis.experiences) >= 4
    assert sum(item.has_quantified_result for item in analysis.experiences) >= 4


def test_multi_page_experiences_keep_logical_order(tmp_path: Path) -> None:
    path = tmp_path / "multi-page.pdf"
    _make_multi_page_cv(path)
    analysis = analyze_cv(extract_text_from_file(path))
    assert len(analysis.experiences) >= 4
    assert [item.start_date for item in analysis.experiences[:4]] == [
        "Mar 2020",
        "Mar 2021",
        "Mar 2022",
        "Mar 2023",
    ]


def test_experience_continuation_at_next_page_stays_with_the_same_entry(tmp_path: Path) -> None:
    path = tmp_path / "split-experience.pdf"
    pdf = canvas.Canvas(str(path), pagesize=(595, 842))
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(220, 805, "EXPERIENCE")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(25, 760, "Jan 2024 - Jun 2024")
    pdf.drawString(220, 760, "Analyst | Split Synthetic Bank")
    pdf.drawString(220, 742, "- Built a portfolio reporting model for 30 companies")
    pdf.showPage()
    pdf.setFont("Helvetica", 9)
    pdf.drawString(220, 805, "which reduced review time by 20% across the team.")
    pdf.drawString(25, 755, "Jul 2023 - Dec 2023")
    pdf.drawString(220, 755, "Intern | Previous Synthetic Bank")
    pdf.drawString(220, 737, "- Reconciled 500 transactions and corrected 12 records")
    pdf.save()

    analysis = analyze_cv(extract_text_from_file(path))

    assert len(analysis.experiences) == 2
    first, second = analysis.experiences
    assert first.company == "Split Synthetic Bank"
    assert "reduced review time by 20%" in first.description
    assert second.company == "Previous Synthetic Bank"
