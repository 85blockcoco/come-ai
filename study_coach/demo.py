"""Reproducible demonstration of the Study Coach journey, with synthetic data.

Run it with::

    python -m study_coach.demo              # temporary data folder, then cleanup
    python -m study_coach.demo --keep       # keep the folder to inspect the database
    python -m study_coach.demo --data-dir ./demo-data

The script walks the ten steps of the learner journey, prints the corrections
with their exact course references, flags the questions that need a human or a
model, closes the engine, reopens it (simulating a restart), resumes the
session and finally proposes the next revision on the weak notions.

Everything printed comes from a synthetic course: no personal document, no
network, no credential.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from .engine import StudyCoach
from .models import Correction, ReviewSession, normalize_text
from .samples import DEMO_COURSE, DEMO_TITLE
from .sources import PersonalMemorySourceAdapter
from .syllabus import syllabus_to_markdown

DEMO_SOURCE_ID = "src_demo_finance"
TODAY = date(2026, 10, 14)

# The fictional student, matched on the *prompt* only: the demo never reads the
# answer key.  Keys are ``family::fragment of the prompt``.
STUDENT_ANSWERS: dict[str, Any] = {
    "definition::valeur actuelle nette": (
        "La valeur actuelle nette est la somme des flux de trésorerie futurs "
        "actualisés moins l'investissement initial."
    ),
    "definition::cout moyen pondere du capital": "Le CMPC est le coût moyen du financement de l'entreprise",
    "definition::flux de tresorerie disponible": "C'est un ratio de liquidité",
    "definition::ratio de rentabilite": "Le ratio de rentabilité rapporte le résultat net au chiffre d'affaires",
    "numerique::investissement initial": "12500",
    "numerique::cout de la dette": "12500",
    "numerique::taux d is": "25 %",
    "ouverte::": "La VAN sert à mesurer si un projet crée de la valeur pour l'entreprise.",
}


def rule(title: str = "") -> None:
    print()
    print("=" * 78)
    if title:
        print(title)
        print("=" * 78)


class _DemoDocumentStore:
    """Fake Côme AI document store: the public ``list_sources``/``search`` contract.

    Like the real engine, it returns *passages* (paragraphs of the course) with
    a page and a line range, not single lines.
    """

    def __init__(self, title: str, text: str, source_id: str) -> None:
        self.title = title
        self.source_id = source_id
        self._passages = self._chunk(text)

    @staticmethod
    def _chunk(text: str) -> list[tuple[int, int, str]]:
        lines = text.split("\n")
        passages: list[tuple[int, int, str]] = []
        start: int | None = None
        buffer: list[str] = []

        def flush(end_index: int) -> None:
            nonlocal buffer, start
            content = " ".join(buffer).strip()
            if content and start is not None:
                passages.append((start + 1, end_index, content))
            buffer = []
            start = None

        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                flush(index)
                continue
            if stripped.startswith("#"):
                flush(index)
                continue
            if start is None:
                start = index
            buffer.append(stripped)
            if stripped.endswith((".", "!", "?")):
                flush(index + 1)
        flush(len(lines))
        return passages

    def list_sources(self, category=None, limit=100):
        return [
            {
                "source_id": self.source_id,
                "id": self.source_id,
                "title": self.title,
                "category": category or "cours",
                "source_type": "texte",
            }
        ]

    def search(self, query, project_id=None, limit=8):
        results = [
            {
                "source_id": self.source_id,
                "title": self.title,
                "excerpt": content,
                "citation": {
                    "source_id": self.source_id,
                    "title": self.title,
                    "page": 1,
                    "line_start": line_start,
                    "line_end": line_end,
                    "label": f"{self.title} p.1 l.{line_start}-{line_end}",
                },
            }
            for line_start, line_end, content in self._passages[:limit]
        ]
        return {"query": query, "count": len(results), "results": results}


def student_answer(question: dict[str, Any]) -> Any:
    """Pick the fictional student's answer, without ever looking at the key."""

    if question["question_type"] == "qcm" and question.get("options"):
        # The learner picks the first displayed option: the key is never read.
        return [question["options"][0]["id"]]
    prompt = normalize_text(question["prompt"])
    for marker, value in STUDENT_ANSWERS.items():
        family, _, needle = marker.partition("::")
        if question["question_type"] != family:
            continue
        if needle in prompt:
            return value
    return "une réponse inventée par l'étudiant fictif"


