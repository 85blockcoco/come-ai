"""Tests for the offer remuneration extractor (CVBOOST-16).

All fixtures are synthetic — no real offer, no personal data, no network.
The extractor must stay pure: same text in, same evidence out.
"""

from __future__ import annotations

import time

import pytest

from career.cv_quality import extract_salary
from career.cv_quality.models import SalaryEvidence


# ──────────────────────────────────────────────────────────────────────
# Montants simples
# ──────────────────────────────────────────────────────────────────────


def test_salary_simple_eur() -> None:
    """« 45 000 € brut annuel » → montant annuel en euros."""
    evidences = extract_salary("45 000 € brut annuel")
    assert len(evidences) == 1
    evidence = evidences[0]
    assert evidence.min_annual_eur == 45000
    assert evidence.max_annual_eur == 45000
    assert evidence.currency == "EUR"
    assert evidence.periodicity == "annual"
    assert evidence.raw_amount_text == "45 000 €"
    assert evidence.raw_period_text == "brut annuel"
    assert evidence.raw_text == "45 000 € brut annuel"


def test_salary_k_eur() -> None:
    """« 55k€ » → le suffixe k vaut mille."""
    evidences = extract_salary("55k€")
    assert len(evidences) == 1
    assert evidences[0].min_annual_eur == 55000
    assert evidences[0].max_annual_eur == 55000
    assert evidences[0].currency == "EUR"


def test_salary_k_without_currency() -> None:
    """« 50k » → montant sans devise lue : aucune devise n'est inventée."""
    evidences = extract_salary("50k")
    assert len(evidences) == 1
    assert evidences[0].min_annual_eur == 50000
    assert evidences[0].max_annual_eur == 50000
    assert evidences[0].currency == ""


def test_salary_k_m_suffix() -> None:
    """« 1.5M€ » → le suffixe M vaut un million."""
    evidences = extract_salary("1.5M€")
    assert len(evidences) == 1
    assert evidences[0].min_annual_eur == 1_500_000
    assert evidences[0].max_annual_eur == 1_500_000


def test_salary_thousands_variants() -> None:
    """« 45 000 », « 45,000 » et « 45.000 » valent la même chose."""
    for written in ("45 000 €", "45,000 EUR", "45.000 EUR"):
        evidences = extract_salary(written)
        assert len(evidences) == 1, written
        assert evidences[0].min_annual_eur == 45000, written
        assert evidences[0].currency == "EUR", written


def test_salary_decimal_is_not_a_thousand() -> None:
    """« 45,50 € » est un décimal, pas quarante-cinq mille."""
    evidences = extract_salary("45,50 €")
    assert len(evidences) == 1
    assert evidences[0].min_annual_eur == 45.5


def test_salary_leading_currency_symbol() -> None:
    """« €45 000 » → la devise peut précéder le montant."""
    evidences = extract_salary("€45 000")
    assert len(evidences) == 1
    assert evidences[0].min_annual_eur == 45000
    assert evidences[0].currency == "EUR"
    assert evidences[0].raw_amount_text == "€45 000"


def test_salary_no_invention_without_currency() -> None:
    """« 45 000 » seul n'est pas un salaire : la devise manque."""
    assert extract_salary("45 000") == []


# ──────────────────────────────────────────────────────────────────────
# Fourchettes
# ──────────────────────────────────────────────────────────────────────


def test_salary_range() -> None:
    """« 45-55k€ » → une seule evidence, deux bornes."""
    evidences = extract_salary("45-55k€")
    assert len(evidences) == 1
    assert evidences[0].min_annual_eur == 45000
    assert evidences[0].max_annual_eur == 55000
    assert evidences[0].currency == "EUR"


def test_salary_range_with_spaces() -> None:
    """« 50 k - 60 k € » → les espaces ne séparent pas les montants."""
    evidences = extract_salary("50 k - 60 k €")
    assert len(evidences) == 1
    assert evidences[0].min_annual_eur == 50000
    assert evidences[0].max_annual_eur == 60000
    assert evidences[0].currency == "EUR"


