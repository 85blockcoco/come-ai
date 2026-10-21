"""Unit tests for the CV ↔ offer matching (CVBOOST-21).

All fixtures are synthetic — no real CV, no real offer, no network call.
The suite checks the product contract: one action per requirement, verbatim
evidence (exact substring + offset + field), no invention, and the
cross-cutting warnings.
"""

from __future__ import annotations

import pytest

from career.cv_quality import (
    analyze_cv,
    DocumentInput,
    match_cv_to_offer,
)
from career.cv_quality.matching import (
    ALTERNANCE_WARNING,
    DO_NOT_ADD_REASON,
    NO_SOURCE_WARNING,
    extract_keywords,
    find_evidence_in_cv,
)
from career.cv_quality.models import MatchResult


# ──────────────────────────────────────────────────────────────────────
# Synthetic fixtures
# ──────────────────────────────────────────────────────────────────────

CV_TEXT = """Jean Dupont
test.user@example.com
Paris, France

Expérience
2020-2023 | Développeur Python | TechCorp
- Migration de 5 services vers Kubernetes
- Augmentation du trafic API de 30% en 6 mois
- Géré une équipe de prestataires
- Management de projet international

Formation
2018-2020 | Master Informatique | Université Paris-Saclay

Compétences
Python, SQL, Docker, Kubernetes, Excel VBA

Langues
Français (natif), Anglais (courant)

Projets
Projet open source : librairie de validation

Certifications
Certified Scrum Master
"""

CV_WITHOUT_ENGLISH = """Jean Dupont
test.user@example.com
Paris, France

Expérience
2020-2023 | Développeur Python | TechCorp
- Migration de 5 services vers Kubernetes

Formation
2018-2020 | Licence Informatique | Université Paris-Saclay

Compétences
Python, SQL, Docker

Langues
Français (natif)

Projets
Projet open source : librairie de validation
"""


def _cv(text: str = CV_TEXT):
    """Analyze a synthetic CV with the real Mission 01 pipeline."""
    return analyze_cv(DocumentInput(text=text, filename="cv.txt", filetype="txt"))


def _requirement(text: str, **kwargs) -> dict:
    """One requirement record, Mission 02 shaped."""
    record = {"text": text}
    record.update(kwargs)
    return record


def _offer(*requirements: dict, **kwargs) -> dict:
    """One offer holding the given requirements."""
    offer = {"id": "offre-1", "requirements": list(requirements)}
    offer.update(kwargs)
    return offer


# ──────────────────────────────────────────────────────────────────────
# Matching — core behaviour
# ──────────────────────────────────────────────────────────────────────


def test_highlight_exact_match():
    """A skill written the same way in the CV and in the offer is highlighted."""
    result = match_cv_to_offer(_cv(), _offer(_requirement("Python", category="skill")))

    assert result.total_requirements == 1
    assert result.matched_requirements == 1
    assert len(result.actions) == 1
    action = result.actions[0]
    assert action.code == "HIGHLIGHT"
    assert action.requirement_text == "Python"
    assert action.cv_evidence_text is not None
    assert "Python" in action.cv_evidence_text
    assert action.cv_evidence_offset is not None
    assert action.cv_evidence_field == "experience"


def test_rephrase_synonym():
    """The same fact worded differently asks for a reformulation."""
    result = match_cv_to_offer(
        _cv(),
        _offer(_requirement("Gestion de projet", category="skill")),
    )

    action = result.actions[0]
    assert action.code == "REPHRASE"
    assert action.cv_evidence_text is not None
    assert "Management de projet" in action.cv_evidence_text
    assert "Gestion de projet" in action.reason


def test_quantify_missing_number():
    """A requirement with a figure and a CV without one asks for a figure."""
    result = match_cv_to_offer(
        _cv(),
        _offer(_requirement("Géré équipe 10+", category="skill")),
    )

    action = result.actions[0]
    assert action.code == "QUANTIFY"
    assert action.cv_evidence_text is not None
    assert "chiffre" in action.reason


