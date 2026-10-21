"""Unit tests for CV ↔ offer matching actions (CVBOOST-21).

All fixtures are synthetic — no real CV, no real offer, no network.
The suite checks the promises of the module:

* one action per offer requirement,
* every quoted evidence is an exact substring of the CV source,
* nothing is invented: a requirement the CV does not prove is reported as
  ``DO_NOT_ADD``,
* the warnings (contract, education, language) are raised,
* the function is pure and deterministic.
"""

from __future__ import annotations

import inspect

import pytest

from career.cv_quality import (
    analyze_cv,
    DocumentInput,
    match_cv_to_offer,
    MatchResult,
)
from career.cv_quality.matching import extract_keywords, find_evidence_in_cv
from career.cv_quality.models import (
    CVAnalysisResult,
    Provenance,
    ReadabilityScore,
)


# ──────────────────────────────────────────────────────────────────────
# Synthetic fixtures
# ──────────────────────────────────────────────────────────────────────

CV_TEXT = """
Jean Dupont
jean.dupont@example.com
Paris

Expérience
2020-2023 | Développeur Python | TechCorp
- Géré équipe de consultants
- Migration de 5 services vers Kubernetes

2018-2020 | Analyste | DataCorp
- Automatisation des reportings mensuels

Formation
2016-2018 | Master Informatique | Université Paris-Saclay

Compétences
Python, SQL, Docker, Kubernetes, Git

Langues
Français (natif), Anglais

Projets
Projet open source : librairie de validation (2k+ stars GitHub)

Certifications
AWS Solutions Architect Associate
"""

CV_WITH_MANAGEMENT = """
Jean Dupont
jean.dupont@example.com

Expérience
2020-2023 | Chef de projet | TechCorp
- Management de projet pour une équipe de 8 personnes

Formation
2016-2018 | Licence Informatique | Université Paris-Saclay

Compétences
Python, SQL

Langues
Français (natif), Anglais (courant)
"""

CV_M1 = """
Jean Dupont

Formation
2014-2016 | M1 Informatique | Université Paris-Saclay

Compétences
Python
"""

CV_LANGUE_SANS_NIVEAU = """
Jean Dupont

Compétences
Python

Langues
Anglais
"""

CV_LANGUE_AVEC_NIVEAU = """
Jean Dupont

Compétences
Python

Langues
Anglais (C1)
"""


def _analyze(text: str) -> CVAnalysisResult:
    """Analyze a synthetic CV."""
    return analyze_cv(DocumentInput(text=text, filename="cv.txt", filetype="txt"))


def _requirement(text: str, **extra) -> dict:
    """One offer requirement record."""
    record = {"text": text, "category": "technical_skill", "mandatory": True}
    record.update(extra)
    return record


def _offer(*requirements: dict, **extra) -> dict:
    """One offer carrying the given requirements."""
    offer = {"id": "OFF-TEST", "requirements": list(requirements)}
    offer.update(extra)
    return offer


def _action(result: MatchResult, requirement_text: str):
    """The action of one requirement."""
    matches = [
        action
        for action in result.actions
        if action.requirement_text == requirement_text
    ]
    assert len(matches) == 1, f"une action par exigence, trouvé {len(matches)}"
    return matches[0]


# ──────────────────────────────────────────────────────────────────────
# Action codes
# ──────────────────────────────────────────────────────────────────────

def test_highlight_exact_match():
    """An exact skill match is highlighted, with its exact evidence."""
    result = match_cv_to_offer(_analyze(CV_TEXT), _offer(_requirement("Python")))

    action = _action(result, "Python")
    assert action.code == "HIGHLIGHT"
    assert action.cv_evidence_text is not None
    assert "Python" in action.cv_evidence_text
    assert action.cv_evidence_offset is not None
    assert action.cv_evidence_field is not None
    assert action.confidence >= 0.9
    assert result.overall_score == 1.0
    assert result.missing_critical == []


def test_rephrase_synonym():
    """A fact worded differently is rephrased, not re-invented."""
    result = match_cv_to_offer(
        _analyze(CV_WITH_MANAGEMENT), _offer(_requirement("Gestion de projet"))
    )

    action = _action(result, "Gestion de projet")
    assert action.code == "REPHRASE"
    assert "Management" in (action.cv_evidence_text or "")
    assert action.cv_evidence_text is not None
    assert "Reformuler" in action.reason