def print_correction(correction: Correction, *, show_key: bool = True) -> None:
    icon = {"correct": "OK ", "partiel": "~  ", "incorrect": "KO ", "non_evaluable": "?  "}[correction.status]
    score = "—" if correction.score is None else f"{correction.score:g}"
    print(f"  [{icon}] statut={correction.status:<14} note={score:<4} validation={correction.validation}")
    print(f"        {correction.explanation}")
    for reference in correction.source_refs[:1]:
        citation = reference.to_citation_dict()
        print(f"        source : {citation['label']}")
        print(f"        extrait: « {reference.excerpt.strip()[:110]} »")
        print(
            "        repères : document l."
            f"{reference.document_line_start}-{reference.document_line_end} · "
            f"document original p.{citation['page']} l.{citation['line_start']}"
        )
    if show_key and correction.expected_answer:
        print(f"        attendu : {correction.expected_answer}")
    for error in correction.errors[:3]:
        print(f"        à retravailler : {error}")


def step_1_to_2(data_dir: Path) -> tuple[StudyCoach, Any]:
    rule("ÉTAPE 1-2 · Chargement du cours et extraction des notions")
    store = _DemoDocumentStore(DEMO_TITLE, DEMO_COURSE, DEMO_SOURCE_ID)
    adapter = PersonalMemorySourceAdapter(store)
    coach = StudyCoach.open(data_dir, today=TODAY)

    document = adapter.load_document(DEMO_SOURCE_ID)
    print(f"Cours chargé : « {document.title} »")
    print(f"Identifiant de source conservé : {document.source_id}")
    print(f"Passages reconstruits : {len(document.metadata.get('passages') or [])}")

    syllabus = coach.ingest_course(document=document, title=DEMO_TITLE, source_id=DEMO_SOURCE_ID)
    print()
    print(syllabus_to_markdown(syllabus))
    return coach, syllabus


def step_3(coach: StudyCoach, syllabus: Any) -> ReviewSession:
    rule("ÉTAPE 3 · Génération de 5 questions sourcées")
    session = coach.start_session(syllabus.id, size=5)
    for index, question in enumerate(session.questions, start=1):
        citation = question.source_refs[0].to_citation_dict()
        print(f"  Q{index} [{question.question_type}] {question.prompt}")
        print(f"       source : {citation['label']}")
    return session


def step_4_to_7(coach: StudyCoach, syllabus: Any, session: ReviewSession) -> list[Correction]:
    rule("ÉTAPE 4-5 · Réponses de l'étudiant fictif et corrections objectives")
    corrections: list[Correction] = []
    while (pending := coach.next_question(session.id)) is not None:
        answer = student_answer(pending)
        correction = coach.submit_answer(session.id, pending["id"], answer)
        corrections.append(correction)
        print(f"\n  Q : {pending['prompt']}")
        for option in pending.get("options") or []:
            print(f"       {option['id']}) {option['label'][:90]}")
        print(f"  R : {answer}")
        print_correction(correction)
    return corrections


def step_7_open_question(coach: StudyCoach, syllabus: Any) -> Correction:
    """One open answer: no deterministic grader may put a score on it."""

    rule("ÉTAPE 7 · Question ouverte : validation humaine ou modèle requise")
    open_session = coach.start_session(syllabus.id, size=1, families=("ouverte",), mode="revision_initiale")
    question = coach.next_question(open_session.id)
    assert question is not None
    answer = STUDENT_ANSWERS["ouverte::"]
    correction = coach.submit_answer(open_session.id, question["id"], answer)

    print(f"  Q : {question['prompt']}")
    print(f"  R : {answer}")
    print_correction(correction)
    print("        points de contrôle fournis par le cours, à vérifier par un modèle ou un humain :")
    from .questions import build_questions_for_notion

    for generated in build_questions_for_notion(syllabus.notion(correction.notion_id), syllabus, families=("ouverte",)):
        for point in generated.reference_points[:4]:
            print(f"          - {point[:100]}")
    coach.complete_session(open_session.id)
    return correction


