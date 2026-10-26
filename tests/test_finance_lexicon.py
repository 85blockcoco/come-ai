"""Offline contract tests for the local finance lexicon (CVBOOST-76 / SPEC-041)."""

from __future__ import annotations

import pytest

from career import finance_lexicon as lex


def test_lexicon_version_is_declared() -> None:
    assert lex.LEXICON_VERSION


def test_expand_detects_role_with_french_accent_and_punctuation() -> None:
    result = lex.expand("Nous cherchons un Analyste M&A confirmé (F/H).")
    assert result["matches"], result
    assert any(match["canonical"] == "M&A Analyst" for match in result["matches"])
    assert "m&a" in result["familles"]


def test_expand_is_case_and_accent_insensitive() -> None:
    upper = lex.expand("ANALYSTE M&A")
    accented = lex.expand("Analyste M&A")
    assert upper["matches"] == accented["matches"]


def test_expand_dedupes_repeated_aliases() -> None:
    text = "Analyste M&A puis encore analyste m&a et Analyste M&A"
    matches = lex.expand(text)["matches"]
    role_matches = [match for match in matches if match["canonical"] == "M&A Analyst"]
    assert len(role_matches) == 1


def test_expand_on_empty_and_none_text_is_safe() -> None:
    for empty in ("", None, "   "):
        result = lex.expand(empty)
        assert result["matches"] == []
        assert result["familles"] == []
        assert result["counts"] == {kind: 0 for kind in lex.KINDS}


def test_expand_aggregates_sorted_families() -> None:
    result = lex.expand("Poste risk quant à Londres, CFA bienvenu, due diligence")
    assert result["familles"] == sorted(result["familles"])
    assert set(result["familles"]) == {"risk", "quant", "offices", "certifications", "anglicisms"}


def test_expand_detects_skills_with_synonyms() -> None:
    for text, canonical in (
        ("maîtrise du terminal Bloomberg", "Bloomberg"),
        ("valuation DCF et comparables", "DCF"),
        ("SQL et Python/pandas", "SQL"),
        ("S&P Capital IQ au quotidien", "S&P Capital IQ"),
    ):
        matches = lex.expand(text)["matches"]
        assert any(match["canonical"] == canonical for match in matches), (text, matches)


def test_expand_detects_certification_levels() -> None:
    result = lex.expand("CFA Level 2 en cours")
    certifications = [match["canonical"] for match in result["matches"] if match["kind"] == "certification"]
    assert certifications == ["CFA"]


def test_expand_detects_offices_with_french_spellings() -> None:
    result = lex.expand("Bureaux de Londres et Francfort")
    offices = {match["canonical"] for match in result["matches"] if match["kind"] == "office"}
    assert offices == {"London", "Frankfurt"}


def test_expand_detects_common_anglicisms() -> None:
    result = lex.expand("Appui sur la data room, term sheet et roadshow")
    anglicisms = {match["canonical"] for match in result["matches"] if match["kind"] == "anglicism"}
    assert {"data room", "term sheet", "roadshow"} <= anglicisms


def test_expand_matches_are_stable_and_sorted() -> None:
    text = "M&A analyst, CFA, Paris, LBO, comps"
    first = lex.expand(text)
    second = lex.expand(text)
    assert first == second
    keys = [(match["kind"], match["canonical"], match["alias"]) for match in first["matches"]]
    assert keys == sorted(keys)


def test_expand_counts_by_kind() -> None:
    counts = lex.expand("M&A analyst CFA Paris")["counts"]
    assert counts["role"] == 1
    assert counts["certification"] == 1
    assert counts["office"] == 1


def test_resolve_role_accepts_aliases_and_returns_canonical() -> None:
    for alias in ("M&A Analyst", "analyste m&a", "fusions acquisitions", "m & a"):
        assert lex.resolve_role(alias) == "M&A Analyst"


def test_resolve_role_never_guesses_unknown_roles() -> None:
    assert lex.resolve_role("Développeur web") == ""
    assert lex.resolve_role("") == ""
    assert lex.resolve_role(None) == ""


def test_score_profile_rewards_full_profile() -> None:
    profile = (
        "Stage M&A : valorisation DCF, analyse de comps et merger model, "
        "modélisation financière avancée, Excel et VBA. CFA niveau 1 validé."
    )
    score = lex.score_profile(profile, "M&A Analyst")
    assert score["role"] == "M&A Analyst"
    assert score["missing"] == []
    assert score["coverage"] == 1.0
    assert score["certifications"] == {"CFA": True}


def test_score_profile_empty_profile_scores_zero() -> None:
    requirements = lex.ROLE_REQUIREMENTS["Risk Analyst"]
    score = lex.score_profile("", "Risk Analyst")
    assert score["coverage"] == 0.0
    assert len(score["missing"]) == len(requirements["skills"])
    assert score["certifications"] == {"PRM": False}


def test_score_profile_clamps_between_zero_and_one() -> None:
    partial = lex.score_profile("J'utilise Excel et VBA", "Treasury Analyst")
    assert 0.0 <= partial["coverage"] <= 1.0


def test_score_profile_raises_on_unknown_role() -> None:
    with pytest.raises(LookupError):
        lex.score_profile("DCF partout", "Astronaute")


def test_keywords_for_returns_deduped_deterministic_list() -> None:
    first = lex.keywords_for("M&A Analyst")
    second = lex.keywords_for("analyste m&a")
    assert first == second
    lowered = [term.lower() for term in first]
    assert len(lowered) == len(set(lowered))
    assert "DCF" in first


def test_keywords_for_raises_on_unknown_role() -> None:
    with pytest.raises(LookupError):
        lex.keywords_for("Vendeur de tiles")


def test_role_requirements_reference_existing_skills_and_certifications() -> None:
    for role, requirements in lex.ROLE_REQUIREMENTS.items():
        assert role in lex.ROLES, role
        for skill in requirements["skills"]:
            assert skill in lex.SKILLS, (role, skill)
        for certification in requirements["certifications"]:
            assert certification in lex.CERTIFICATIONS, (role, certification)


def test_lexicon_entries_are_wellformed() -> None:
    for canonical, (family, aliases) in lex.ROLES.items():
        assert family in lex.FAMILIES, canonical
        assert aliases, canonical
    for table in (lex.SKILLS, lex.CERTIFICATIONS, lex.OFFICES, lex.ANGLICISMS):
        for canonical, aliases in table.items():
            assert canonical and aliases, canonical


def test_no_network_module_is_imported() -> None:
    source = (lex.__file__ or "").rsplit("/", 1)[-1]
    assert source == "finance_lexicon.py"
    imported = set(lex.__dict__) | set()
    assert not any(name in imported for name in ("requests", "urllib", "socket", "http"))
    assert "import requests" not in open(lex.__file__).read()
    assert "urllib" not in open(lex.__file__).read()


def test_expand_family_labels_use_documented_names() -> None:
    known = set(lex.FAMILIES) | {"skills", "certifications", "offices", "anglicisms"}
    result = lex.expand("M&A analyst, CFA, Paris, DCF, due diligence")
    assert set(result["familles"]) <= known