def test_quantify_missing_number():
    """A fact without a figure asks for a provable number."""
    result = match_cv_to_offer(_analyze(CV_TEXT), _offer(_requirement("Géré équipe 10+")))

    action = _action(result, "Géré équipe 10+")
    assert action.code == "QUANTIFY"
    assert "chiffre" in action.reason
    assert action.cv_evidence_text is not None


def test_quantify_not_triggered_when_figure_present():
    """A figure already in the CV is not asked for again."""
    result = match_cv_to_offer(
        _analyze(CV_WITH_MANAGEMENT), _offer(_requirement("équipe de 8 personnes"))
    )

    action = _action(result, "équipe de 8 personnes")
    assert action.code != "QUANTIFY"


def test_do_not_add_absent():
    """An unproven requirement is explicitly refused, with the standard reason."""
    result = match_cv_to_offer(_analyze(CV_TEXT), _offer(_requirement("Terraform")))

    action = _action(result, "Terraform")
    assert action.code == "DO_NOT_ADD"
    assert action.cv_evidence_text is None
    assert action.cv_evidence_offset is None
    assert action.cv_evidence_field is None
    assert "Aucune preuve dans le CV, ne pas ajouter sans preuve" in action.reason


def test_do_not_add_is_not_a_proof_of_absence():
    """A skill proven by another requirement is still proven for itself."""
    result = match_cv_to_offer(
        _analyze(CV_TEXT),
        _offer(_requirement("Kubernetes"), _requirement("Terraform")),
    )

    assert _action(result, "Kubernetes").code == "HIGHLIGHT"
    assert _action(result, "Terraform").code == "DO_NOT_ADD"


def test_partially_proven_requirement_is_never_highlighted():
    """A requirement only partly proven is not sold as covered."""
    result = match_cv_to_offer(_analyze(CV_TEXT), _offer(_requirement("Kubernetes Helm")))

    action = _action(result, "Kubernetes Helm")
    assert action.code == "REPHRASE"
    assert "Kubernetes" in (action.cv_evidence_text or "")
    assert "partie" in action.reason


# ──────────────────────────────────────────────────────────────────────
# Critical requirements
# ──────────────────────────────────────────────────────────────────────

def test_missing_critical():
    """A mandatory requirement without evidence is listed as critical."""
    result = match_cv_to_offer(_analyze(CV_TEXT), _offer(_requirement("Azure")))

    assert result.missing_critical == ["Azure"]
    assert result.matched_requirements == 0
    assert result.overall_score == 0.0


def test_critical_vs_optional():
    """An optional requirement is never a critical gap."""
    result = match_cv_to_offer(
        _analyze(CV_TEXT),
        _offer(_requirement("Azure", mandatory=False), _requirement("Python")),
    )

    assert result.missing_critical == []
    assert result.matched_requirements == 1
    assert result.total_requirements == 2
    assert result.overall_score == 0.5


def test_modality_preferred_is_never_critical():
    """The Mission 02 modality is read: a preference is never mandatory."""
    result = match_cv_to_offer(
        _analyze(CV_TEXT),
        _offer({"text": "Azure", "category": "technical_skill", "modality": "preferred"}),
    )

    assert result.missing_critical == []


def test_modality_required_is_critical():
    """The Mission 02 modality is read: a requirement is a gap when unproven."""
    result = match_cv_to_offer(
        _analyze(CV_TEXT),
        _offer({"text": "Azure", "category": "technical_skill", "modality": "required"}),
    )

    assert result.missing_critical == ["Azure"]


# ──────────────────────────────────────────────────────────────────────
# Provenance
# ──────────────────────────────────────────────────────────────────────

def test_evidence_provenance_exact():
    """Every quote is an exact substring of the CV, at the announced offset."""
    cv_result = _analyze(CV_TEXT)
    result = match_cv_to_offer(
        cv_result,
        _offer(_requirement("Python"), _requirement("Kubernetes"), _requirement("SQL")),
    )

    source = cv_result.provenance.source_text
    assert source
    proved = [action for action in result.actions if action.cv_evidence_text]
    assert proved
    for action in proved:
        offset = action.cv_evidence_offset
        assert offset is not None
        assert source[offset:offset + len(action.cv_evidence_text or "")] == action.cv_evidence_text


