"""Tests for letter fact verification + quality score (N100-F05, N100-F06)."""

from __future__ import annotations

from career.letter_check import score_letter, verify_letter_facts, to_dict


GOOD = (
    "Madame, Monsieur,\n\nJe me permets de vous adresser ma candidature pour un stage "
    "en analyse financière au sein de votre banque à partir de janvier prochain. "
    "Je suis actuellement étudiant en dernière année de programme BBA Finance, avec une "
    "première expérience en contrôle de gestion auprès d'une entreprise industrielle.\n"
    "- BBA Finance obtenu en 2026\n"
    "- Stage de six mois en contrôle de gestion\n\nCordialement,\nAlice"
)

INVENTED = (
    "Madame, Monsieur,\n\nJe me permets de vous adresser ma candidature pour un poste "
    "en banque d'affaires au sein de votre établissement. J'ai dirigé une équipe de "
    "trente quants pendant cinq ans sur plusieurs marchés internationaux.\n\n"
    "Cordialement,\nAlice"
)


EVIDENCE = ["BBA Finance obtenu en 2026"]


def test_supported_facts() -> None:
    facts = verify_letter_facts(GOOD, EVIDENCE)
    assert facts["summary"]["supported"] >= 1
    assert facts["invented"] == 0


def test_invented_detected() -> None:
    facts = verify_letter_facts(INVENTED, EVIDENCE)
    assert facts["invented"] >= 1


def test_score_good_letter() -> None:
    r = score_letter(GOOD, EVIDENCE)
    assert r.facts_ok is True
    assert r.completeness_score >= 60
    assert r.blockers == []


def test_score_placeholder_blocker() -> None:
    body = GOOD + "\n[À COMPLÉTER : ajouter des faits approuvés du profil.]"
    r = score_letter(body, EVIDENCE)
    assert any("placeholder" in b for b in r.blockers)
    assert r.completeness_score < 100


def test_missing_salutation() -> None:
    body = "Texte sans salutation. " * 5 + "Cordialement,\nX"
    r = score_letter(body)
    assert any("salutation" in v for v in r.violations)


def test_missing_closing() -> None:
    body = "Madame, Monsieur,\n\nTexte sans formule finale. " * 3
    r = score_letter(body)
    assert any("politesse" in v for v in r.violations)


def test_no_evidence_unverifiable() -> None:
    facts = verify_letter_facts(GOOD, [])
    assert facts["unverifiable"] >= 1


def test_empty_letter() -> None:
    r = score_letter("")
    assert r.completeness_score <= 40
    assert len(r.violations) >= 2


def test_to_dict() -> None:
    r = score_letter(GOOD, EVIDENCE)
    assert to_dict(r)["facts_ok"] is True