def test_french_expressions() -> None:
    """« entre 40k et 50k » → fourchette française."""
    evidences = extract_salary("entre 40k et 50k")
    assert len(evidences) == 1
    assert evidences[0].min_annual_eur == 40000
    assert evidences[0].max_annual_eur == 50000


def test_english_expressions() -> None:
    """« between 50k and 60k » → fourchette anglaise."""
    evidences = extract_salary("between 50k and 60k")
    assert len(evidences) == 1
    assert evidences[0].min_annual_eur == 50000
    assert evidences[0].max_annual_eur == 60000


def test_french_range_with_currency() -> None:
    """« de 45 000 à 55 000 euros » → fourchette avec devise."""
    evidences = extract_salary("de 45 000 à 55 000 euros")
    assert len(evidences) == 1
    assert evidences[0].min_annual_eur == 45000
    assert evidences[0].max_annual_eur == 55000
    assert evidences[0].currency == "EUR"


def test_two_amounts_are_not_a_range() -> None:
    """Deux montants séparés par du texte ne forment pas une fourchette."""
    evidences = extract_salary("Base 50k€ + bonus 10k€")
    assert len(evidences) == 2
    assert evidences[0].min_annual_eur == 50000
    assert evidences[1].min_annual_eur == 10000


# ──────────────────────────────────────────────────────────────────────
# Devises
# ──────────────────────────────────────────────────────────────────────


def test_salary_usd() -> None:
    """« $80,000 per year » → devise USD, périodicité annuelle."""
    evidences = extract_salary("$80,000 per year")
    assert len(evidences) == 1
    assert evidences[0].min_annual_eur == 80000
    assert evidences[0].max_annual_eur == 80000
    assert evidences[0].currency == "USD"
    assert evidences[0].periodicity == "annual"


def test_salary_gbp() -> None:
    """« £45,000 per annum » → devise GBP."""
    evidences = extract_salary("£45,000 per annum")
    assert len(evidences) == 1
    assert evidences[0].min_annual_eur == 45000
    assert evidences[0].currency == "GBP"
    assert evidences[0].periodicity == "annual"


def test_salary_currency_code() -> None:
    """« 50 000 EUR » → le code ISO est lu."""
    evidences = extract_salary("50 000 EUR")
    assert len(evidences) == 1
    assert evidences[0].currency == "EUR"
    assert evidences[0].min_annual_eur == 50000


# ──────────────────────────────────────────────────────────────────────
# Périodicité
# ──────────────────────────────────────────────────────────────────────


def test_salary_monthly_is_annualized() -> None:
    """« 4 500 € mensuel » → annualisé sur douze mois."""
    evidences = extract_salary("4 500 € mensuel")
    assert len(evidences) == 1
    assert evidences[0].min_annual_eur == 54000
    assert evidences[0].max_annual_eur == 54000
    assert evidences[0].periodicity == "monthly"


def test_salary_hourly_is_annualized() -> None:
    """« 25 €/heure » → annualisé sur la convention 35 h × 52 semaines."""
    from career.cv_quality.parser import HOURS_PER_YEAR

    evidences = extract_salary("25 €/heure")
    assert len(evidences) == 1
    assert evidences[0].periodicity == "hourly"
    assert evidences[0].min_annual_eur == 25 * HOURS_PER_YEAR


def test_salary_slash_period() -> None:
    """« 45 000 € / an » → la périodicité est lue après la barre oblique."""
    evidences = extract_salary("45 000 € / an")
    assert len(evidences) == 1
    assert evidences[0].periodicity == "annual"
    assert evidences[0].raw_period_text == "an"


def test_salary_slash_month() -> None:
    """« 3 000 € / mois » → périodicité mensuelle."""
    evidences = extract_salary("3 000 € / mois")
    assert len(evidences) == 1
    assert evidences[0].periodicity == "monthly"
    assert evidences[0].min_annual_eur == 36000


# ──────────────────────────────────────────────────────────────────────
# Nature de la rémunération
# ──────────────────────────────────────────────────────────────────────


