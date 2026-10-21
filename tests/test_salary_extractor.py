"""Unit tests for the salary extractor (Mission CVBOOST-16).

All fixtures are synthetic — no real job offer, no personal data.
The extractor is a pure function: deterministic, offline, no LLM.
"""

from __future__ import annotations

import time

import pytest

from career.cv_quality import extract_salary, SalaryEvidence
from career.cv_quality.parser import _parse_number


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def one(text: str) -> SalaryEvidence:
    """Return the single mention of a text (fails when there is not exactly one)."""
    evidences = extract_salary(text)
    assert len(evidences) == 1, f"expected 1 evidence for {text!r}, got {len(evidences)}"
    return evidences[0]


# ──────────────────────────────────────────────────────────────────────
# Amounts — currencies, scales, ranges
# ──────────────────────────────────────────────────────────────────────

def test_salary_simple_eur():
    ev = one("45 000 € brut annuel")
    assert ev.min_annual_eur == 45000
    assert ev.max_annual_eur == 45000
    assert ev.currency == "EUR"
    assert ev.periodicity == "annual"


def test_salary_k_eur():
    ev = one("55k€")
    assert ev.min_annual_eur == 55000
    assert ev.max_annual_eur == 55000
    assert ev.currency == "EUR"


def test_salary_k_uppercase():
    ev = one("55K€")
    assert ev.min_annual_eur == 55000
    assert ev.currency == "EUR"


def test_salary_range():
    ev = one("45-55k€")
    assert ev.min_annual_eur == 45000
    assert ev.max_annual_eur == 55000
    assert ev.currency == "EUR"


def test_salary_range_spaces():
    ev = one("50 k - 60 k €")
    assert ev.min_annual_eur == 50000
    assert ev.max_annual_eur == 60000
    assert ev.currency == "EUR"


def test_salary_range_en_dash():
    ev = one("40k–60k")
    assert ev.min_annual_eur == 40000
    assert ev.max_annual_eur == 60000


def test_salary_usd():
    ev = one("$80,000 per year")
    assert ev.min_annual_eur == 80000
    assert ev.max_annual_eur == 80000
    assert ev.currency == "USD"
    assert ev.periodicity == "annual"


def test_salary_gbp():
    ev = one("£45,000 per annum")
    assert ev.min_annual_eur == 45000
    assert ev.max_annual_eur == 45000
    assert ev.currency == "GBP"
    assert ev.periodicity == "annual"


def test_salary_jpy():
    ev = one("¥6,000,000 per year")
    assert ev.min_annual_eur == 6000000
    assert ev.currency == "JPY"


def test_salary_monthly_annualised():
    ev = one("4 500 € mensuel")
    assert ev.min_annual_eur == 54000
    assert ev.max_annual_eur == 54000
    assert ev.periodicity == "monthly"


def test_salary_monthly_slash():
    ev = one("1 500 € / mois")
    assert ev.min_annual_eur == 18000
    assert ev.periodicity == "monthly"


def test_salary_hourly_annualised():
    ev = one("Per hour $50")
    assert ev.min_annual_eur == 50 * 1820
    assert ev.periodicity == "hourly"


def test_salary_k():
    ev = one("50k")
    assert ev.min_annual_eur == 50000
    assert ev.max_annual_eur == 50000


def test_salary_m_suffix():
    ev = one("1.5M€")
    assert ev.min_annual_eur == 1_500_000
    assert ev.currency == "EUR"


def test_salary_currency_before_amount():
    ev = one("€45 000 brut annuel")
    assert ev.min_annual_eur == 45000
    assert ev.currency == "EUR"


def test_salary_currency_code_after():
    ev = one("45.000 EUR par an")
    assert ev.min_annual_eur == 45000
    assert ev.currency == "EUR"
    assert ev.periodicity == "annual"


def test_salary_euros_word():
    ev = one("Le salaire est de 45 000 euros par an.")
    assert ev.min_annual_eur == 45000
    assert ev.currency == "EUR"
    assert ev.periodicity == "annual"


def test_salary_non_breaking_space():
    ev = one("45 000 € brut annuel")
    assert ev.min_annual_eur == 45000
    assert ev.currency == "EUR"


# ──────────────────────────────────────────────────────────────────────
# Ranges — FR / EN expressions
# ──────────────────────────────────────────────────────────────────────

def test_french_expressions():
    ev = one("entre 40k et 50k€")
    assert ev.min_annual_eur == 40000
    assert ev.max_annual_eur == 50000
    assert ev.currency == "EUR"


def test_english_expressions():
    ev = one("between 50k and 60k")
    assert ev.min_annual_eur == 50000
    assert ev.max_annual_eur == 60000