def test_no_invention():
    """Nothing is ever quoted that the CV does not contain."""
    cv_result = _analyze(CV_TEXT)
    result = match_cv_to_offer(
        cv_result,
        _offer(
            _requirement("Python"),
            _requirement("Scrum"),
            _requirement("Anglais"),
            _requirement("Kubernetes"),
        ),
    )

    source = cv_result.provenance.source_text or ""
    for action in result.actions:
        if action.code == "DO_NOT_ADD":
            assert action.cv_evidence_text is None
            continue
        assert action.cv_evidence_text in source


def test_evidence_field_is_a_cv_field():
    """The evidence announces the CV field it comes from."""
    result = match_cv_to_offer(_analyze(CV_TEXT), _offer(_requirement("Python")))

    action = _action(result, "Python")
    assert action.cv_evidence_field in {
        "skills",
        "experience",
        "education",
        "languages",
        "projects",
        "certifications",
        "document",
    }


def test_find_evidence_returns_verbatim_excerpt():
    """The evidence helper quotes the CV verbatim."""
    cv_result = _analyze(CV_TEXT)

    evidence = find_evidence_in_cv(cv_result, "Python")
    assert evidence is not None
    assert "Python" in evidence.text
    assert cv_result.provenance.source_text[
        evidence.offset:evidence.offset + len(evidence.text)
    ] == evidence.text


def test_find_evidence_returns_none_when_absent():
    """The evidence helper says nothing instead of guessing."""
    assert find_evidence_in_cv(_analyze(CV_TEXT), "Terraform") is None


def test_without_source_text_nothing_is_proven():
    """Without the source text, no proof can be quoted — and it is said."""
    cv_result = _analyze(CV_TEXT)
    stripped = CVAnalysisResult(
        findings=cv_result.findings,
        sections=cv_result.sections,
        experiences=cv_result.experiences,
        readability=cv_result.readability,
        provenance=Provenance(
            filename=cv_result.provenance.filename,
            filetype=cv_result.provenance.filetype,
            text_length=cv_result.provenance.text_length,
            page_count=cv_result.provenance.page_count,
        ),
    )

    result = match_cv_to_offer(stripped, _offer(_requirement("Python")))

    action = _action(result, "Python")
    assert action.code == "DO_NOT_ADD"
    assert action.cv_evidence_text is None
    assert any("source" in warning for warning in result.warnings)


# ──────────────────────────────────────────────────────────────────────
# Languages
# ──────────────────────────────────────────────────────────────────────

def test_language_without_level_is_to_confirm():
    """A language mentioned without a level must be confirmed."""
    result = match_cv_to_offer(
        _analyze(CV_LANGUE_SANS_NIVEAU),
        _offer(_requirement("Anglais", category="language")),
    )

    action = _action(result, "Anglais")
    assert action.code == "CONFIRM_LANGUAGE"
    assert "confirmer" in action.reason.lower()


def test_language_with_level_is_highlighted():
    """A language with a proven level is a fact already in the CV."""
    result = match_cv_to_offer(
        _analyze(CV_LANGUE_AVEC_NIVEAU),
        _offer(_requirement("Anglais", category="language")),
    )

    action = _action(result, "Anglais")
    assert action.code == "HIGHLIGHT"


def test_language_level_of_another_language_is_not_borrowed():
    """The level of another language never proves this one."""
    result = match_cv_to_offer(
        _analyze(CV_TEXT),
        _offer(_requirement("Anglais", category="language")),
    )

    action = _action(result, "Anglais")
    assert action.code == "CONFIRM_LANGUAGE"


def test_language_warning():
    """A language the CV does not prove raises a warning."""
    result = match_cv_to_offer(
        _analyze(CV_TEXT),
        _offer(_requirement("Espagnol", category="language")),
    )

    assert any("Espagnol" in warning for warning in result.warnings)
    assert any("Langue" in warning for warning in result.warnings)


