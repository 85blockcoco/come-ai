from __future__ import annotations

from academics.vc.content import load_content
from academics.vc.glossary import decode_term_sheet, search_glossary


def test_search_is_accent_insensitive_and_bilingual() -> None:
    content = load_content()
    french = search_glossary(content, "preference de liquidation")
    assert french
    assert any(entry.term_en == "Liquidation preference" for entry in french)

    english = search_glossary(content, "venture capital")
    assert english
    assert any(entry.term_fr == "Capital-risque" for entry in english)


def test_unknown_term_returns_no_match() -> None:
    content = load_content()
    assert search_glossary(content, "terme totalement inconnu") == []
    assert search_glossary(content, "") == []


def test_term_sheet_decodes_known_clauses_in_order() -> None:
    content = load_content()
    text = "\n".join(
        [
            "Liquidation preference 1x non participating",
            "Anti-dilution broad-based weighted average",
            "Clause mystérieuse non répertoriée",
            "Pro-rata right for existing investors",
        ]
    )
    result = decode_term_sheet(content, text)
    assert [clause["clause"] for clause in result["clauses"]] == [
        "liquidation",
        "anti_dilution",
        "pro_rata",
    ]
    assert result["clauses"][0]["multiple"] == 1
    assert result["clauses"][0]["participating"] is False
    assert result["unknown_clauses"] == ["Clause mystérieuse non répertoriée"]
    assert all(clause["economic_effect"] for clause in result["clauses"])


def test_control_clauses_are_decoded_in_order() -> None:
    content = load_content()
    result = decode_term_sheet(
        content,
        "\n".join(
            [
                "Board seat for the lead investor",
                "Drag-along right for the majority",
                "Tag-along right for minority holders",
            ]
        ),
    )
    assert [clause["clause"] for clause in result["clauses"]] == [
        "board",
        "drag_along",
        "tag_along",
    ]
    assert all(clause["economic_effect"] for clause in result["clauses"])


def test_participating_and_cap_are_explained() -> None:
    content = load_content()
    result = decode_term_sheet(
        content, "Liquidation preference 1x participating with a 3x cap"
    )
    clause = result["clauses"][0]
    assert clause["participating"] is True
    assert clause["capped"] is True
    assert clause["economic_effect"]