def test_do_not_add_absent():
    """A requirement the CV does not prove is never invented."""
    result = match_cv_to_offer(_cv(), _offer(_requirement("AWS", category="skill")))

    action = result.actions[0]
    assert action.code == "DO_NOT_ADD"
    assert action.cv_evidence_text is None
    assert action.cv_evidence_offset is None
    assert action.cv_evidence_field is None
    assert action.reason == DO_NOT_ADD_REASON
    assert "Aucune preuve dans le CV, ne pas ajouter sans preuve" in action.reason


def test_missing_critical():
    """A mandatory requirement without evidence is listed as missing."""
    result = match_cv_to_offer(
        _cv(),
        _offer(_requirement("AWS", category="skill", modality="required")),
    )

    assert result.missing_critical == ["AWS"]
    assert result.matched_requirements == 0
    assert result.overall_score == 0.0


def test_critical_vs_optional():
    """An optional requirement is missing but never critical."""
    result = match_cv_to_offer(
        _cv(),
        _offer(
            _requirement("AWS", category="skill", modality="preferred"),
            _requirement("Kafka", category="skill", modality="required"),
        ),
    )

    assert result.missing_critical == ["Kafka"]
    assert len(result.actions) == 2
    assert all(action.code == "DO_NOT_ADD" for action in result.actions)


def test_multiple_requirements():
    """Five requirements give five actions and a matched/total score."""
    result = match_cv_to_offer(
        _cv(),
        _offer(
            _requirement("Python", category="skill"),
            _requirement("SQL", category="skill"),
            _requirement("Docker", category="skill"),
            _requirement("AWS", category="skill"),
            _requirement("Kafka", category="skill"),
        ),
    )

    assert len(result.actions) == 5
    assert result.total_requirements == 5
    assert result.matched_requirements == 3
    assert result.overall_score == pytest.approx(3 / 5)


def test_one_action_per_requirement():
    """Exactly one action per requirement, in requirement order."""
    requirements = [
        _requirement("Python", category="skill"),
        _requirement("Anglais", category="language"),
        _requirement("Master", category="education"),
        _requirement("CDI", category="contract"),
    ]
    result = match_cv_to_offer(_cv(), _offer(*requirements))

    assert [action.requirement_text for action in result.actions] == [
        "Python",
        "Anglais",
        "Master",
        "CDI",
    ]
    assert result.total_requirements == len(result.actions)


def test_requirement_text_is_verbatim():
    """The requirement text is copied exactly from the offer."""
    text = "Maîtrise de Python (5 ans d'expérience)"
    result = match_cv_to_offer(_cv(), _offer(_requirement(text, category="skill")))

    assert result.actions[0].requirement_text == text


def test_no_requirements():
    """An offer without requirement gives an empty, honest result."""
    result = match_cv_to_offer(_cv(), {"id": "offre-1"})

    assert result.actions == []
    assert result.total_requirements == 0
    assert result.matched_requirements == 0
    assert result.overall_score == 0.0


# ──────────────────────────────────────────────────────────────────────
# Provenance
# ──────────────────────────────────────────────────────────────────────


def test_evidence_provenance_exact():
    """The quoted evidence is an exact substring of the CV, at its offset."""
    cv = _cv()
    result = match_cv_to_offer(cv, _offer(_requirement("Kubernetes", category="skill")))

    action = result.actions[0]
    assert action.cv_evidence_text is not None
    assert action.cv_evidence_offset is not None
    source = cv.provenance.source_text
    assert source is not None
    assert source[action.cv_evidence_offset:].startswith(action.cv_evidence_text)


def test_no_invention():
    """Every quoted evidence is a substring of the CV source — nothing else."""
    cv = _cv()
    requirements = [
        _requirement("Python", category="skill"),
        _requirement("Anglais", category="language"),
        _requirement("AWS", category="skill"),
        _requirement("Gestion de projet", category="skill"),
    ]
    result = match_cv_to_offer(cv, _offer(*requirements))
    source = cv.provenance.source_text or ""

    for action in result.actions:
        if action.cv_evidence_text is None:
            assert action.code == "DO_NOT_ADD"
            continue
        assert action.cv_evidence_text in source
        assert action.cv_evidence_offset is not None
        assert source[action.cv_evidence_offset:].startswith(action.cv_evidence_text)