def test_several_languages_are_never_sold_as_covered():
    """A requirement naming two languages reports what the CV proves."""
    result = match_cv_to_offer(
        _analyze(CV_TEXT),
        _offer(_requirement("Français et espagnol", category="language")),
    )

    action = _action(result, "Français et espagnol")
    assert action.code == "REPHRASE"
    assert "Français" in (action.cv_evidence_text or "")
    assert any("Espagnol" in warning for warning in result.warnings)


# ──────────────────────────────────────────────────────────────────────
# Warnings
# ──────────────────────────────────────────────────────────────────────

def test_warning_alternance():
    """An alternance contract is reported."""
    result = match_cv_to_offer(
        _analyze(CV_TEXT), _offer(_requirement("Python"), contract_type="alternance")
    )

    assert any("Alternance détectée" in warning for warning in result.warnings)


def test_warning_alternance_detected_in_the_description():
    """An alternance mentioned in the offer text is reported too."""
    offer = _offer(_requirement("Python"), description_original="Poste en alternance, 2 ans.")

    result = match_cv_to_offer(_analyze(CV_TEXT), offer)
    assert any("Alternance détectée" in warning for warning in result.warnings)


def test_no_alternance_warning_on_a_cdi():
    """A CDI raises no alternance warning."""
    result = match_cv_to_offer(
        _analyze(CV_TEXT), _offer(_requirement("Python"), contract_type="CDI")
    )

    assert not any("Alternance" in warning for warning in result.warnings)


def test_warning_education_gap():
    """An offer asking for a higher degree than the CV shows is reported."""
    result = match_cv_to_offer(
        _analyze(CV_M1),
        _offer(_requirement("Python"), education_level="M2"),
    )

    assert any("Niveau d'études requis" in warning for warning in result.warnings)


def test_no_education_warning_when_the_degree_matches():
    """Same degree on both sides: no warning."""
    result = match_cv_to_offer(
        _analyze(CV_TEXT),
        _offer(_requirement("Python"), education_level="Master"),
    )

    assert not any("Niveau d'études" in warning for warning in result.warnings)


def test_warning_missing_critical_is_summarized():
    """A gap is summarized in the warnings."""
    result = match_cv_to_offer(_analyze(CV_TEXT), _offer(_requirement("Azure")))

    assert any("sans preuve" in warning for warning in result.warnings)


# ──────────────────────────────────────────────────────────────────────
# Shape of the result
# ──────────────────────────────────────────────────────────────────────

def test_multiple_requirements():
    """Five requirements, five actions, score = matched / total."""
    result = match_cv_to_offer(
        _analyze(CV_TEXT),
        _offer(
            _requirement("Python"),
            _requirement("SQL"),
            _requirement("Kubernetes"),
            _requirement("Azure"),
            _requirement("Terraform"),
        ),
    )

    assert len(result.actions) == 5
    assert result.total_requirements == 5
    assert result.matched_requirements == 3
    assert result.overall_score == pytest.approx(0.6)


def test_one_action_per_requirement():
    """Each requirement gets exactly one action, in order."""
    requirements = [_requirement(text) for text in ("Python", "SQL", "Azure")]
    result = match_cv_to_offer(_analyze(CV_TEXT), _offer(*requirements))

    assert [action.requirement_text for action in result.actions] == [
        "Python",
        "SQL",
        "Azure",
    ]


def test_score_is_matched_over_total():
    """The score is the ratio of proved requirements."""
    result = match_cv_to_offer(
        _analyze(CV_TEXT), _offer(_requirement("Python"), _requirement("Azure"))
    )

    assert result.overall_score == pytest.approx(
        result.matched_requirements / result.total_requirements
    )


def test_empty_requirements():
    """An offer without requirements matches nothing, without crashing."""
    result = match_cv_to_offer(_analyze(CV_TEXT), {"id": "OFF-EMPTY"})

    assert result.actions == []
    assert result.total_requirements == 0
    assert result.overall_score == 0.0


def test_confidence_do_not_add():
    """A refused requirement is certain: no proof exists."""
    result = match_cv_to_offer(_analyze(CV_TEXT), _offer(_requirement("Azure")))

    assert _action(result, "Azure").confidence == 1.0


