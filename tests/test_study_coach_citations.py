"""Citation fidelity tests: every reference must point to a real passage.

These tests are the regression net for the two coordinate systems used by the
engine:

* the **source** coordinates (``line_start``/``line_end``/``page``) describe the
  original Côme AI document and follow the personal-memory citation contract;
* the **document** coordinates (``document_line_start``/``document_line_end``/
  ``char_start``/``char_end``) describe the reconstructed Study Coach text and
  are what the excerpt is verified against.

Only synthetic passages are used: no personal document is read anywhere.
"""

from __future__ import annotations

from study_coach.models import SourceRef
from study_coach.samples import FINANCE_COURSE
from study_coach.sources import PersonalMemorySourceAdapter, document_from_text
from study_coach.syllabus import build_syllabus

PASSAGE_ONE = "La valeur actuelle nette est la somme des flux actualisés moins l'investissement initial."
PASSAGE_TWO = "Le coût moyen pondéré du capital est le coût moyen du financement de l'entreprise."
PASSAGE_THREE = "Dans notre exemple, le coût de la dette vaut 6 % et le taux d'IS vaut 25 %."


def make_store(passages, *, title="Cours de finance", source_id="src_cours"):
    """Fake ``PersonalMemoryStore`` returning the public search contract."""

    class FakeStore:
        def list_sources(self, category=None, limit=100):
            return [{"source_id": source_id, "id": source_id, "title": title, "category": category or "cours"}]

        def search(self, query, project_id=None, limit=8):
            results = []
            for text, citation in passages:
                results.append(
                    {
                        "source_id": source_id,
                        "title": title,
                        "excerpt": text,
                        "citation": dict(citation, source_id=source_id, title=title),
                    }
                )
            return {"query": query, "count": len(results), "results": results}

    return FakeStore()


def citation(page: int, line_start: int, line_end: int | None = None) -> dict:
    return {
        "page": page,
        "line_start": line_start,
        "line_end": line_start if line_end is None else line_end,
        "label": f"Cours de finance p.{page} l.{line_start}",
    }


# --------------------------------------------------------------------------- #
# Reconstructed document
# --------------------------------------------------------------------------- #


def test_single_passage_keeps_the_source_page_and_original_lines() -> None:
    adapter = PersonalMemorySourceAdapter(make_store([(PASSAGE_ONE, citation(2, 14))]))
    document = adapter.load_document("src_cours")

    assert document.source_id == "src_cours"
    assert document.title == "Cours de finance"
    assert document.lines[0] == PASSAGE_ONE
    assert document.line_number(0) == 1

    passages = document.metadata["passages"]
    assert len(passages) == 1
    assert passages[0]["line_start"] == 1, "le passage doit pointer sa propre ligne reconstruite"

    reference = SourceRef(
        source_id=document.source_id,
        title=document.title,
        excerpt=PASSAGE_ONE,
        locator={
            "document_line_start": document.line_number(0),
            "document_line_end": document.line_number(0),
            "char_start": 0,
            "char_end": len(PASSAGE_ONE),
            "line_start": 14,
            "line_end": 14,
            "page": 2,
        },
    )
    assert reference.matches_text(document.text)
    assert reference.page == 2
    assert reference.document_line_start == 1
    assert reference.to_citation_dict() == {
        "source_id": "src_cours",
        "title": "Cours de finance",
        "page": 2,
        "line_start": 14,
        "line_end": 14,
        "label": "Cours de finance (p.2 l.14)",
    }


def test_several_passages_keep_one_reconstructed_line_each() -> None:
    passages = [
        (PASSAGE_ONE, citation(2, 14)),
        (PASSAGE_TWO, citation(2, 27)),
        (PASSAGE_THREE, citation(3, 4)),
    ]
    document = PersonalMemorySourceAdapter(make_store(passages)).load_document("src_cours")

    assert document.lines == [PASSAGE_ONE, PASSAGE_TWO, PASSAGE_THREE]
    kept = document.metadata["passages"]
    assert [(item["line_start"], item["line_end"]) for item in kept] == [(1, 1), (2, 2), (3, 3)]
    for index, item in enumerate(kept):
        assert item["line_start"] == document.line_number(index)
        assert item["citation"]["page"] == passages[index][1]["page"]

    syllabus = build_syllabus(document)
    assert syllabus.notions
    for notion in syllabus.notions:
        for reference in notion.source_refs:
            assert reference.matches_text(document.text), "chaque extrait doit être une tranche exacte"
            assert reference.source_id == "src_cours"
            assert reference.page in (2, 3), "la page doit venir du document d'origine"