def test_range_with_to():
    ev = one("50k to 60k EUR")
    assert ev.min_annual_eur == 50000
    assert ev.max_annual_eur == 60000


def test_range_french_a():
    ev = one("Rémunération : 55 000 € à 70 000 € brut annuel")
    assert ev.min_annual_eur == 55000
    assert ev.max_annual_eur == 70000
    assert ev.periodicity == "annual"


# ──────────────────────────────────────────────────────────────────────
# Salary types
# ──────────────────────────────────────────────────────────────────────

def test_salary_package():
    ev = one("Package 70k€ brut annuel")
    assert ev.salary_type == "package"
    assert ev.min_annual_eur == 70000


def test_salary_bonus():
    ev = one("Bonus 10k€")
    assert ev.salary_type == "bonus"
    assert ev.min_annual_eur == 10000


def test_salary_base():
    ev = one("Base 50k€")
    assert ev.salary_type == "base"
    assert ev.min_annual_eur == 50000


def test_salary_total_compensation():
    ev = one("Total compensation 150k$")
    assert ev.salary_type == "total"
    assert ev.min_annual_eur == 150000
    assert ev.currency == "USD"


def test_salary_ctc():
    ev = one("CTC 120k€")
    assert ev.salary_type == "total"


def test_salary_variable():
    ev = one("Variable 20%")
    assert ev.salary_type == "variable"
    # A percentage is not a monetary amount: nothing is invented.
    assert ev.min_annual_eur is None
    assert ev.max_annual_eur is None


def test_salary_equity():
    ev = one("RSU 5000 units")
    assert ev.salary_type == "rsu"
    assert ev.min_annual_eur is None
    assert ev.max_annual_eur is None


def test_salary_stock_options():
    ev = one("Stock options 1000 shares")
    assert ev.salary_type == "stock"
    assert ev.min_annual_eur is None


def test_salary_rsu():
    ev = one("RSU 2000 units vesting 4 ans")
    assert ev.salary_type == "rsu"


def test_salary_generic_word_is_base():
    ev = one("Salaire brut annuel : 45 000 €")
    assert ev.salary_type == "base"
    assert ev.periodicity == "annual"


# ──────────────────────────────────────────────────────────────────────
# Zero invention
# ──────────────────────────────────────────────────────────────────────

def test_no_salary():
    assert extract_salary("Pas de salaire mentionné") == []


def test_empty_text():
    assert extract_salary("") == []
    assert extract_salary("   ") == []


def test_no_number_no_mention():
    assert extract_salary("Rémunération attractive selon profil.") == []


def test_ordinary_numbers_are_ignored():
    assert extract_salary("Notre entreprise compte 250 collaborateurs depuis 2019.") == []


def test_percentage_only_is_ignored():
    assert extract_salary("20% de participation") == []


def test_scale_counter_is_ignored():
    assert extract_salary("50k downloads chaque mois") == []


def test_year_is_not_a_salary():
    assert extract_salary("Créée en 2019, la société emploie 30 personnes.") == []


# ──────────────────────────────────────────────────────────────────────
# Several mentions in the same text
# ──────────────────────────────────────────────────────────────────────

def test_multiple_salaries():
    evidences = extract_salary("Base 50k€ + bonus 10k€")
    assert len(evidences) == 2
    assert evidences[0].salary_type == "base"
    assert evidences[0].min_annual_eur == 50000
    assert evidences[1].salary_type == "bonus"
    assert evidences[1].min_annual_eur == 10000


def test_a_mention_does_not_reuse_the_previous_qualifiers():
    """The "brut annuel" of a mention belongs to it, not to the next one."""
    text = "Nous recrutons un Data Scientist (45-55k€ brut annuel) et un Engineer (50 k€)."
    evidences = extract_salary(text)
    assert len(evidences) == 2
    assert evidences[0].periodicity == "annual"
    assert evidences[1].periodicity == "unknown"
    assert evidences[1].salary_type == "unknown"


def test_salary_word_is_a_base_salary():
    ev = one("Le salaire est de 45 000 euros par an.")
    assert ev.salary_type == "base"
    assert ev.periodicity == "annual"


def test_hourly_uses_the_french_working_year():
    """35 hours a week x 52 weeks."""
    ev = one("Per hour $50")
    assert ev.min_annual_eur == 50 * 1820


def test_full_package_breakdown():
    evidences = extract_salary("Total compensation 150k$ (base 120k$ + bonus 30k$)")
    assert [e.salary_type for e in evidences] == ["total", "base", "bonus"]
    assert [e.min_annual_eur for e in evidences] == [150000, 120000, 30000]


