"""Tests for the academic research kit (NAGE BALANCE 8H — Worker D)."""

from __future__ import annotations

import re

import pytest

from academics.research_kit import (
    ParaphraseCheck,
    build_outline,
    citation_check,
    citation_format,
    homework_steps,
    paraphrase_check,
    to_dict,
)


# ------------------------------------------------------------------- outline


def test_outline_title_and_ordered_plan() -> None:
    o = build_outline("Marché de l'électricité", ["Introduction", "Prix"], [])
    assert o.topic == "Marché de l'électricité"
    assert [s.index for s in o.sections] == [1, 2]
    assert any("plan ordonné" in c for c in o.checks)


def test_outline_placeholder_for_empty_section() -> None:
    o = build_outline("Sujet", ["Intro", "   ", "Fin"], [])
    blank = o.sections[1]
    assert blank.placeholder is True
    assert blank.title == "[À COMPLÉTER]"
    assert "placeholder" in blank.notes
    assert o.ok is False


def test_outline_no_invention_in_placeholder() -> None:
    o = build_outline("Sujet", ["A", "", "B"], [])
    blank = o.sections[1]
    assert blank.facts == []
    # aucune invention : notes ne proposent aucun contenu, seulement à compléter
    assert "à compléter" in blank.notes
    assert "aucune invention" in blank.notes


def test_outline_ok_when_all_sections_titled() -> None:
    o = build_outline("Sujet sérieux", ["Intro", "Méthode", "Résultats"], [])
    assert o.ok is True
    assert all(not s.placeholder for s in o.sections)


def test_outline_facts_attached_to_matching_section() -> None:
    o = build_outline(
        "Finance quant",
        ["Demande d'électricité", "Prix spot"],
        ["La demande d'électricité augmente en hiver"],
    )
    assert o.facts_used == ["La demande d'électricité augmente en hiver"]
    assert o.missing_facts == []
    assert o.sections[0].facts == ["La demande d'électricité augmente en hiver"]
    assert o.sections[1].facts == []


def test_outline_missing_facts_listed() -> None:
    o = build_outline("Astrophysique", ["Étoiles"], ["Facture électorale suisse 2026"])
    assert o.facts_used == []
    assert o.missing_facts == ["Facture électorale suisse 2026"]


def test_outline_empty_topic_flagged() -> None:
    o = build_outline("   ", ["Intro"], [])
    assert o.ok is False
    assert any("topic" in c or "titre de recherche" in c for c in o.checks)


def test_outline_to_dict() -> None:
    d = to_dict(build_outline("T", ["A"], None))
    assert set(d) == {"topic", "sections", "facts_used", "missing_facts", "checks", "ok"}
    assert isinstance(d["ok"], bool)


# ----------------------------------------------------------- citation_format


def test_citation_format_apa() -> None:
    s = citation_format("Smith, J.", 2024, "Titre de l'étude", "Journal of Finance", "apa")
    assert s == "Smith, J. (2024). Titre de l'étude. Journal of Finance."


def test_citation_format_mla() -> None:
    s = citation_format("Smith, J.", 2024, "Titre de l'étude", "Journal of Finance", "mla")
    assert s == 'Smith, J. "Titre de l\'étude." Journal of Finance, 2024.'


def test_citation_format_harvard() -> None:
    s = citation_format(
        "Smith, J.",
        "2024",
        "Titre de l'étude",
        "Journal of Finance",
        "harvard",
    )
    assert s == "Smith, J. (2024) 'Titre de l'étude', Journal of Finance."


def test_citation_format_default_is_apa() -> None:
    assert citation_format("Auteur Un", 2025, "Étude X", "Revue Y") == (
        "Auteur Un (2025). Étude X. Revue Y."
    )


def test_citation_format_unknown_style_raises() -> None:
    with pytest.raises(ValueError, match="styles valides"):
        citation_format("Smith, J.", 2024, "T", "S", "chicago")


# ------------------------------------------------------------- citation_check


def test_citation_check_used_and_unused() -> None:
    text = "Selon Smith (2024), le marché du cuivre se resserre. " * 1
    info = citation_check(
        text,
        ["Smith, J. (2024). Marché du cuivre. Revue.", "Dupont, A. (2021). Autre. Journal."],
    )
    assert info.unused == ["Dupont, A. (2021). Autre. Journal."]