def test_salary_package() -> None:
    """« Package 70k€ brut annuel » → type package."""
    evidences = extract_salary("Package 70k€ brut annuel")
    assert len(evidences) == 1
    assert evidences[0].salary_type == "package"
    assert evidences[0].min_annual_eur == 70000


def test_salary_bonus() -> None:
    """« Bonus 10k€ » → type bonus."""
    evidences = extract_salary("Bonus 10k€")
    assert len(evidences) == 1
    assert evidences[0].salary_type == "bonus"


def test_salary_equity() -> None:
    """« RSU 5000 units » → type rsu, pas un montant en euros."""
    evidences = extract_salary("RSU 5000 units")
    assert len(evidences) == 1
    assert evidences[0].salary_type == "rsu"
    assert evidences[0].min_annual_eur is None
    assert evidences[0].max_annual_eur is None
    assert evidences[0].currency == ""


def test_salary_variable() -> None:
    """« Variable 20% » → type variable, pourcentage non convertible."""
    evidences = extract_salary("Variable 20%")
    assert len(evidences) == 1
    assert evidences[0].salary_type == "variable"
    assert evidences[0].min_annual_eur is None
    assert evidences[0].raw_amount_text == "20%"


def test_salary_base() -> None:
    """« Base 50k€ » → type base."""
    evidences = extract_salary("Base 50k€")
    assert len(evidences) == 1
    assert evidences[0].salary_type == "base"


def test_stock_options() -> None:
    """« Stock options 1000 shares » → type stock, pas un montant."""
    evidences = extract_salary("Stock options 1000 shares")
    assert len(evidences) == 1
    assert evidences[0].salary_type == "stock"
    assert evidences[0].min_annual_eur is None
    assert evidences[0].raw_amount_text == "1000 shares"


def test_rsu() -> None:
    """« RSU 2000 units vesting 4 ans » → le « 4 ans » n'est pas un salaire."""
    evidences = extract_salary("RSU 2000 units vesting 4 ans")
    assert len(evidences) == 1
    assert evidences[0].salary_type == "rsu"
    assert evidences[0].min_annual_eur is None


def test_total_compensation() -> None:
    """« Total compensation 120k$ » → type total."""
    evidences = extract_salary("Total compensation 120k$")
    assert len(evidences) == 1
    assert evidences[0].salary_type == "total"
    assert evidences[0].currency == "USD"


def test_gross_annual_is_a_base_salary() -> None:
    """« 45 000 € brut annuel » → la rémunération de base."""
    evidences = extract_salary("45 000 € brut annuel")
    assert evidences[0].salary_type == "base"


# ──────────────────────────────────────────────────────────────────────
# Zéro invention
# ──────────────────────────────────────────────────────────────────────


def test_no_salary() -> None:
    """« Pas de salaire mentionné » → liste vide."""
    assert extract_salary("Pas de salaire mentionné") == []


def test_no_salary_in_english() -> None:
    """« No salary mentioned » → liste vide."""
    assert extract_salary("No salary mentioned") == []


def test_no_salary_on_empty_text() -> None:
    """Un texte vide ne produit aucune evidence."""
    assert extract_salary("") == []
    assert extract_salary("   ") == []


def test_years_of_experience_are_not_salaries() -> None:
    """Une expérience en années n'est pas une rémunération."""
    assert extract_salary("5 years of experience") == []
    assert extract_salary("3 ans d'expérience, 12 000 followers") == []


def test_percentage_without_component_is_ignored() -> None:
    """« 20 % de participation » n'est pas une rémunération."""
    assert extract_salary("20 % de participation") == []


# ──────────────────────────────────────────────────────────────────────
# Provenance
# ──────────────────────────────────────────────────────────────────────


def test_provenance_is_exact() -> None:
    """Chaque evidence pointe la position exacte de son extrait."""
    text = "CDI, 45 000 € brut annuel, prime de 5 000 €"
    evidences = extract_salary(text)
    assert len(evidences) == 2
    for evidence in evidences:
        assert text[evidence.source_offset:evidence.source_offset + len(evidence.raw_text)] == evidence.raw_text
        assert evidence.source_excerpt in text
        assert len(evidence.source_excerpt) <= 50