def test_evidences_are_ordered_by_position():
    evidences = extract_salary("Base 50k€ puis bonus 10k€ puis prime 5k€")
    assert [e.source_offset for e in evidences] == sorted(e.source_offset for e in evidences)


# ──────────────────────────────────────────────────────────────────────
# Provenance
# ──────────────────────────────────────────────────────────────────────

def test_provenance_offsets():
    text = "Nous recherchons un ingénieur. Rémunération : 45 000 € brut annuel."
    ev = one(text)
    assert text[ev.source_offset:ev.source_offset + len(ev.raw_text)] == ev.raw_text
    assert ev.raw_text == "45 000 € brut annuel"


def test_provenance_excerpt_is_around_the_offset():
    text = "Nous recherchons un ingénieur. Rémunération : 45 000 € brut annuel."
    ev = one(text)
    assert len(ev.source_excerpt) <= 50
    assert ev.source_offset - 25 <= text.index("45 000 €") <= ev.source_offset + 25


def test_provenance_keeps_the_source_text():
    text = "Package 70k€ brut annuel"
    ev = one(text)
    assert ev.raw_text == text
    assert ev.raw_amount_text == "70k€"


def test_raw_period_text():
    ev = one("45 000 € brut annuel")
    assert ev.raw_period_text == "brut annuel"


def test_raw_amount_text():
    ev = one("$80,000 per year")
    assert ev.raw_amount_text == "$80,000"


def test_excerpt_replaces_newlines():
    text = "Salaire\n45 000 € brut annuel"
    ev = one(text)
    assert "\n" not in ev.source_excerpt
    assert "⏎" in ev.source_excerpt


# ──────────────────────────────────────────────────────────────────────
# Confidence
# ──────────────────────────────────────────────────────────────────────

def test_confidence_scoring():
    clear = one("Salaire brut annuel : 45 000 €")
    vague = one("50k")
    assert clear.confidence > 0.8
    assert vague.confidence < 0.5


def test_confidence_is_bounded():
    for text in ("45 000 € brut annuel", "50k", "Variable 20%", "RSU 5000 units"):
        for ev in extract_salary(text):
            assert 0.0 <= ev.confidence <= 1.0


def test_confidence_currency_beats_bare_amount():
    with_currency = one("55k€")
    without = one("55k")
    assert with_currency.confidence > without.confidence


# ──────────────────────────────────────────────────────────────────────
# Determinism & purity
# ──────────────────────────────────────────────────────────────────────

def test_deterministic():
    text = "Rémunération : 45 000 € brut annuel, package 70k€."
    first = extract_salary(text)
    second = extract_salary(text)
    assert first == second


def test_no_mutation_of_the_input():
    text = "Rémunération : 45 000 € brut annuel"
    copy = str(text)
    extract_salary(text)
    assert text == copy


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("45000", 45000.0),
        ("45 000", 45000.0),
        ("60,000", 60000.0),
        ("6,000,000", 6000000.0),
        ("45.000", 45000.0),
        ("1.5", 1.5),
        ("45,50", 45.5),
    ],
)
def test_parse_number(raw, expected):
    assert _parse_number(raw) == expected


def test_parse_number_keeps_two_years_apart():
    assert _parse_number("2020") == 2020.0
    assert _parse_number("2021") == 2021.0


# ──────────────────────────────────────────────────────────────────────
# Performance
# ──────────────────────────────────────────────────────────────────────

def test_performance_on_a_long_offer():
    """A 50 000 character offer must be extracted in a few milliseconds."""
    description = (
        "Notre entreprise recherche un ingénieur logiciel pour renforcer son équipe data. "
        "Vous évoluerez au sein d'une squad pluridisciplinaire, en interaction permanente "
        "avec les équipes produit, design et infrastructure. Vos missions couvriront "
        "l'analyse des besoins, la conception d'architectures robustes et le développement "
        "de services distribués. "
    )
    salary = (
        "Rémunération : 55 000 € à 70 000 € brut annuel, variable 10% et participation. "
    )
    text = (description * 160)[:50000] + salary
    assert len(text) > 50000

    # The best of three runs is used: it measures the cost of the extraction
    # itself, not the scheduling noise of the machine.
    elapsed = min(_timed_ms(text) for _ in range(3))

    assert extract_salary(text), "the offer mentions a salary: it must be extracted"
    assert elapsed < 5.0, f"extraction took {elapsed:.1f} ms for 50 000 characters"


def _timed_ms(text: str) -> float:
    """Run the extraction once and return the elapsed time in milliseconds."""
    start = time.perf_counter()
    extract_salary(text)
    return (time.perf_counter() - start) * 1000
