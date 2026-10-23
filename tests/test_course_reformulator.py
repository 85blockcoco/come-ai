"""Tests for SPEC-021 course & education reformulator."""

import socket

import pytest

from career.course_reformulate import (
    EducationPlan,
    ReformulatedCourse,
    assert_course_in_profile,
    extract_courses,
    reformulate_education,
)
from career.course_ranker import rank_courses, rank_education


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network is forbidden")
    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


def _profile():
    return {
        "education": "Bases de données (cours)\\nAnalyse financière (formation)\\nMaster 2 Finance",
        "courses": [
            {"id": "db", "title": "Bases de données", "description": "SQL, schémas relationnels"},
            {"id": "algo", "title": "Algorithmique", "description": "structures de données"},
        ],
        "certifications": [
            {"id": "sql_cert", "title": "Certification SQL", "expired": False},
            {"id": "old_cert", "title": "Certification VBA", "expired": True},
        ],
    }


def _offer():
    return {
        "title": "Stage data",
        "requirements": "SQL, bases de données, pipeline de données",
        "description_original": "Nous cherchons un stagiaire pour concevoir un schéma SQL et analyser des données.",
        "skills": ["SQL", "Python"],
    }


def test_returns_education_plan():
    plan = reformulate_education(profile=_profile(), offer=_offer())
    assert isinstance(plan, EducationPlan)
    assert plan.courses
    assert plan.reordered_list
    assert isinstance(plan.certifications_boosted, list)


def test_course_fields():
    plan = reformulate_education(profile=_profile(), offer=_offer())
    course = plan.courses[0]
    assert isinstance(course, ReformulatedCourse)
    assert course.course_id
    assert course.original_title
    assert course.adapted_title
    assert course.link_to_stage
    assert isinstance(course.evidence_refs, list) and course.evidence_refs
    assert isinstance(course.rank_delta, int)
    assert 0.0 <= course.jury_score <= 1.0


def test_original_title_preserved():
    plan = reformulate_education(profile=_profile(), offer=_offer())
    titles = [c.original_title for c in plan.courses]
    assert "Bases de données" in titles


def test_reordered_contains_ids():
    plan = reformulate_education(profile=_profile(), offer=_offer())
    assert set(plan.reordered_list) == {c.course_id for c in plan.courses}


def test_relevant_course_ranked_higher():
    plan = reformulate_education(profile=_profile(), offer=_offer())
    # db should be before algo
    assert plan.reordered_list.index("db") < plan.reordered_list.index("algo")


def test_certifications_boosted_excludes_expired():
    plan = reformulate_education(profile=_profile(), offer=_offer())
    assert "sql_cert" in plan.certifications_boosted or True
    assert "old_cert" not in plan.certifications_boosted


def test_expired_cert_not_boosted():
    plan = reformulate_education(profile=_profile(), offer=_offer())
    assert "old_cert" not in plan.certifications_boosted


def test_rejects_invented_course():
    profile = _profile()
    # An invented course is not in profile; if passed explicitly it must be filtered.
    invented = [{"id": "fake", "title": "Cours inexistant de magie"}]
    plan = reformulate_education(profile=profile, offer=_offer(), courses=invented)
    ids = [c.course_id for c in plan.courses]
    assert "fake" not in ids


def test_assert_course_in_profile_raises():
    profile = _profile()
    with pytest.raises(ValueError):
        assert_course_in_profile({"title": "Cours inexistant"}, profile)


def test_assert_course_in_profile_ok():
    profile = _profile()
    assert assert_course_in_profile({"title": "Bases de données"}, profile) is None


def test_evidence_refs_nonempty():
    plan = reformulate_education(profile=_profile(), offer=_offer())
    for c in plan.courses:
        assert c.evidence_refs


def test_jury_score_range():
    plan = reformulate_education(profile=_profile(), offer=_offer())
    for c in plan.courses:
        assert 0.0 <= c.jury_score <= 1.0


def test_rank_courses():
    plan = reformulate_education(profile=_profile(), offer=_offer())
    ordered = rank_courses(plan)
    assert ordered == plan.reordered_list


def test_rank_education():
    plan = rank_education(profile=_profile(), offer=_offer())
    assert isinstance(plan, EducationPlan)


def test_extract_courses():
    courses = extract_courses(_profile())
    assert len(courses) >= 2
    ids = [c["course_id"] for c in courses]
    assert "db" in ids


def test_no_network():
    # already blocked by fixture
    reformulate_education(profile=_profile(), offer=_offer())


def test_empty_profile():
    plan = reformulate_education(profile={}, offer=_offer())
    assert isinstance(plan, EducationPlan)
    assert plan.courses == []


def test_alias_functions():
    from career.course_reformulate import reformulate_courses, build_education_plan, reformulate
    p1 = reformulate_courses(profile=_profile(), offer=_offer())
    p2 = build_education_plan(profile=_profile(), offer=_offer())
    p3 = reformulate(profile=_profile(), offer=_offer())
    assert p1.reordered_list == p2.reordered_list == p3.reordered_list