def test_citation_check_uncovered_claims_include_number() -> None:
    text = (
        "Le marché du cuivre se resserre nettement depuis peu. "
        "Selon Smith (2024), le resserrement est durable."
    )
    info = citation_check(text, ["Smith, J. (2024). Marché. Revue."])
    assert len(info.uncovered_claims) == 1
    assert info.uncovered_claims[0].startswith("claim 1:")
    assert "cuivre" in info.uncovered_claims[0]


def test_citation_check_covered_claims_not_reported() -> None:
    text = (
        "Selon Smith (2024), le resserrement du marché du cuivre est durable. "
        "Il en conclut que la tendance perdurera selon Smith, 2024."
    )
    info = citation_check(text, ["Smith, J. (2024). Marché. Revue."])
    assert info.uncovered_claims == []
    assert info.unused == []


def test_citation_check_all_unused_without_citations() -> None:
    text = "Une phrase longue de plus de cinq mots sans source du tout."
    info = citation_check(text, [])
    assert info.unused == []
    assert len(info.uncovered_claims) == 1


# ------------------------------------------------------------ homework_steps


def test_homework_derivative_method() -> None:
    h = homework_steps("derivative", "bac+1")
    assert h["problem_type"] == "derivative"
    assert h["level"] == "bac+1"
    assert len(h["steps"]) >= 4
    joined = " ".join(s["action"] for s in h["steps"]).lower()
    assert "dériv" in joined
    assert "règles" in joined


def test_homework_annuity_method() -> None:
    joined = " ".join(s["action"] for s in homework_steps("annuity", "lycée")["steps"]).lower()
    assert "taux périodique" in joined
    assert "valeur" in joined


def test_homework_npv_method() -> None:
    joined = " ".join(s["action"] for s in homework_steps("npv", "bac+2")["steps"]).lower()
    assert "flux" in joined
    assert "actualis" in joined
    assert "taux" in joined


def test_homework_steps_never_contains_final_answer() -> None:
    for ptype in ("derivative", "integral", "annuity", "npv", "statistics", "equation"):
        h = homework_steps(ptype, "bac+3")
        for s in h["steps"]:
            assert set(s) == {"step", "action"}
            # jamais de résultat numérique final dans une étape
            assert re.search(r"=\s*[-+]?\d", s["action"]) is None
        assert "étudiant" in h["note"].lower()


@pytest.mark.parametrize(
    "ptype",
    ["derivative", "integral", "annuity", "npv", "statistics", "equation"],
)
def test_homework_all_types_have_steps(ptype: str) -> None:
    h = homework_steps(ptype, "université")
    assert len(h["steps"]) == 5
    assert [s["step"] for s in h["steps"]] == [1, 2, 3, 4, 5]


def test_homework_unknown_type_error_lists_valid() -> None:
    with pytest.raises(ValueError, match="derivative, integral, annuity, npv, statistics, equation"):
        homework_steps("trigonometry", "lycée")


# ----------------------------------------------------------- paraphrase_check


def test_paraphrase_identical_text_ratio_one() -> None:
    text = (
        "la demande d'électricité augmente fortement pendant l'hiver en europe "
        "selon les dernières données disponibles cette année"
    )
    r = paraphrase_check(text, text)
    assert isinstance(r, ParaphraseCheck)
    assert r.ratio == 1.0
    assert r.verdict == "reuse élevée"


def test_paraphrase_different_text_ratio_near_zero() -> None:
    a = "la demande d'électricité augmente fortement pendant l'hiver en europe aujourd'hui"
    b = "les gravures rupestres des pyrénées montrent des cerfs et des ours renversés"
    r = paraphrase_check(a, b)
    assert r.ratio <= 0.05
    assert r.verdict == "faible"
    assert r.shared_spans == 0


def test_paraphrase_partial_overlap_ratio() -> None:
    a = "un deux trois quatre cinq six sept huit"
    b = "alpha beta un deux trois quatre cinq gamma"
    r = paraphrase_check(a, b)
    assert r.ratio == 0.625
    assert r.verdict == "reuse élevée"
    assert r.shared_spans == 1


def test_paraphrase_short_b_returns_zero() -> None:
    r = paraphrase_check("un deux trois quatre cinq", "un deux trois")
    assert r.ratio == 0.0
    assert r.verdict == "faible"


def test_paraphrase_to_dict() -> None:
    d = to_dict(paraphrase_check("a b", "c d e f g h i j k l"))
    assert d["ratio"] == 0.0
    assert d["verdict"] == "faible"
    assert d["shared_spans"] == 0