def test_evidence_field_is_a_known_section():
    """The evidence field names the CV section that holds the proof."""
    result = match_cv_to_offer(
        _cv(),
        _offer(
            _requirement("VBA", category="skill"),
            _requirement("Master", category="education"),
            _requirement("Anglais", category="language"),
            _requirement("Kubernetes", category="skill"),
        ),
    )
    fields = {action.requirement_text: action.cv_evidence_field for action in result.actions}

    assert fields["VBA"] == "skills"
    assert fields["Master"] == "education"
    assert fields["Anglais"] == "languages"
    assert fields["Kubernetes"] == "experience"


def test_confidence_scoring():
    """An exact match scores high, an approximate match stays in the middle."""
    exact = match_cv_to_offer(_cv(), _offer(_requirement("Python", category="skill")))
    approximate = match_cv_to_offer(
        _cv(),
        _offer(_requirement("Gestion de projet", category="skill")),
    )

    assert exact.actions[0].confidence >= 0.9
    assert 0.6 <= approximate.actions[0].confidence <= 0.8


def test_confidence_do_not_add():
    """A requirement without proof is certain: confidence 1.0."""
    result = match_cv_to_offer(_cv(), _offer(_requirement("AWS", category="skill")))

    assert result.actions[0].confidence == 1.0


def test_find_evidence_in_cv_is_none_without_proof():
    """The evidence helper never invents a proof."""
    cv = _cv()

    assert find_evidence_in_cv(cv, "AWS") is None
    assert find_evidence_in_cv(cv, "Python") is not None


def test_extract_keywords_drops_capability_words():
    """Capability words qualify a skill, they never identify it."""
    assert extract_keywords("Maîtrise de Python") == ["python"]
    assert extract_keywords("3 ans d'expérience en Python") == ["python"]


# ──────────────────────────────────────────────────────────────────────
# Warnings
# ──────────────────────────────────────────────────────────────────────


def test_warning_alternance():
    """An alternance offer is flagged."""
    result = match_cv_to_offer(
        _cv(),
        _offer(_requirement("Python", category="skill"), contract_type="alternance"),
    )

    assert ALTERNANCE_WARNING in result.warnings
    assert any("Alternance" in warning for warning in result.warnings)


def test_warning_education_gap():
    """A level required above the CV level is flagged."""
    cv = _cv(CV_WITHOUT_ENGLISH)
    result = match_cv_to_offer(
        cv,
        _offer(_requirement("Python", category="skill"), education_level="master"),
    )

    assert any("Niveau d'études" in warning for warning in result.warnings)
    assert any(">" in warning for warning in result.warnings)


def test_no_education_warning_when_levels_match():
    """A level required below the CV level raises no warning."""
    result = match_cv_to_offer(
        _cv(),
        _offer(_requirement("Python", category="skill"), education_level="licence"),
    )

    assert not any("Niveau d'études" in warning for warning in result.warnings)


def test_language_warning():
    """A required language the CV does not prove is flagged."""
    result = match_cv_to_offer(
        _cv(CV_WITHOUT_ENGLISH),
        _offer(_requirement("Anglais", category="language", modality="required")),
    )

    assert any("Langue" in warning for warning in result.warnings)
    assert result.missing_critical == ["Anglais"]


def test_confirm_language_when_level_missing():
    """A language mentioned without any level must be confirmed, not asserted."""
    result = match_cv_to_offer(
        _cv(CV_WITHOUT_ENGLISH.replace("Français (natif)", "Anglais")),
        _offer(_requirement("Anglais", category="language")),
    )

    action = result.actions[0]
    assert action.code == "CONFIRM_LANGUAGE"
    assert action.cv_evidence_text is not None
    assert "confirmer" in action.reason.lower()


def test_language_with_level_is_highlighted():
    """A language proven with its level is simply highlighted."""
    result = match_cv_to_offer(
        _cv(),
        _offer(_requirement("Anglais", category="language")),
    )

    action = result.actions[0]
    assert action.code == "HIGHLIGHT"
    assert action.cv_evidence_field == "languages"


