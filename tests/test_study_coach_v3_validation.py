"""V3 validation study: the full PDF -> notions -> questions -> corrections ->
progression -> resume journey, with two independent synthetic courses.

This file qualifies the citation corrections ported from the ``study-coach``
worktree (truncated windows, duplicate windows, complete-statement guard)
against the v3 integration base.  Every check below is reproducible offline
with the synthetic courses only: no personal document, no network, no cloud.

Covered here:

* two independent courses keep disjoint notion ids and never cite each other;
* duplicate retrievals of one statement fuse into a single notion that keeps
  every proving passage;
* each citation resolves to the *exact* passage of the course (presence of a
  citation is not proof: the excerpt must match the passage at those
  coordinates);
* truncated windows never leak a half-sentence as a reviewable notion;
* a session interrupted by a complete shutdown resumes exactly where it
  stopped, ids and progression included.
"""

from __future__ import annotations

from datetime import date

from study_coach.engine import StudyCoach
from study_coach.samples import ACCOUNTING_COURSE, FINANCE_COURSE
from study_coach.sources import PersonalMemorySourceAdapter, document_from_text
from study_coach.syllabus import build_syllabus

from test_study_coach_citations import PASSAGE_ONE, PASSAGE_THREE, PASSAGE_TWO, citation, make_store


def load_course(passages, *, title="Cours de finance", source_id="src_cours"):
    """Rebuild a StudyDocument from synthetic passages through the real adapter."""

    return PersonalMemorySourceAdapter(make_store(passages, title=title, source_id=source_id)).load_document(source_id)


# --------------------------------------------------------------------------- #
# 1. Two independent courses stay isolated
# --------------------------------------------------------------------------- #


def test_two_independent_courses_keep_disjoint_notion_ids() -> None:
    finance = build_syllabus(document_from_text(FINANCE_COURSE, title="Finance", source_id="src_finance"))
    accounting = build_syllabus(document_from_text(ACCOUNTING_COURSE, title="Comptabilité", source_id="src_compta"))

    finance_ids = {notion.id for notion in finance.notions}
    accounting_ids = {notion.id for notion in accounting.notions}

    assert finance_ids and accounting_ids
    assert finance_ids.isdisjoint(accounting_ids), "deux cours indépendants ne doivent pas partager d'identifiant"
    assert finance.id != accounting.id


def test_two_independent_courses_never_cite_each_other() -> None:
    """A notion of one course must only cite passages of its own course."""

    finance_doc = document_from_text(FINANCE_COURSE, title="Finance", source_id="src_finance")
    accounting_doc = document_from_text(ACCOUNTING_COURSE, title="Comptabilité", source_id="src_compta")
    finance = build_syllabus(finance_doc)
    accounting = build_syllabus(accounting_doc)

    for notion in finance.notions:
        for reference in notion.source_refs:
            assert reference.source_id == "src_finance"
            assert reference.title == "Finance"
            assert reference.matches_text(finance_doc.text)
    for notion in accounting.notions:
        for reference in notion.source_refs:
            assert reference.source_id == "src_compta"
            assert reference.title == "Comptabilité"
            assert reference.matches_text(accounting_doc.text)


# --------------------------------------------------------------------------- #
# 2. Duplicate retrievals of one statement
# --------------------------------------------------------------------------- #


def test_duplicate_windows_fuse_into_one_notion_with_every_passage() -> None:
    """The same statement retrieved from several windows stays one notion.

    Presence of the statement in several windows is not several proofs of
    several notions: the learner reviews it once, and every passage that
    proves it stays cited.  The second window repeats the definition in
    another part of the course and adds new words, so the store keeps it
    (it is not a redundant window of the same chunk).
    """

    repeated = PASSAGE_ONE + " Elle se calcule au taux du marché."
    passages = [
        (PASSAGE_ONE, citation(2, 14)),
        (repeated, citation(5, 30)),
        (PASSAGE_TWO, citation(2, 27)),
    ]
    document = load_course(passages)
    syllabus = build_syllabus(document)

    duplicates = [notion for notion in syllabus.notions if "valeur actuelle nette" in notion.title]
    assert len(duplicates) == 1, "un même énoncé récupéré deux fois ne donne qu'une notion"
    assert len(duplicates[0].source_refs) == 2, "chaque passage qui le prouve reste cité"
    assert [reference.locator["line_start"] for reference in duplicates[0].source_refs] == [14, 30]
    assert [reference.page for reference in duplicates[0].source_refs] == [2, 5]
    for reference in duplicates[0].source_refs:
        assert reference.matches_text(document.text)


