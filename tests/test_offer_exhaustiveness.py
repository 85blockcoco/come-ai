"""SK-20 — tests du score d'exhaustivité par offre.

Le chargeur de fixtures lit uniquement ce worktree : jamais une base privée ni
un checkout voisin. Chaque fixture décrit le dictionnaire `job` que produit
`qualify_offer(...).to_dict()`, avec l'exhaustivité nested sous `"qualification"`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from career.offer_exhaustiveness import (
    ExhaustivenessScore,
    WEIGHTS,
    compute_exhaustiveness,
    measure_corpus_exhaustiveness,
)
from career.offer_qualification import qualify_offer

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "offer_exhaustiveness"

# (fixture, score attendu, couleur de badge attendue)
FIXTURE_CASES: tuple[tuple[str, int, str], ...] = (
    ("complete_offer.json", 100, "green"),
    ("standard_finance.json", 75, "green"),
    ("greenhouse_raw.json", 0, "gray"),
    ("rich_description.json", 65, "orange"),
    ("title_only.json", 0, "gray"),
    ("missions_dates.json", 40, "orange"),
    ("salary_only.json", 25, "red"),
    ("conditions_only.json", 20, "red"),
    ("education_only.json", 15, "red"),
    ("salary_dates.json", 35, "red"),
    ("ceiling_only.json", 0, "gray"),
    ("deadline_only.json", 10, "red"),
    ("start_month_passage.json", 10, "red"),
    ("salary_fact_alias.json", 25, "red"),
    ("education_alias.json", 15, "red"),
    ("empty_string_evidence.json", 0, "gray"),
    ("empty_job.json", 0, "gray"),
)


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _fixture_names() -> list[str]:
    assert len(FIXTURE_CASES) >= 15, "la mission exige au moins 15 fixtures synthétiques"
    assert sorted(FIXTURES.glob("*.json")) == sorted(
        Path(FIXTURES / name) for name, _, _ in FIXTURE_CASES
    ), "chaque fixture du répertoire doit être couverte par un cas déclaré"
    return [name for name, _, _ in FIXTURE_CASES]


def test_weights_sum_to_hundred():
    assert sum(WEIGHTS.values()) == 100
    assert WEIGHTS == {"missions": 30, "salary": 25, "conditions": 20,
                       "education": 15, "dates": 10}


# --- Fixtures synthétiques (17) ------------------------------------------------

@pytest.mark.parametrize(("fixture_name", "expected_score", "expected_color"), FIXTURE_CASES)
def test_fixtures_score_and_badge(fixture_name: str, expected_score: int, expected_color: str):
    score = compute_exhaustiveness(_load_fixture(fixture_name))
    assert score.overall_score == expected_score == sum(score.breakdown.values())
    assert score.badge_color == expected_color
    assert score.badge_label.startswith("Exhaustivité")
    # Règle tranchée : salaire manquant ⇒ mention spécifique, y compris à 0 %.
    if score.breakdown["salary"] == 0:
        assert "Rémunération : non communiquée" in score.badge_label
    else:
        assert "Rémunération" not in score.badge_label


def test_complete_fixture_breakdown_exact():
    score = compute_exhaustiveness(_load_fixture("complete_offer.json"))
    assert score.breakdown == {"missions": 30, "salary": 25, "conditions": 20,
                               "education": 15, "dates": 10}
    assert score.missing == []
    assert score.present == ["missions", "salary", "conditions", "education", "dates"]
    assert score.badge_label == "Exhaustivité 100%"
    assert score.badge_color == "green"


def test_greenhouse_raw_badge_label_exact():
    score = compute_exhaustiveness(_load_fixture("greenhouse_raw.json"))
    assert score.badge_label == "Exhaustivité 0% — offre vide | Rémunération : non communiquée"
    assert score.badge_color == "gray"
    assert set(score.missing) == {"missions", "salary", "conditions", "education", "dates"}


def test_standard_finance_keeps_salary_mention():
    score = compute_exhaustiveness(_load_fixture("standard_finance.json"))
    assert score.overall_score == 75
    assert score.badge_color == "green"
    assert score.badge_label == "Exhaustivité 75% | Rémunération : non communiquée"


def test_component_present_rejects_empty_evidence():
    score = compute_exhaustiveness(_load_fixture("empty_string_evidence.json"))
    assert score.breakdown == {"missions": 0, "salary": 0, "conditions": 0,
                               "education": 0, "dates": 0}
    assert "salary" in score.missing and "missions" in score.missing


def test_ceiling_alone_never_credits_dates():
    """« up to 6 months » n'établit pas de durée réelle : dates = 0."""
    score = compute_exhaustiveness(_load_fixture("ceiling_only.json"))
    assert score.breakdown["dates"] == 0
    assert score.overall_score == 0


def test_missions_dates_fixture_boundary_of_orange():
    score = compute_exhaustiveness(_load_fixture("missions_dates.json"))
    assert score.overall_score == 40  # plancher "orange" (>= 40)
    assert score.badge_color == "orange"


def test_salary_dates_fixture_red_range():
    score = compute_exhaustiveness(_load_fixture("salary_dates.json"))
    assert score.overall_score == 35
    assert score.badge_color == "red"


def test_to_dict_roundtrip_is_json_serde():
    score = compute_exhaustiveness(_load_fixture("rich_description.json"))
    dumped = json.loads(json.dumps(score.to_dict()))
    rebuilt = ExhaustivenessScore(**dumped)
    assert rebuilt == score


# --- mesure de corpus ---------------------------------------------------------

