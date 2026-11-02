import pytest

from academics.vc.notes import approve_proposal, extract_note_lines, propose_cards, propose_cards_from_file


def test_notes_produce_cited_cards_that_need_approval():
    proposals = propose_cards("Pre-money : valeur avant investissement\nMOIC : multiple de retour", source_name="synthetic.md", topic="valuation")
    assert len(proposals) == 2
    assert proposals[0].status == "à approuver"
    assert "synthetic.md:ligne 1" in proposals[0].citation
    card = approve_proposal(proposals[0])
    assert card.approved and card.source == proposals[0].citation


def test_ambiguous_or_unstructured_notes_do_not_create_cards():
    assert propose_cards("texte sans définition\n: vide\nterme:") == []


def test_approval_requires_citation_and_pending_status():
    proposal = propose_cards("MOIC : multiple", source_name="synthetic.md")[0]
    with pytest.raises(ValueError):
        approve_proposal(type(proposal)(proposal.proposal_id, proposal.topic, proposal.front, proposal.back, "", "approved"))


def test_local_text_file_keeps_line_citations(tmp_path):
    source = tmp_path / "vc-notes.txt"
    source.write_text("Pre-money : valorisation avant tour\nPhrase sans définition\n", encoding="utf-8")
    assert extract_note_lines(source)[0][0] == "vc-notes.txt:ligne 1"
    proposal = propose_cards_from_file(source, topic="valuation")[0]
    assert proposal.citation.startswith("vc-notes.txt:ligne 1")
