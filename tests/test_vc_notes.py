from __future__ import annotations

from pathlib import Path

import pytest

from academics.vc.content import load_content
from academics.vc.errors import InputError
from academics.vc.models import Flashcard
from academics.vc.notes import (
    MAX_NOTE_BYTES,
    approve_proposal,
    ingest_file,
    ingest_notes,
    list_notes,
    reject_proposal,
)
from academics.vc.storage import VcStore

FIXTURES = Path(__file__).parent / "fixtures" / "vc_notes"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def ingest_fixture(
    store: VcStore, name: str, *, topic_id: str = "VC04", replace: bool = False
) -> dict:
    return ingest_notes(
        store,
        read_fixture(name),
        filename=name,
        topic_id=topic_id,
        replace=replace,
    )


def by_question(payload: dict, fragment: str) -> dict:
    needle = fragment.lower()
    return next(
        proposal
        for proposal in payload["proposals"]
        if needle in proposal["question"].lower()
    )


def test_markdown_definitions_are_extracted_with_exact_citations(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    text = read_fixture("definitions.md")
    result = ingest_fixture(store, "definitions.md")

    assert result["created"] >= 4
    assert result["notice"].startswith("Aucune carte")
    assert result["source"]["kind"] == "md"
    assert result["source"]["sha256"] == result["source"]["source_id"]
    for proposal in result["proposals"]:
        citation = proposal["citation"]
        assert citation["source_id"] == result["source"]["source_id"]
        assert citation["locator"].startswith("ligne ")
        assert citation["quote"] in text
        assert proposal["status"] in {"proposed", "a_completer"}

    post_money = by_question(result, "post-money")
    assert post_money["answer"].startswith("valorisation de la société après")
    assert post_money["citation"]["quote"].startswith("**Post-money**")

    cap_table = by_question(result, "recense")
    assert cap_table["answer"] == "cap table"
    assert cap_table["status"] == "proposed"


def test_bold_and_em_dash_patterns_are_supported(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    result = ingest_fixture(store, "definitions.md")

    assert any("Post-money" in item["question"] for item in result["proposals"])
    liquidation = by_question(result, "liquidation preference")
    assert liquidation["question"] == "Que signifie « Liquidation preference » ?"
    assert liquidation["citation"]["quote"].startswith("Liquidation preference —")
    assert liquidation["answer"].startswith("montant récupéré")


def test_question_answer_pairs_and_missing_answer(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    text = read_fixture("questions.txt")
    result = ingest_fixture(store, "questions.txt")

    assert result["created"] == 3
    safe = by_question(result, "safe")
    assert safe["status"] == "proposed"
    assert safe["answer"].startswith("Un contrat convertible")
    assert "Q:" in safe["citation"]["quote"]
    assert "R:" in safe["citation"]["quote"]
    assert "lignes" in safe["citation"]["locator"]
    assert safe["citation"]["quote"] in text

    moic = by_question(result, "moic")
    assert moic["answer"] == "Le multiple brut reçu sur le capital investi."

    uncertain = by_question(result, "participating")
    assert uncertain["status"] == "a_completer"
    assert uncertain["answer"] is None
    assert uncertain["citation"]["quote"] == "Q: Que signifie une préférence participating ?"


def test_bullet_cloze_and_incomplete_without_heading(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    text = read_fixture("bullets.md")
    result = ingest_fixture(store, "bullets.md")

    orphan = by_question(result, "définit")
    assert orphan["status"] == "a_completer"
    assert orphan["answer"] is None
    assert "_____" in orphan["question"]

    liquidation = by_question(result, "récupère")
    assert liquidation["status"] == "proposed"
    assert liquidation["answer"].lower() == "liquidation preference"
    assert "_____" in liquidation["question"]

    participation = by_question(result, "permet")
    assert participation["status"] == "proposed"
    assert participation["answer"] == "participation"

    for proposal in result["proposals"]:
        assert proposal["citation"]["quote"] in text


def test_every_proposal_has_source_locator_and_quote(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    result = ingest_fixture(store, "definitions.md")

    for proposal in result["proposals"]:
        assert set(proposal["citation"]) == {"source_id", "locator", "quote"}
        assert proposal["citation"]["source_id"]
        assert proposal["citation"]["locator"]
        assert proposal["citation"]["quote"]


def test_no_card_is_active_before_approval(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    result = ingest_fixture(store, "definitions.md")
    content = load_content()
    card_ids = {card.id for card in content.cards}
    questions = {card.question for card in content.cards}

    assert store.load_deck() == []
    for proposal in result["proposals"]:
        assert proposal["status"] != "active"
        assert proposal["proposal_id"] not in card_ids
        assert proposal["question"] not in questions
    assert not (store.path("deck.json")).exists()


def test_approval_moves_a_cited_card_to_the_deck(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    result = ingest_fixture(store, "definitions.md")
    proposal = next(item for item in result["proposals"] if item["status"] == "proposed")

    card = approve_proposal(store, proposal["proposal_id"])

    assert isinstance(card, Flashcard)
    assert card.status == "active"
    assert card.source_type == "user_note"
    assert card.citation == proposal["citation"]
    assert card.answer == proposal["answer"]
    assert store.load_deck() == [card]

    listed = list_notes(store)
    approved = next(
        item
        for item in listed["proposals"]
        if item["proposal_id"] == proposal["proposal_id"]
    )
    assert approved["status"] == "approved"
    assert listed["counts"]["approved"] == 1

    merged = load_content().with_cards(store.load_deck())
    assert merged.card(card.id).source_type == "user_note"
    assert merged.card(card.id).answer == card.answer

    assert approve_proposal(store, proposal["proposal_id"]).id == card.id
    assert len(store.load_deck()) == 1


def test_approval_requires_an_answer_for_a_completer(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    result = ingest_fixture(store, "questions.txt")
    proposal = next(
        item for item in result["proposals"] if item["status"] == "a_completer"
    )

    with pytest.raises(InputError, match="to be completed"):
        approve_proposal(store, proposal["proposal_id"])

    card = approve_proposal(
        store,
        proposal["proposal_id"],
        answer="Une préférence qui participe au résidu après remboursement.",
    )
    assert card.status == "active"
    assert card.answer.startswith("Une préférence")


def test_rejection_persists_and_prevents_reintroduction(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    result = ingest_fixture(store, "definitions.md")
    proposal = next(item for item in result["proposals"] if item["status"] == "proposed")

    reject_proposal(store, proposal["proposal_id"])
    listed = list_notes(store)
    rejected = next(
        item
        for item in listed["proposals"]
        if item["proposal_id"] == proposal["proposal_id"]
    )
    assert rejected["status"] == "rejected"
    assert listed["counts"]["rejected"] == 1
    assert store.load_deck() == []

    again = ingest_fixture(store, "definitions.md")
    assert again["created"] == 0
    assert again["rejected_skipped"] >= 1
    assert not any(
        item["status"] == "proposed"
        and item["question"] == proposal["question"]
        for item in again["proposals"]
    )

    reloaded = VcStore(store.home)
    statuses = {
        item["status"]: item["status"]
        for item in list_notes(reloaded)["proposals"]
        if item["proposal_id"] == proposal["proposal_id"]
    }
    assert statuses["rejected"] == "rejected"

    with pytest.raises(InputError, match="rejected"):
        approve_proposal(store, proposal["proposal_id"])


def test_duplicate_proposals_from_one_source_are_deduplicated(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    text = (
        "Post-money : définition du post-money après le cash.\n\n"
        "Post-money : définition du post-money après le cash.\n"
    )
    first = ingest_notes(
        store, text, filename="duplicates.md", topic_id="VC04"
    )
    assert first["created"] == 1
    assert first["duplicates"] == 1

    second = ingest_notes(
        store, text, filename="duplicates.md", topic_id="VC04"
    )
    assert second["created"] == 0
    assert second["duplicates"] == 2


def test_changed_source_is_flagged_and_requires_replace(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    first = ingest_notes(
        store,
        "Post-money : définition initiale du post-money après le cash.\n",
        filename="cours.md",
        topic_id="VC04",
    )
    old_source = first["source"]

    with pytest.raises(InputError, match="changed"):
        ingest_notes(
            store,
            "Pre-money : définition remplacée du pre-money avant le cash.\n",
            filename="cours.md",
            topic_id="VC04",
        )
    unchanged = list_notes(store)
    assert unchanged["sources"][0]["sha256"] == old_source["sha256"]
    assert not any(
        "remplacée" in item["answer"] for item in unchanged["proposals"]
    )

    replaced = ingest_notes(
        store,
        "Pre-money : définition remplacée du pre-money avant le cash.\n",
        filename="cours.md",
        topic_id="VC04",
        replace=True,
    )
    assert replaced["source"]["source_id"] != old_source["source_id"]
    statuses = {source["status"] for source in list_notes(store)["sources"]}
    assert "superseded" in statuses
    assert not store.path("notes", f"{old_source['source_id']}.txt").exists()
    assert store.path("notes", f"{replaced['source']['source_id']}.txt").exists()


def test_scanned_pdf_without_text_returns_a_readable_error(tmp_path: Path) -> None:
    from pypdf import PdfWriter

    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as handle:
        writer.write(handle)

    store = VcStore(tmp_path / "vc")
    with pytest.raises(InputError, match="sans texte"):
        ingest_file(store, path, topic_id="VC04")


def test_size_limit_is_enforced_for_files_and_text(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    path = tmp_path / "big.txt"
    path.write_bytes(b"a" * (MAX_NOTE_BYTES + 1))
    with pytest.raises(InputError, match="2 Mo"):
        ingest_file(store, path, topic_id="VC04")
    with pytest.raises(InputError, match="2 Mo"):
        ingest_notes(
            store,
            "a" * (MAX_NOTE_BYTES + 1),
            filename="big.txt",
            topic_id="VC04",
        )


def test_non_utf8_and_unsupported_files_are_rejected(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    binary = tmp_path / "notes.txt"
    binary.write_bytes(b"\xff\xfe\x00\x00")
    with pytest.raises(InputError, match="UTF-8"):
        ingest_file(store, binary, topic_id="VC04")

    unsupported = tmp_path / "notes.docx"
    unsupported.write_text("contenu", encoding="utf-8")
    with pytest.raises(InputError, match="Unsupported notes format"):
        ingest_file(store, unsupported, topic_id="VC04")

    empty = tmp_path / "empty.md"
    empty.write_text("   \n", encoding="utf-8")
    with pytest.raises(InputError, match="vide"):
        ingest_file(store, empty, topic_id="VC04")

    with pytest.raises(InputError, match="VCxx"):
        ingest_notes(store, "Post-money : définition.", filename="x.md", topic_id="VC4")


def test_note_text_never_leaks_into_errors_or_repository(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    marker = "NAGE_PRIVATE_NOTE_" + "TOKEN_2026"
    text = f"Post-money : {marker} est une définition privée.\n"
    result = ingest_notes(
        store, text, filename="prive.md", topic_id="VC04"
    )
    snapshot = store.path("notes", f"{result['source']['source_id']}.txt")
    assert marker in snapshot.read_text(encoding="utf-8")
    assert store.warnings == []

    with pytest.raises(InputError) as caught:
        ingest_notes(
            store,
            f"Pre-money : {marker} a changé de définition.\n",
            filename="prive.md",
            topic_id="VC04",
        )
    assert marker not in str(caught.value)

    for file in Path("academics/vc").rglob("*"):
        if file.is_file() and file.suffix in {".py", ".json", ".md"}:
            assert marker not in file.read_text(encoding="utf-8", errors="ignore")
    assert marker not in Path("tests/test_vc_notes.py").read_text(encoding="utf-8")


def test_content_pack_with_cards_merges_only_active_cards() -> None:
    content = load_content()
    original_count = len(content.cards)
    active = Flashcard(
        id="vcnote-demo",
        topic_id="VC04",
        question="Que signifie « post-money » ?",
        answer="La valorisation après le cash.",
        source_type="user_note",
        citation={"source_id": "src-1", "locator": "ligne 1", "quote": "post-money"},
        status="active",
    )
    incomplete = Flashcard(
        id="vcnote-incomplete",
        topic_id="VC04",
        question="Que signifie « pre-money » ?",
        answer="",
        status="a_completer",
    )

    merged = content.with_cards([active, incomplete])

    assert len(merged.cards) == original_count + 1
    assert merged.card("vcnote-demo") is active
    assert "vcnote-incomplete" not in merged.card_by_id
    assert "vcnote-demo" not in content.card_by_id
    assert len(content.cards) == original_count