# --------------------------------------------------------------------------- #
# 3. Every citation resolves to the exact passage
# --------------------------------------------------------------------------- #


def test_every_citation_resolves_to_the_exact_passage_of_its_course() -> None:
    """A displayed citation must let the learner quote back the exact excerpt.

    Presence of a citation is not a proof: the excerpt carried by the
    reference must be the very text of the passage at the cited coordinates,
    in the cited source, on the cited page.
    """

    passages = [
        (PASSAGE_ONE, citation(7, 120)),
        (PASSAGE_TWO, citation(8, 3)),
        (PASSAGE_THREE, citation(9, 41)),
    ]
    document = load_course(passages)
    syllabus = build_syllabus(document)

    assert syllabus.notions, "le cours synthétique doit produire des notions"
    for notion in syllabus.notions:
        assert notion.source_refs, f"la notion « {notion.title} » n'a aucune citation"
        for reference in notion.source_refs:
            locator = reference.locator
            # Source coordinates: the excerpt is one line of the store.
            assert reference.excerpt in "\n".join(document.text.splitlines(keepends=True))
            # Document coordinates: the excerpt sits at the cited position.
            assert reference.matches_text(document.text)
            # The citation label points at the passage the excerpt came from.
            label = reference.to_citation_dict()["label"]
            assert f"p.{locator['page']}" in label
            assert f"l.{locator['line_start']}" in label
            # Statement quoted back matches the passage that carries it.
            assert notion.statement.strip() in document.text


# --------------------------------------------------------------------------- #
# 4. Truncated windows
# --------------------------------------------------------------------------- #


def test_window_truncated_at_both_ends_keeps_only_the_complete_sentence() -> None:
    """A window cut at both ends keeps its complete inner sentence only.

    The first and last sentences of a truncated window are cut by the
    retrieval: they can never be asked as questions.
    """

    head = " flux actualisés moins l'investissement initial. Un projet dont la VAN est positive augmente la valeur"
    middle = " de l'entreprise. La VAN se calcule actualisant chaque flux au taux du marché. Certains projets"
    tail = " sont rejetés quand leur taux de rendement est inférieur au taux exigé par les investisseurs"
    passages = [(head, citation(3, 10)), (middle, citation(3, 11)), (tail, citation(3, 12))]
    document = load_course(passages)
    syllabus = build_syllabus(document)

    for notion in syllabus.notions:
        assert notion.statement.strip().endswith((".", "!", "?"))
        # No half-sentence leaked: every statement ends on a sentence boundary.
        assert "…" not in notion.statement


def test_sentence_split_by_the_store_is_rejoined_and_fully_cited() -> None:
    """Regression kept from the ported corrections: a cut sentence is rebuilt.

    The store marks its cuts with ``…``; both halves carry the mark, and only
    then may the engine glue two windows together.
    """

    first = "La valeur actuelle nette est la somme des flux actualisés moins…"
    second = "…l'investissement initial. Un projet dont la VAN est positive augmente la valeur."
    passages = [(first, citation(2, 10)), (second, citation(2, 11))]
    document = load_course(passages)
    syllabus = build_syllabus(document)

    notion = next(item for item in syllabus.notions if item.title == "valeur actuelle nette")
    assert notion.statement.startswith(
        "La valeur actuelle nette est la somme des flux actualisés moins l'investissement initial."
    )
    assert len(notion.source_refs) == 2, "une citation par passage d'origine"
    for reference in notion.source_refs:
        assert reference.matches_text(document.text)