def test_passage_with_line_breaks_stays_one_cited_line() -> None:
    wrapped = "La VAN est la somme des flux actualisés\nmoins l'investissement initial."
    document = PersonalMemorySourceAdapter(make_store([(wrapped, citation(1, 2))])).load_document("src_cours")

    assert document.lines == ["La VAN est la somme des flux actualisés moins l'investissement initial."]
    assert document.metadata["passages"][0]["line_start"] == 1
    assert document.metadata["passages"][0]["citation"]["line_start"] == 2


def test_empty_passage_is_ignored_without_shifting_the_following_lines() -> None:
    passages = [
        (PASSAGE_ONE, citation(2, 14)),
        ("   \n  ", citation(2, 18)),
        (PASSAGE_TWO, citation(2, 27)),
    ]
    document = PersonalMemorySourceAdapter(make_store(passages)).load_document("src_cours")

    assert document.lines == [PASSAGE_ONE, PASSAGE_TWO]
    kept = document.metadata["passages"]
    assert [item["citation"]["line_start"] for item in kept] == [14, 27]
    assert [item["line_start"] for item in kept] == [1, 2]
    for index, item in enumerate(kept):
        assert item["line_start"] == document.line_number(index)
        assert document.lines[index] == passages[[0, 2][index]][0]


def test_document_with_another_line_numbering_keeps_both_references() -> None:
    """``base_line`` lets an integration align with its own line numbering."""

    passages = [(PASSAGE_ONE, citation(2, 14)), (PASSAGE_TWO, citation(2, 27))]
    document = PersonalMemorySourceAdapter(make_store(passages)).load_document("src_cours")

    shifted = document_from_text(
        document.text,
        title=document.title,
        source_id=document.source_id,
        document_id=document.document_id,
        base_line=1_000,
        metadata=document.metadata,
    )
    assert shifted.line_number(0) == 1_000
    assert shifted.metadata["passages"][0]["line_start"] == 1
    # The reconstruction lines moved, the original document lines did not.
    assert shifted.metadata["passages"][0]["citation"]["line_start"] == 14
    assert shifted.text == document.text


def test_citation_label_finds_the_passage_back() -> None:
    passages = [(PASSAGE_ONE, citation(2, 14)), (PASSAGE_TWO, citation(3, 5)), (PASSAGE_THREE, citation(3, 9))]
    document = PersonalMemorySourceAdapter(make_store(passages)).load_document("src_cours")
    syllabus = build_syllabus(document)

    for notion in syllabus.notions:
        for reference in notion.source_refs:
            citation_dict = reference.to_citation_dict()
            label = citation_dict["label"]
            assert label.startswith(document.title)
            assert f"p.{citation_dict['page']}" in label

            matching = [
                item
                for item in document.metadata["passages"]
                if item["citation"]["page"] == citation_dict["page"]
                and item["citation"]["line_start"] == citation_dict["line_start"]
            ]
            assert matching, f"la citation {label} doit correspondre à un passage connu"
            # The displayed excerpt is the text of that very passage.
            assert reference.excerpt in "\n".join(document.lines)