def test_multiple_salaries_keep_their_own_type() -> None:
    """« Base 50k€ + bonus 10k€ » → deux evidences typées."""
    evidences = extract_salary("Base 50k€ + bonus 10k€")
    assert [evidence.salary_type for evidence in evidences] == ["base", "bonus"]
    assert [evidence.min_annual_eur for evidence in evidences] == [50000, 10000]


def test_evidences_are_ordered_by_position() -> None:
    """Les evidences sont rendues dans l'ordre du texte."""
    text = "Variable 20% puis base 50k€ puis bonus 5k€"
    offsets = [evidence.source_offset for evidence in extract_salary(text)]
    assert offsets == sorted(offsets)


def test_extractor_is_deterministic() -> None:
    """Deux appels sur le même texte donnent le même résultat."""
    text = "Rémunération : 45 000 € brut annuel + variable 10 % + RSUs 5000 units"
    first = extract_salary(text)
    second = extract_salary(text)
    assert first == second
    assert len(first) == 3


# ──────────────────────────────────────────────────────────────────────
# Confiance
# ──────────────────────────────────────────────────────────────────────


def test_confidence_scoring() -> None:
    """Un passage clair est confiant, un passage ambigu ne l'est pas."""
    clear = extract_salary("Salaire : 45 000 € brut annuel")[0]
    ambiguous = extract_salary("50k")[0]
    assert clear.confidence > 0.8
    assert ambiguous.confidence < 0.5


def test_confidence_is_bounded() -> None:
    """La confiance reste dans [0, 1]."""
    for text in ("45 000 € brut annuel", "50k", "Variable 20%", "RSU 5000 units"):
        for evidence in extract_salary(text):
            assert 0.0 <= evidence.confidence <= 1.0


def test_non_monetary_components_stay_below_the_money_threshold() -> None:
    """Un pourcentage n'est pas un montant : sa confiance reste plafonnée."""
    evidence = extract_salary("Variable 20%")[0]
    assert evidence.confidence < 0.5


# ──────────────────────────────────────────────────────────────────────
# Contrat de la fonction
# ──────────────────────────────────────────────────────────────────────


def test_extract_salary_returns_salary_evidence_objects() -> None:
    """Le type de retour est stable et documenté."""
    evidences = extract_salary("45 000 € brut annuel")
    assert isinstance(evidences[0], SalaryEvidence)


def test_extract_salary_is_pure_and_offline() -> None:
    """Le module ne fait aucun appel réseau ni lecture de fichier."""
    from pathlib import Path

    package_dir = Path(__file__).resolve().parents[1] / "career" / "cv_quality"
    for name in ("parser.py", "models.py"):
        source = (package_dir / name).read_text(encoding="utf-8")
        for forbidden in ("import requests", "import urllib", "import socket", "urlopen", "subprocess"):
            assert forbidden not in source, f"{name} ne doit pas utiliser {forbidden}"


def test_performance_on_a_long_offer_description() -> None:
    """Un texte de 50k caractères reste sous 5 ms."""
    filler = "Nous recherchons un ingénieur confirmé pour une équipe produit. "
    text = (filler * 700 + " Salaire : 45 000 € brut annuel " + filler * 700)[:50000]
    assert "45 000" in text
    start = time.perf_counter()
    evidences = extract_salary(text)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert len(evidences) == 1
    assert elapsed_ms < 5.0, f"extraction trop lente : {elapsed_ms:.1f} ms"


@pytest.mark.parametrize(
    "text",
    [
        "45 000 € brut annuel",
        "Package 70k€ brut annuel, variable 10%",
        "$80,000 per year",
        "entre 40k et 50k",
        "RSU 2000 units vesting 4 ans",
    ],
)
def test_extraction_is_stable_across_calls(text: str) -> None:
    """Le contrat de pureté : deux appels, deux résultats identiques."""
    assert extract_salary(text) == extract_salary(text)