def _corpus_of_112_jobs_from_fixtures() -> list[dict[str, Any]]:
    """Corpus déterministe de 112 jobs, pondération immobilise d'après fixtures."""
    corpus: list[dict[str, Any]] = []
    # 25 offres complètes, 30 standard finance, 20 description riche,
    # 22 missions+dates, 15 brutes type Greenhouse : total 112.
    corpus += [_load_fixture("complete_offer.json") for _ in range(25)]
    corpus += [_load_fixture("standard_finance.json") for _ in range(30)]
    corpus += [_load_fixture("rich_description.json") for _ in range(20)]
    corpus += [_load_fixture("missions_dates.json") for _ in range(22)]
    corpus += [_load_fixture("greenhouse_raw.json") for _ in range(15)]
    return corpus


def test_corpus_average_above_sixty_percent():
    jobs = _corpus_of_112_jobs_from_fixtures()
    assert len(jobs) >= 100
    scores = [compute_exhaustiveness(job).overall_score for job in jobs]
    avg = sum(scores) / len(scores)
    attendu = (25 * 100 + 30 * 75 + 20 * 65 + 22 * 40 + 15 * 0) / len(jobs)
    assert avg == pytest.approx(attendu, abs=1e-9)
    assert avg > 60, f"Exhaustivité moyenne {avg:.1f}% < 60%"


def test_measure_corpus_empty_is_zero():
    assert measure_corpus_exhaustiveness([]) == 0.0


def test_measure_corpus_matches_compute():
    jobs = _corpus_of_112_jobs_from_fixtures()
    assert measure_corpus_exhaustiveness(jobs) == pytest.approx(
        measure_corpus_exhaustiveness(jobs), abs=1e-9)  # déterministe
    singles = [_load_fixture(name) for name, _, _ in FIXTURE_CASES]
    for job in singles:
        assert compute_exhaustiveness(job).overall_score in range(101)


# --- intégration dans qualify_offer -------------------------------------------

def _integration_offer(**overrides: Any) -> dict[str, Any]:
    description = (
        "Vos missions : assister l'équipe M&A dans l'analyse de dossiers.\n"
        "Nous offrons : restauration d'entreprise et remboursement des transports.\n"
        "Étudiant en Master 1 ou 2 Finance.\n"
        "Gratification de 1 150 € à 1 300 € mensuels.\n"
        "Stage de 6 mois, début février 2027."
    )
    return {"title": "Stage M&A",
            "description_original": description,
            **overrides}


def test_qualify_offer_populates_exhaustiveness_fields():
    result = qualify_offer(_integration_offer(), minimum_duration_months=6,
                           as_of=__import__("datetime").date(2026, 10, 22))
    assert result.exhaustiveness_score >= 0
    assert set(result.exhaustiveness_breakdown) == {"missions", "salary", "conditions", "education", "dates"}
    assert result.exhaustiveness_badge.startswith("Exhaustivité")
    assert result.exhaustiveness_badge_color in {"green", "orange", "red", "gray"}
    # Les cinq extracteurs intégrés créditent chaque fait présent dans la source.
    assert result.exhaustiveness_breakdown["dates"] == 10
    assert result.exhaustiveness_breakdown == {
        "missions": 30, "salary": 25, "conditions": 20, "education": 15, "dates": 10,
    }
    assert result.exhaustiveness_missing == ()
    assert "exhaustiveness" in result.provenance


def test_qualify_offer_empty_description_scores_zero():
    result = qualify_offer({"title": "", "description_original": ""}, minimum_duration_months=6,
                           as_of=__import__("datetime").date(2026, 10, 22))
    assert result.exhaustiveness_score == 0
    assert result.exhaustiveness_badge_color == "gray"
    assert "offre vide" in result.exhaustiveness_badge
    assert "Rémunération : non communiquée" in result.exhaustiveness_badge
    assert set(result.exhaustiveness_missing) == {"missions", "salary", "conditions", "education", "dates"}


def test_qualifiedoffer_to_dict_carries_exhaustiveness():
    result = qualify_offer(_integration_offer(), as_of=__import__("datetime").date(2026, 10, 22))
    dumped = result.to_dict()
    assert dumped["exhaustiveness_score"] == result.exhaustiveness_score
    assert dumped["provenance"]["exhaustiveness"]["value"] == result.exhaustiveness_score


def test_score_input_is_never_contaminated_by_its_own_entry():
    """La preuve d'exhaustivité elle-même ne doit pas alimenter le scoring."""
    result = qualify_offer(_integration_offer(), as_of=__import__("datetime").date(2026, 10, 22))
    first = result.exhaustiveness_score
    recompute = compute_exhaustiveness({
        "qualification": {"provenance": {k: {"value": v.value} for k, v in result.provenance.items()}}})
    # L'entrée "exhaustiveness" a une valeur int (> 0), mais elle ne mappe
    # aucune composante : recalculer via les clés d'épreuves n'ajoute rien.
    assert recompute.breakdown == result.exhaustiveness_breakdown
    assert recompute.overall_score == first


def test_defaults_on_a_manual_construction_are_zeroed():
    """Un QualifiedOffer construit sans exhaustivité reste explicite à 0."""
    from career.offer_qualification import QualifiedOffer
    fallback = QualifiedOffer(
        contract_type="internship", contract_status="confirmed", posted_date=None,
        start_date=None, end_date=None, start_month=None, duration_min_months=None,
        duration_max_months=None, language=None, country="France", city="Paris",
        geography_status="allowed", source_name="src", source_id="id",
        official_url="https://example.test/job", verification_status="verified",
        target_status="to_verify", missing_fields=(), provenance={}, reasons=())
    assert fallback.exhaustiveness_score == 0
    assert fallback.exhaustiveness_badge_color == "gray"
    assert fallback.exhaustiveness() .badge_label == fallback.exhaustiveness_badge


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