def test_language_proof_is_the_line_that_proves_the_level():
    """The quoted line is the one that proves the level, not a passing mention."""
    cv_text = CV_TEXT.replace(
        "- Management de projet international",
        "- Management de projet international pour un client anglais",
    )
    result = match_cv_to_offer(
        _cv(cv_text),
        _offer(_requirement("Anglais", category="language")),
    )

    action = result.actions[0]
    assert action.code == "HIGHLIGHT"
    assert action.cv_evidence_field == "languages"
    assert "courant" in (action.cv_evidence_text or "")


def test_warning_without_source_text():
    """Without the source text, nothing is quoted and the warning says so."""
    cv = _cv()
    without_source = type(cv)(
        findings=cv.findings,
        sections=cv.sections,
        experiences=cv.experiences,
        readability=cv.readability,
        provenance=type(cv.provenance)(
            filename=cv.provenance.filename,
            filetype=cv.provenance.filetype,
            text_length=cv.provenance.text_length,
            page_count=cv.provenance.page_count,
        ),
    )

    result = match_cv_to_offer(without_source, _offer(_requirement("Python", category="skill")))

    assert NO_SOURCE_WARNING in result.warnings
    assert result.actions[0].code == "DO_NOT_ADD"
    assert result.actions[0].cv_evidence_text is None


# ──────────────────────────────────────────────────────────────────────
# Offer shapes
# ──────────────────────────────────────────────────────────────────────


def test_requirements_as_plain_strings():
    """A plain list of requirement strings is accepted."""
    result = match_cv_to_offer(_cv(), {"id": "offre-1", "requirements": ["Python", "AWS"]})

    assert [action.requirement_text for action in result.actions] == ["Python", "AWS"]
    assert result.actions[0].code == "HIGHLIGHT"
    assert result.actions[1].code == "DO_NOT_ADD"


def test_requirements_as_text_block():
    """A requirements block written as text is split into statements."""
    result = match_cv_to_offer(
        _cv(),
        {"id": "offre-1", "requirements": "Python\n- SQL\n- Kafka"},
    )

    assert [action.requirement_text for action in result.actions] == ["Python", "SQL", "Kafka"]


def test_mission_02_modality_drives_mandatory():
    """The Mission 02 modality decides what is mandatory."""
    result = match_cv_to_offer(
        _cv(),
        _offer(
            _requirement("AWS", category="skill", modality="required"),
            _requirement("Kafka", category="skill", modality="preferred"),
            _requirement("Spark", category="skill", modality="contextual"),
        ),
    )

    assert result.missing_critical == ["AWS"]


def test_explicit_mandatory_flag_wins_over_modality():
    """An explicit mandatory flag is honoured."""
    result = match_cv_to_offer(
        _cv(),
        _offer(_requirement("AWS", category="skill", modality="preferred", mandatory=True)),
    )

    assert result.missing_critical == ["AWS"]


def test_requirement_without_modality_is_mandatory():
    """A requirement nobody qualified is a requirement."""
    result = match_cv_to_offer(_cv(), _offer(_requirement("AWS", category="skill")))

    assert result.missing_critical == ["AWS"]


def test_preferred_language_does_not_warn():
    """A language the offer only appreciates raises no warning."""
    result = match_cv_to_offer(
        _cv(CV_WITHOUT_ENGLISH),
        _offer(_requirement("Anglais", category="language", modality="preferred")),
    )

    assert result.warnings == []
    assert result.actions[0].code == "DO_NOT_ADD"


def test_negated_requirement_produces_no_action():
    """A requirement explicitly negated by the offer is not a requirement."""
    result = match_cv_to_offer(
        _cv(),
        _offer(
            _requirement("Anglais", category="language", modality="required", negated=True),
            _requirement("Python", category="skill"),
        ),
    )

    assert len(result.actions) == 1
    assert result.actions[0].requirement_text == "Python"