def step_8(coach: StudyCoach, session: ReviewSession) -> dict[str, Any]:
    rule("ÉTAPE 8 · Bilan de la séance et erreurs enregistrées")
    report = coach.complete_session(session.id)
    syllabus = coach.get_syllabus(session.syllabus_id)
    for notion_id in report["notions_to_review"]:
        notion = syllabus.notion(notion_id)
        print(f"  à retravailler : {notion.title if notion else notion_id}")
        if notion:
            print(f"    {notion.source_refs[0].citation_label}")
            print(f"    « {notion.statement[:100]} »")
    print()
    print(f"  statuts : {report['by_status']}")
    return report


def step_8b_interrupt(coach: StudyCoach, syllabus: Any) -> tuple[str, int]:
    """Start a second session, answer two questions, then close the engine."""

    rule("ÉTAPE 8 bis · Séance interrompue en cours de route")
    session = coach.start_session(syllabus.id, size=4, program_index=1)
    answered = 0
    for _ in range(2):
        question = coach.next_question(session.id)
        if question is None:
            break
        coach.submit_answer(session.id, question["id"], student_answer(question))
        answered += 1
    print(f"  Séance « {session.title} » : {answered}/{len(session.questions)} questions répondues.")
    print("  L'application est fermée ici : la suite se passe après redémarrage.")
    return session.id, answered


def step_9(data_dir: Path, session_id: str, answered: int) -> dict[str, Any]:
    rule("ÉTAPE 9 · Redémarrage de l'application et reprise de la séance")
    coach = StudyCoach.open(data_dir, today=TODAY)
    try:
        resumed = coach.resume_session(session_id)
        print(f"  Séance retrouvée : {resumed.title}")
        print(f"  Statut : {resumed.status} · réponses déjà enregistrées : {resumed.current_index}/{len(resumed.questions)}")
        print(f"  Progression conservée : {answered} réponses relues depuis la base locale")

        while (question := coach.next_question(session_id)) is not None:
            print(f"\n  question en attente : {question['prompt']}")
            answer = student_answer(question)
            correction = coach.submit_answer(session_id, question["id"], answer)
            print(f"  R : {answer}")
            print_correction(correction)
        return coach.complete_session(session_id)
    finally:
        coach.close()


def step_10(data_dir: Path, session_id: str) -> dict[str, Any]:
    rule("ÉTAPE 10 · Nouvelle révision sur les notions difficiles")
    coach = StudyCoach.open(data_dir, today=TODAY)
    try:
        progress = coach.progress()
        print("  Statistiques :", progress["stats"]["questions_seen"], "questions vues,",
              progress["stats"]["sessions_completed"], "séance(s) terminée(s)")
        print("  Notions difficiles :")
        for notion in progress["notions_to_review"]:
            print(f"    - {notion['title']} ({(notion['accuracy'] * 100):.0f} % de réussite)")
        print("  Révision recommandée :")
        for item in progress["recommended_revision"]:
            print(f"    - {item['item_key']} : {item['interval_days']} j d'intervalle, "
                  f"{item['days_overdue']} j de retard, {item['lapses']} échec(s)")
        resumed = coach.start_session(coach.list_courses()[0]["id"], size=2, due_only=True, mode="revision_espacee")
        print(f"\n  Séance de révision espacee prête : {len(resumed.questions)} question(s)")
        for question in resumed.questions:
            print(f"    [{question.question_type}] {question.prompt[:90]}")
        return progress
    finally:
        coach.close()