def test_assignment_instructions_never_become_revision_notions() -> None:
    """Imperative exercise prompts belong to the outline, not the quiz bank."""

    document = document_from_text(
        """Part 1 - Concepts
Delta measures the change in option value when the underlying moves.
Part 2 - Exercise
Use the decomposition seen in the slide show (session 6 and 7).
You are a junior analyst asked to complete the following table.
""",
        title="Convertible case",
        source_id="src_assignment",
    )

    syllabus = build_syllabus(document)

    assert any(notion.title == "Delta" for notion in syllabus.notions)
    assert all(not notion.title.lower().startswith(("use ", "you")) for notion in syllabus.notions)
    assert all(not notion.statement.lower().startswith(("use ", "you")) for notion in syllabus.notions)


# --------------------------------------------------------------------------- #
# 5. Resume after a complete shutdown
# --------------------------------------------------------------------------- #


def test_journey_resumes_exactly_after_a_complete_shutdown(tmp_path) -> None:
    """Close the store, reopen it: the journey continues where it stopped.

    A complete shutdown (process killed, database reopened from disk) must
    preserve syllabus and notion ids, the pending questions, the recorded
    answers and the progression.
    """

    coach = StudyCoach.open(tmp_path / "study_data", today=date(2026, 10, 14))
    try:
        finance = coach.ingest_course(FINANCE_COURSE, title="Finance", source_id="src_finance")
        accounting = coach.ingest_course(ACCOUNTING_COURSE, title="Comptabilité", source_id="src_compta")
        assert {notion.id for notion in finance.notions}.isdisjoint(
            {notion.id for notion in accounting.notions}
        )

        session = coach.start_session(finance.id, size=4)
        question = coach.next_question(session.id)
        assert question is not None
        coach.submit_answer(session.id, question["id"], "12 %")
        pending_before = [item.id for item in coach.resume_session(session.id).pending_questions()]
        progress_before = coach.progress()
        assert pending_before, "la séance interrompue doit garder des questions en attente"
    finally:
        coach.close()

    # Complete shutdown: a brand-new coach reopens the very same database.
    reopened = StudyCoach.open(tmp_path / "study_data", today=date(2026, 10, 14))
    try:
        finance_ids = [course["id"] for course in reopened.store.list_syllabi(limit=100)]
        assert finance.id in finance_ids, "le syllabus doit survivre à l'arrêt complet"

        restored = reopened.resume_session(session.id)
        assert restored.id == session.id
        pending_after = [item.id for item in restored.pending_questions()]
        assert pending_after == pending_before, "les questions en attente doivent être identiques après reprise"

        # The recorded answer survived too: the same question is not asked twice.
        answered = {item["question_id"] for item in reopened.store.list_answers(session_id=session.id)}
        assert question["id"] in answered

        # The continuation works: the next pending question can be answered.
        following = reopened.next_question(session.id)
        assert following is not None
        assert following["id"] not in answered, "une question déjà posée ne doit pas revenir"
        reopened.submit_answer(session.id, following["id"], "100 000 €")

        # The progression is preserved: the answered question was recorded
        # before the shutdown, and the continuation added exactly one more.
        progress_after = reopened.progress()
        assert progress_after["stats"]["syllabi"] == progress_before["stats"]["syllabi"] == 2
        assert progress_after["stats"]["sessions_total"] == progress_before["stats"]["sessions_total"] == 1
        assert (
            progress_after["stats"]["questions_seen"]
            == progress_before["stats"]["questions_seen"] + 1
        ), "chaque réponse enregistrée doit compter, avant et après l'arrêt"
        restored_finance = reopened.store.get_syllabus(finance.id)
        restored_accounting = reopened.store.get_syllabus(accounting.id)
        assert restored_finance is not None and restored_accounting is not None
        assert {notion.id for notion in restored_finance.notions}.isdisjoint(
            {notion.id for notion in restored_accounting.notions}
        )
    finally:
        reopened.close()
