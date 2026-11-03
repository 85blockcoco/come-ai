"""Tests for contract type detection (N100-B04)."""

from __future__ import annotations

import pytest

from career.contract_type import detect_contract_type, CONTRACT_TYPES


CASES = [
    ("Stage de 6 mois en finance", "stage"),
    ("Internship in London", "intern"),
    ("Contrat d'alternance", "alternance"),
    ("CDD 6 mois", "cdd"),
    ("CDI temps plein", "cdi"),
    ("Apprentissage 2 ans", "apprentissage"),
    ("Freelance mission", "freelance"),
    ("", "unknown"),
]


@pytest.mark.parametrize("text,expected", [(t, e if e != "intern" else "stage") for t, e in CASES])
def test_detect(text, expected) -> None:
    assert detect_contract_type(text) == expected


def test_types_tuple() -> None:
    assert "stage" in CONTRACT_TYPES
    assert "unknown" in CONTRACT_TYPES


def test_case_insensitive() -> None:
    assert detect_contract_type("STAGE FINANCE") == "stage"