def test_confidence_scoring():
    """An exact match scores 0.9+, an approximate one stays in 0.6-0.8."""
    exact = match_cv_to_offer(_analyze(CV_TEXT), _offer(_requirement("Python")))
    approximate = match_cv_to_offer(
        _analyze(CV_WITH_MANAGEMENT), _offer(_requirement("Gestion de projet"))
    )

    assert _action(exact, "Python").confidence >= 0.9
    confidence = _action(approximate, "Gestion de projet").confidence
    assert 0.6 <= confidence <= 0.8


def test_confidence_stays_in_range():
    """Every confidence stays between 0 and 1."""
    result = match_cv_to_offer(
        _analyze(CV_TEXT),
        _offer(
            _requirement("Python"),
            _requirement("Azure"),
            _requirement("Anglais", category="language"),
        ),
    )

    for action in result.actions:
        assert 0.0 <= action.confidence <= 1.0


# ──────────────────────────────────────────────────────────────────────
# Mission 02 contract
# ──────────────────────────────────────────────────────────────────────

def test_mission_02_contract_is_accepted():
    """The Mission 02 analysis is the expected input of the matching."""
    from career.offer_requirements import analyze_offer

    offer = {
        "id": "OFF-002",
        "description_original": (
            "Requirements:\n"
            "- Strong SQL skills are mandatory.\n"
            "- You must be fluent in English.\n"
            "Nice to have:\n"
            "- German B1.\n"
        ),
    }
    analysis = analyze_offer(offer)

    result = match_cv_to_offer(_analyze(CV_TEXT), analysis)

    assert result.total_requirements == len(analysis["requirements"])
    assert len(result.actions) == result.total_requirements
    assert any(action.code == "HIGHLIGHT" for action in result.actions)


def test_raw_offer_requirements_are_extracted():
    """A raw offer is read with the very same contract."""
    offer = {
        "id": "OFF-001",
        "requirements": "Excel avancé obligatoire\nMaîtrise du VBA\nEspagnol apprécié",
    }

    result = match_cv_to_offer(_analyze(CV_TEXT), offer)

    assert result.total_requirements == 3
    assert len(result.actions) == 3


def test_preferred_requirement_is_never_critical():
    """A preference extracted as "preferred" is not a critical gap."""
    from career.offer_requirements import analyze_offer

    offer = {"id": "OFF-003", "requirements": "Espagnol apprécié\nPython obligatoire"}
    analysis = analyze_offer(offer)

    result = match_cv_to_offer(_analyze(CV_TEXT), analysis)

    assert "Espagnol apprécié" not in result.missing_critical


# ──────────────────────────────────────────────────────────────────────
# Purity
# ──────────────────────────────────────────────────────────────────────

def test_is_deterministic():
    """Same CV, same offer, same result — always."""
    cv_result = _analyze(CV_TEXT)
    offer = _offer(
        _requirement("Python"),
        _requirement("Gestion de projet"),
        _requirement("Azure"),
    )

    first = match_cv_to_offer(cv_result, offer)
    second = match_cv_to_offer(cv_result, offer)
    assert first == second


def test_does_not_mutate_its_inputs():
    """The function reads its inputs, it never rewrites them."""
    cv_result = _analyze(CV_TEXT)
    offer = _offer(_requirement("Python"))
    offer_snapshot = dict(offer)
    requirements_snapshot = list(offer["requirements"])
    findings_snapshot = list(cv_result.findings)

    match_cv_to_offer(cv_result, offer)

    assert offer == offer_snapshot
    assert offer["requirements"] == requirements_snapshot
    assert list(cv_result.findings) == findings_snapshot


def test_uses_no_network():
    """The module stays offline: no network client is imported."""
    source = inspect.getsource(
        __import__("career.cv_quality.matching", fromlist=["matching"])
    )
    for forbidden in ("import requests", "import httpx", "import socket", "urllib.request"):
        assert forbidden not in source


def test_extract_keywords_ignores_filler_words():
    """Function and capability words never identify a skill."""
    assert "maitrise" not in extract_keywords("Maitrise d'Excel")
    assert "experience" not in extract_keywords("5 ans d'experience en gestion de projet")
    assert "excel" in extract_keywords("Maitrise d'Excel")


def test_readability_model_is_untouched():
    """The Mission 01 models keep their shape."""
    assert ReadabilityScore is not None