def test_source_and_document_coordinates_never_get_mixed() -> None:
    """The memory-contract keys must carry the ORIGINAL lines, not the synthetic ones."""

    passages = [(PASSAGE_ONE, citation(7, 120)), (PASSAGE_TWO, citation(8, 3)), (PASSAGE_THREE, citation(9, 41))]
    document = PersonalMemorySourceAdapter(make_store(passages)).load_document("src_cours")
    syllabus = build_syllabus(document)

    numerique = [notion for notion in syllabus.notions if notion.numeric_facts]
    others = [notion for notion in syllabus.notions if not notion.numeric_facts]
    assert numerique and others

    for notion in others:
        reference = notion.source_refs[0]
        locator = reference.locator
        assert locator["line_start"] in (120, 3, 41), "lignes d'origine conservées"
        assert locator["page"] in (7, 8, 9)
        assert locator["document_line_start"] in (1, 2, 3), "lignes reconstruites conservées à part"
        assert locator["document_line_start"] != locator["line_start"]
        assert reference.matches_text(document.text)


def test_sentence_split_across_two_passages_is_rebuilt_and_fully_cited() -> None:
    """Non-regression: the two halves of one cut sentence are re-joined.

    The document store marks its cuts with ``…``; both halves carry the mark, and
    that is the only evidence the engine accepts to glue two windows together.
    """

    first = "La valeur actuelle nette est la somme des flux actualisés moins…"
    second = "…l'investissement initial. Un projet dont la VAN est positive augmente la valeur."
    passages = [(first, citation(2, 10)), (second, citation(2, 11))]
    document = PersonalMemorySourceAdapter(make_store(passages)).load_document("src_cours")
    syllabus = build_syllabus(document)

    notion = next(item for item in syllabus.notions if item.title == "valeur actuelle nette")
    assert notion.statement.startswith(
        "La valeur actuelle nette est la somme des flux actualisés moins l'investissement initial."
    )
    assert len(notion.source_refs) == 2, "une citation par passage d'origine"
    assert [reference.locator["line_start"] for reference in notion.source_refs] == [10, 11]
    assert [reference.page for reference in notion.source_refs] == [2, 2]
    for reference in notion.source_refs:
        assert reference.matches_text(document.text)


def test_unmarked_fragments_are_never_glued_into_a_notion() -> None:
    """Two complete-but-unmarked windows must not be concatenated blindly."""

    first = "La valeur actuelle nette est la somme des flux actualisés moins"
    second = "l'investissement initial. Un projet dont la VAN est positive augmente la valeur."
    document = PersonalMemorySourceAdapter(
        make_store([(first, citation(2, 10)), (second, citation(2, 11))])
    ).load_document("src_cours")
    syllabus = build_syllabus(document)

    for notion in syllabus.notions:
        assert notion.statement.endswith((".", "!", "?")), "aucun fragment sans point final"
        assert not notion.statement.startswith("l'investissement")
        assert "… " not in notion.statement


def test_excerpt_of_a_plain_text_course_is_verifiable() -> None:
    document = document_from_text(FINANCE_COURSE, title="Finance", source_id="src_texte")
    syllabus = build_syllabus(document)

    for notion in syllabus.notions:
        for reference in notion.source_refs:
            assert reference.matches_text(document.text)
            # No document store behind: source and document lines coincide.
            assert reference.locator["line_start"] == reference.document_line_start
            assert reference.page is None
            assert reference.to_citation_dict()["page"] is None


def test_integrity_check_detects_a_tampered_reference() -> None:
    document = document_from_text(FINANCE_COURSE, title="Finance")
    syllabus = build_syllabus(document)
    reference = syllabus.notions[0].source_refs[0]
    start = reference.locator["char_start"]

    assert reference.matches_text(document.text)
    assert not SourceRef(
        source_id=reference.source_id,
        title=reference.title,
        excerpt="Une phrase qui n'est pas dans le cours.",
        locator=dict(reference.locator),
    ).matches_text(document.text)

    # A course edited under the feet of the references invalidates them.
    edited = document.text[:start] + "X" + document.text[start + 1 :]
    assert not reference.matches_text(edited)

    # So does an insertion before the passage: the offsets no longer point to it.
    shifted = document.text[:start] + "inserted " + document.text[start:]
    assert not reference.matches_text(shifted)

    # A reference without character offsets cannot be verified and says so.
    opaque = SourceRef(
        source_id=reference.source_id,
        title=reference.title,
        excerpt=reference.excerpt,
        locator={"line_start": 1},
    )
    assert not opaque.matches_text(document.text)