def _interactive_session(coach: StudyCoach, syllabus: Any) -> None:
    """Run an interactive review session where the user answers questions."""
    
    rule("MODE INTERACTIF · Session de révision")
    print("Commandes: 'q' pour quitter, 's' pour passer, 'a' pour abandonner la session")
    print()
    
    session = coach.start_session(syllabus.id, size=5)
    print(f"Session démarrée: {session.title}")
    print(f"{len(session.questions)} question(s) au programme")
    print()
    
    while True:
        question = coach.next_question(session.id)
        if question is None:
            print("\nPlus de questions. Session terminée.")
            report = coach.complete_session(session.id)
            print(f"Bilan: {report['by_status']}")
            break
        
        sources = question.get("sources", [])
        source_label = sources[0]["label"] if sources else "inconnue"
        print(f"\n{'='*70}")
        print(f"Q [{question['question_type']}] {question['prompt']}")
        print(f"   Source: {source_label}")
        
        if question.get("options"):
            for option in question["options"]:
                print(f"   {option['id']}) {option['label']}")
        
        print("-" * 70)
        answer = input("Votre réponse: ").strip()
        
        if answer.lower() in ('q', 'quit', 'exit'):
            print("Session abandonnée (progression sauvegardée).")
            coach.close()
            return
        elif answer.lower() in ('s', 'skip'):
            print("Question passée.")
            # Submit empty answer to skip
            coach.submit_answer(session.id, question["id"], "")
            continue
        elif answer.lower() in ('a', 'abort'):
            print("Session abandonnée sans sauvegarder cette réponse.")
            return
        
        correction = coach.submit_answer(session.id, question["id"], answer)
        print_correction(correction, show_key=True)
    
    coach.close()


def _export_anki_csv(coach: StudyCoach, syllabus: Any, output_path: Path) -> None:
    """Export notions as Anki-compatible CSV."""
    import csv
    
    rows = coach.export_for_anki(syllabus_id=syllabus.id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Front", "Back", "Tags"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"✅ Export Anki: {len(rows)} cartes → {output_path}")


def _export_progress_csv(coach: StudyCoach, syllabus: Any, output_path: Path) -> None:
    """Export progress as CSV for analysis."""
    import csv
    
    rows = coach.export_progress_csv(syllabus_id=syllabus.id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["notion_id", "notion_title", "question_type", "status", "score", "answered_at", "syllabus_id"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"✅ Export progression: {len(rows)} lignes → {output_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Démonstration Study Coach (données synthétiques).")
    parser.add_argument("--data-dir", default="", help="dossier de données (défaut : temporaire, supprimé à la fin)")
    parser.add_argument("--keep", action="store_true", help="conserver le dossier de données")
    parser.add_argument("--interactive", action="store_true", help="lancer une session de révision interactive")
    parser.add_argument("--export-anki", metavar="FILE", help="exporter les cartes au format Anki (CSV)")
    parser.add_argument("--export-progress", metavar="FILE", help="exporter la progression (CSV)")
    arguments = parser.parse_args(argv)

    temporary = not arguments.data_dir
    data_dir = Path(arguments.data_dir) if arguments.data_dir else Path(tempfile.mkdtemp(prefix="study-coach-demo-"))

    rule("DÉMONSTRATION STUDY COACH V1 — données 100 % synthétiques, aucun accès réseau")
    try:
        coach, syllabus = step_1_to_2(data_dir)
        
        if arguments.export_anki:
            _export_anki_csv(coach, syllabus, Path(arguments.export_anki))
        elif arguments.export_progress:
            _export_progress_csv(coach, syllabus, Path(arguments.export_progress))
        elif arguments.interactive:
            _interactive_session(coach, syllabus)
        else:
            session = step_3(coach, syllabus)
            step_4_to_7(coach, syllabus, session)
            step_7_open_question(coach, syllabus)
            step_8(coach, session)
            interrupted_id, answered = step_8b_interrupt(coach, syllabus)
            coach.close()

            step_9(data_dir, interrupted_id, answered)
            step_10(data_dir, interrupted_id)

            rule("FIN · Le parcours est complet")
            print("  Cours synthétique → notions sourcées → 5 questions → réponses → corrections")
            print("  → suivi des erreurs → reprise après redémarrage → révision espacee.")
            if arguments.keep:
                print(f"\n  Données conservées dans : {data_dir}")
        return 0
    finally:
        if temporary and not arguments.keep:
            shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit(main())