def test_raw_offer_is_extracted_with_mission_02():
    """A raw offer without extracted requirements goes through Mission 02."""
    offer = {
        "id": "offre-1",
        "description_original": "Requirements:\n- Python\n- Docker\n- Kubernetes",
    }
    result = match_cv_to_offer(_cv(), offer)

    assert result.total_requirements == 3
    assert {action.requirement_text for action in result.actions} == {
        "Python",
        "Docker",
        "Kubernetes",
    }


def test_english_requirement_on_a_french_cv_is_rephrased():
    """The same language written in another language asks for a reformulation."""
    result = match_cv_to_offer(
        _cv(),
        _offer(_requirement("English", category="language")),
    )

    action = result.actions[0]
    assert action.code == "REPHRASE"
    assert action.cv_evidence_text is not None
    assert "Anglais" in action.cv_evidence_text


def test_language_warning_names_the_language():
    """The language warning names the language that is not proven."""
    result = match_cv_to_offer(
        _cv(CV_WITHOUT_ENGLISH),
        _offer(_requirement("Anglais", category="language", modality="required")),
    )

    assert "Anglais" in result.warnings[0]


def test_evidence_offset_points_to_the_quote():
    """The offset given to the UI really points at the quoted text."""
    cv = _cv()
    result = match_cv_to_offer(cv, _offer(_requirement("VBA", category="skill")))
    action = result.actions[0]
    source = cv.provenance.source_text or ""

    assert action.cv_evidence_offset is not None
    assert action.cv_evidence_text is not None
    assert source[action.cv_evidence_offset:action.cv_evidence_offset + len(action.cv_evidence_text)] == action.cv_evidence_text


def test_score_is_matched_over_total():
    """The global score is exactly the matched/total ratio."""
    result = match_cv_to_offer(
        _cv(),
        _offer(
            _requirement("Python", category="skill"),
            _requirement("AWS", category="skill"),
            _requirement("Kafka", category="skill"),
            _requirement("Terraform", category="skill"),
        ),
    )

    assert result.matched_requirements == 1
    assert result.total_requirements == 4
    assert result.overall_score == result.matched_requirements / result.total_requirements


# ──────────────────────────────────────────────────────────────────────
# Determinism and purity
# ──────────────────────────────────────────────────────────────────────


def test_matching_is_deterministic():
    """Two identical calls return exactly the same result."""
    cv = _cv()
    offer = _offer(
        _requirement("Python", category="skill"),
        _requirement("AWS", category="skill"),
        _requirement("Anglais", category="language"),
    )

    first = match_cv_to_offer(cv, offer)
    second = match_cv_to_offer(cv, offer)

    assert first == second


def test_matching_does_not_mutate_the_cv_result():
    """The analysis is read, never written."""
    cv = _cv()
    before = repr(cv)

    match_cv_to_offer(cv, _offer(_requirement("Python", category="skill")))

    assert repr(cv) == before


def test_match_result_is_a_dataclass():
    """The public result carries the documented fields."""
    result = match_cv_to_offer(_cv(), _offer(_requirement("Python", category="skill")))

    assert isinstance(result, MatchResult)
    assert 0.0 <= result.overall_score <= 1.0
    assert isinstance(result.actions, list)
    assert isinstance(result.missing_critical, list)
    assert isinstance(result.warnings, list)


def test_action_codes_are_exhaustive():
    """Every action uses one of the five documented codes."""
    cv = _cv()
    result = match_cv_to_offer(
        cv,
        _offer(
            _requirement("Python", category="skill"),
            _requirement("Gestion de projet", category="skill"),
            _requirement("Géré équipe 10+", category="skill"),
            _requirement("AWS", category="skill"),
            _requirement("Anglais", category="language"),
        ),
    )

    codes = {action.code for action in result.actions}
    assert codes <= {"HIGHLIGHT", "REPHRASE", "DO_NOT_ADD", "QUANTIFY", "CONFIRM_LANGUAGE"}
    assert "DO_NOT_ADD" in codes


def test_empty_offer_gives_no_warning_about_languages():
    """An empty offer produces no warning at all."""
    result = match_cv_to_offer(_cv(), {"id": "offre-1", "requirements": []})

    assert result.warnings == []
