"""CLI handlers for `nage.py vc`."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .cases import case_payload, case_result_payload, evaluate_case
from .content import load_content
from .cram import (
    FORMULA_GROUPS,
    TRAPS,
    formula_payload,
    plan_blocks,
    render_html,
    render_markdown,
)
from .drills import drill_payload, grade_drill, random_drill
from .errors import ContentError, InputError, StorageError, VcError
from .exams import (
    build_exam,
    exam_payload,
    grade_exam,
    oral_questions,
    record_exam_result,
)
from .mastery import build_study_plan, coverage_report, mastery_radar, radar_payload
from .pastpapers import answer_template, find_paper, grade_paper, load_papers, paper_payload
from .report import build_progress_report
from .scheduler import (
    answer_session,
    current_card,
    session_payload,
    session_status,
    start_session,
)
from .storage import VcStore


def _emit(payload: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                print(f"{key}:")
                print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
            else:
                print(f"{key}: {value}")
    else:
        print(payload)


def _pts(value: float) -> str:
    return f"{value:g} pt" + ("" if value == 1 else "s")


def _store(args) -> VcStore:
    home = getattr(args, "home", None)
    return VcStore(Path(home) if home else None)


def _load_session(store: VcStore, session_id: str):
    session = store.load_active_session()
    if session is None or session.session_id != session_id:
        raise InputError("Active session not found. Restart `vc review`.")
    return session


def _add_common(parser) -> None:
    parser.add_argument("--json", action="store_true", help="Sortie JSON")
    parser.add_argument("--home", type=Path, default=None, help="Dossier VC local")


def build_vc_parser(parser) -> None:
    sub = parser.add_subparsers(dest="vc_action")

    review = sub.add_parser("review", help="Active recall session")
    review.add_argument("--minutes", type=int, default=10)
    review.add_argument("--mode", choices=("quick", "long", "exam_eve", "custom"), default="quick")
    review.add_argument("--today", default=None)
    review.add_argument("--session", default=None)
    review.add_argument("--reveal", action="store_true")
    review.add_argument("--grade", choices=("again", "hard", "good", "easy"), default=None)
    review.add_argument("--status", action="store_true")
    _add_common(review)

    drill = sub.add_parser("drill", help="Drills de formules VC")
    drill_sub = drill.add_subparsers(dest="drill_action", required=True)
    drill_list = drill_sub.add_parser("list", help="Lister les drills")
    drill_list.add_argument("--topic", default=None)
    _add_common(drill_list)
    drill_run = drill_sub.add_parser("run", help="Lancer un drill")
    drill_run.add_argument("drill_id")
    drill_run.add_argument("--answer", default=None)
    _add_common(drill_run)
    drill_random = drill_sub.add_parser("random", help="Tirer un drill")
    drill_random.add_argument("--topic", default=None)
    drill_random.add_argument("--seed", type=int, default=0)
    drill_random.add_argument("--answer", default=None)
    _add_common(drill_random)

    case = sub.add_parser("case", help="Cas VC")
    case_sub = case.add_subparsers(dest="case_action", required=True)
    case_list = case_sub.add_parser("list", help="Lister les cas")
    case_list.add_argument("--topic", default=None)
    _add_common(case_list)
    case_show = case_sub.add_parser("show", help="Afficher un cas")
    case_show.add_argument("case_id")
    _add_common(case_show)
    case_grade = case_sub.add_parser("grade", help="Corriger un cas")
    case_grade.add_argument("case_id")
    case_grade.add_argument("--answers", required=True, type=Path)
    _add_common(case_grade)

    diagnostic = sub.add_parser("diagnostic", help="Initial diagnostic exam (from zero)")
    diagnostic_sub = diagnostic.add_subparsers(dest="diagnostic_action")
    diagnostic_start = diagnostic_sub.add_parser("start", help="Start a diagnostic exam")
    diagnostic_start.add_argument("--questions", type=int, default=15)
    diagnostic_start.add_argument("--minutes", type=int, default=20)
    diagnostic_start.add_argument("--seed", type=int, default=42)
    diagnostic_start.set_defaults(diagnostic_action="start")
    _add_common(diagnostic_start)
    diagnostic_submit = diagnostic_sub.add_parser("submit", help="Submit diagnostic answers")
    diagnostic_submit.add_argument("exam_id")
    diagnostic_submit.add_argument("--answers", required=True, type=Path)
    diagnostic_submit.add_argument("--now", default=None)
    diagnostic_submit.set_defaults(diagnostic_action="submit")
    _add_common(diagnostic_submit)

    exam = sub.add_parser("exam", help="Timed mock exam")
    exam_sub = exam.add_subparsers(dest="exam_action", required=True)
    exam_start = exam_sub.add_parser("start", help="Start or resume an exam")
    exam_start.add_argument("--questions", type=int, default=20)
    exam_start.add_argument("--minutes", type=int, default=90)
    exam_start.add_argument("--seed", type=int, default=0)
    exam_start.add_argument("--topic", action="append", default=[])
    exam_start.add_argument("--new", action="store_true", help="Remplacer l'examen actif")
    _add_common(exam_start)
    exam_submit = exam_sub.add_parser("submit", help="Submit answers")
    exam_submit.add_argument("exam_id")
    exam_submit.add_argument("--answers", required=True, type=Path)
    exam_submit.add_argument("--now", default=None, help="Injected clock (tests)")
    _add_common(exam_submit)

    exam_review = exam_sub.add_parser("review", help="Review the last exam")
    exam_review.set_defaults(review_last=True)
    _add_common(exam_review)

    oral = sub.add_parser("oral", help="Simulated oral with follow-ups")
    oral.add_argument("topic_id")
    oral.add_argument("--count", type=int, default=5)
    oral.add_argument("--grade", action="store_true", help="Grade answers from a file")
    oral.add_argument("--answers", type=Path, default=None, help="Answers JSON (card_id -> text)")
    _add_common(oral)

    notes = sub.add_parser("notes", help="Importer et approuver des notes de cours")
    notes_sub = notes.add_subparsers(dest="notes_action", required=True)
    notes_ingest = notes_sub.add_parser("ingest", help="Propose cited cards")
    notes_ingest.add_argument("file", type=Path)
    notes_ingest.add_argument("--topic", required=True)
    notes_ingest.add_argument(
        "--replace", action="store_true", help="Replace a modified source"
    )
    notes_ingest.add_argument(
        "--auto-approve", action="store_true", help="Auto-approve proposals that already have an answer"
    )
    _add_common(notes_ingest)
    notes_list = notes_sub.add_parser("list", help="Lister sources et propositions")
    _add_common(notes_list)
    notes_approve = notes_sub.add_parser("approve", help="Ajouter une carte au deck")
    notes_approve.add_argument("proposal_id")
    notes_approve.add_argument(
        "--answer", default=None, help='Complete a "to be completed" proposal'
    )
    _add_common(notes_approve)
    notes_reject = notes_sub.add_parser("reject", help="Rejeter une proposition")
    notes_reject.add_argument("proposal_id")
    _add_common(notes_reject)

    paper = sub.add_parser("paper", help="Real EDHEC 2023-2025 papers with solutions")
    paper_sub = paper.add_subparsers(dest="paper_action", required=True)
    paper_list = paper_sub.add_parser("list", help="Lister les sujets disponibles")
    _add_common(paper_list)
    paper_show = paper_sub.add_parser("show", help="Afficher un sujet")
    paper_show.add_argument("year", type=int)
    paper_show.add_argument("--solutions", action="store_true", help="Include solutions")
    paper_show.add_argument("--section", default=None, help="Filtrer une section (A, B, C)")
    _add_common(paper_show)
    paper_grade = paper_sub.add_parser("grade", help="Grade an answers file")
    paper_grade.add_argument("year", type=int)
    paper_grade.add_argument("--answers", required=True, type=Path)
    _add_common(paper_grade)
    paper_template = paper_sub.add_parser("template", help="Generate an empty answers file")
    paper_template.add_argument("year", type=int)
    paper_template.add_argument("--output", type=Path, default=None)
    _add_common(paper_template)

    cram = sub.add_parser("cram", help="Battle plan + formula sheet")
    cram.add_argument("--minutes", type=int, default=90)
    cram.add_argument("--hours", type=int, default=None, help="Hours available (overrides --minutes)")
    cram.add_argument("--focus", choices=["all", "weak"], default="all", help="Focus on weak topics only")
    cram.add_argument("--html", type=Path, default=None, help="Write the HTML sheet")
    cram.add_argument("--markdown", type=Path, default=None, help="Write the Markdown sheet")
    cram.add_argument("--json", action="store_true")
    cram.add_argument("--home", type=Path, default=None, help="Dossier VC local")

    predict = sub.add_parser("predict", help="Predict likely exam questions")
    predict.add_argument("--count", type=int, default=10, help="Number of questions")
    _add_common(predict)

    formulas = sub.add_parser("formulas", help="Fiche de formules VC")
    formulas.add_argument("--json", action="store_true")

    radar = sub.add_parser("radar", help="Mastery radar")
    radar.add_argument("--today", default=None)
    _add_common(radar)

    coverage = sub.add_parser("coverage", help="Coverage of topics by content type")
    _add_common(coverage)

    schedule = sub.add_parser("schedule", help="Day-by-day study schedule up to the exam")
    schedule.add_argument("--days", type=int, default=7, help="Number of days")
    schedule.add_argument("--daily-minutes", type=int, default=60, help="Daily capacity in minutes")
    schedule.add_argument("--today", default=None)
    schedule.add_argument("--exam-date", default=None)
    _add_common(schedule)

    plan = sub.add_parser("plan", help="Bounded study plan")
    plan.add_argument("--minutes", type=int, default=60)
    plan.add_argument("--today", default=None)
    plan.add_argument("--exam-date", default=None)
    _add_common(plan)

    next = sub.add_parser("next", help="Meilleure activité à faire maintenant")
    next.add_argument("--minutes", type=int, default=20)
    next.add_argument("--today", default=None)
    next.add_argument("--exam-date", default=None)
    _add_common(next)

    export = sub.add_parser("export", help="Export VC progress to JSON")
    export.add_argument("--output", type=Path, default=None, help="Output file")
    export.add_argument("--study-coach", action="store_true", help="Export in Study Coach format")
    _add_common(export)

    errors = sub.add_parser("errors", help="Error dashboard by category and topic")
    _add_common(errors)

    exam_date = sub.add_parser("exam-date", help="Show or set the exam date")
    exam_date.add_argument("date", nargs="?", default=None, help="Date AAAA-MM-JJ")
    exam_date.add_argument("--time", default=None, help="Heure HH:MM")
    exam_date.add_argument("--duration", type=int, default=None, help="Duration in minutes")
    _add_common(exam_date)

    report = sub.add_parser("report", help="Rapport de progression")
    report.add_argument("--days", type=int, default=30)
    report.add_argument("--today", default=None)
    _add_common(report)

    glossary = sub.add_parser("glossary", help="Lexique VC FR/EN")
    glossary_sub = glossary.add_subparsers(dest="glossary_action", required=True)
    glossary_search = glossary_sub.add_parser("search", help="Chercher un terme")
    glossary_search.add_argument("query")
    _add_common(glossary_search)

    term_sheet = sub.add_parser("term-sheet", help="Decode a term sheet")
    term_sub = term_sheet.add_subparsers(dest="term_sheet_action", required=True)
    term_decode = term_sub.add_parser("decode", help="Decode a text file")
    term_decode.add_argument("file", type=Path)
    _add_common(term_decode)

    delete = sub.add_parser("delete", help="Delete local VC data")
    delete.add_argument("--confirm", required=True)
    _add_common(delete)

    # VC Tutor IA hybride
    serve = sub.add_parser("serve", help="Serve the offline VC hub over HTTP (local only)")
    serve.add_argument("--host", default="127.0.0.1", help="Host to bind (default 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8765, help="Port to bind (default 8765)")
    serve.add_argument("--open", action="store_true", help="Open the hub in the default browser")
    _add_common(serve)

    time_cmd = sub.add_parser("time", help="Track study time by topic")
    time_sub = time_cmd.add_subparsers(dest="time_action")
    time_log = time_sub.add_parser("log", help="Log a study session")
    time_log.add_argument("--topic", required=True)
    time_log.add_argument("--minutes", type=int, required=True)
    _add_common(time_log)
    time_report = time_sub.add_parser("report", help="Show time summary")
    _add_common(time_report)
    time_cmd.set_defaults(time_action="report")

    tutor = sub.add_parser("tutor", help="Source-grounded local tutor (cloud disabled)")
    tutor_sub = tutor.add_subparsers(dest="tutor_cmd", required=True)
    tutor_explain = tutor_sub.add_parser("explain", help="Expliquer un concept/calcul")
    tutor_explain.add_argument("--question", "-q")
    tutor_explain.add_argument("--answer", "-a")
    _add_common(tutor_explain)
    tutor_debug = tutor_sub.add_parser("debug", help="Debug a calculation step by step")
    tutor_debug.add_argument("--question", "-q")
    tutor_debug.add_argument("--answer", "-a")
    _add_common(tutor_debug)
    tutor_oral = tutor_sub.add_parser("oral", help="Simuler un oral d'examen")
    tutor_oral.add_argument("--topic", "-t")
    _add_common(tutor_oral)

    # VC Master - unified exam prep tool (experimental, same exam date as VC)
    master = sub.add_parser("master", help="VC Master - revise and prepare for the exam")
    master_sub = master.add_subparsers(dest="master_cmd")
    master_status = master_sub.add_parser("status", help="Vue d'ensemble")
    master_status.set_defaults(master_cmd="status")
    master_set = master_sub.add_parser("set-exam", help="Set the exam date and time")
    master_set.add_argument("date", help="Date AAAA-MM-JJ")
    master_set.add_argument("time", nargs="?", default=None, help="Time HH:MM (default 16:00)")
    master_set.add_argument("--duration", type=int, default=None, help="Duration in minutes (default 90)")
    master_set.set_defaults(master_cmd="set-exam")
    master_sprint = master_sub.add_parser("sprint", help="Sprint intelligent")
    master_sprint.add_argument("hours", nargs="?", type=int, default=3)
    master_sprint.set_defaults(master_cmd="sprint")
    master_formulas = master_sub.add_parser("formulas", help="Drills de formules")
    master_formulas.set_defaults(master_cmd="formulas")
    master_terms = master_sub.add_parser("terms", help="Clauses de term sheet")
    master_terms.set_defaults(master_cmd="terms")
    master_cases = master_sub.add_parser("cases", help="Cas disponibles")
    master_cases.set_defaults(master_cmd="cases")
    master_sim = master_sub.add_parser("simulate", help="Simuler examen")
    master_sim.add_argument("minutes", nargs="?", type=int, default=60)
    master_sim.set_defaults(master_cmd="simulate")
    master_rev = master_sub.add_parser("revise", help="Targeted revision")
    master_rev.set_defaults(master_cmd="revise")


def _review(args, store: VcStore, content) -> int:
    if args.session:
        session = _load_session(store, args.session)
        progress = store.load_progress()
        if args.status:
            _emit(session_status(session, content), args.json)
            return 0
        if args.grade:
            session, event = answer_session(store, content, session, args.grade)
            payload = session_payload(session, content, store.load_progress())
            payload["last_result"] = {
                "card_id": event.card_id,
                "grade": event.grade,
                "due_after": event.due_after,
            }
            _emit(payload, args.json)
            return 0
        payload = session_payload(session, content, progress, reveal=args.reveal)
        _emit(payload, args.json)
        return 0

    if args.grade:
        raise InputError("--grade exige --session.")
    session = start_session(
        store, content, minutes=args.minutes, mode=args.mode, today=args.today
    )
    if args.json:
        _emit(session_payload(session, content, store.load_progress()), True)
        return 0
    return _interactive_review(store, content, session)


def _interactive_review(store: VcStore, content, session) -> int:
    print(
        f"Session {session.mode} — {session.target_minutes} min — "
        f"{len(session.card_ids)} carte(s)."
    )
    if not session.card_ids:
        print("Aucune carte due. Lancez un drill ou ajoutez du contenu.")
        return 0
    while True:
        card = current_card(store, content, session)
        if card is None:
            break
        started = time.monotonic()
        print()
        print(f"[{session.cursor + 1}/{len(session.card_ids)}] {card.topic_id} — {card.question}")
        try:
            input("Press Enter to reveal... ")
        except (EOFError, KeyboardInterrupt):
            print("\nSession kept. Resume with `vc review`.")
            return 0
        print(f"Answer: {card.answer}")
        if card.explanation:
            print(f"Pourquoi : {card.explanation}")
        while True:
            try:
                grade = input("Note (again/hard/good/easy) : ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nSession kept. Resume with `vc review`.")
                return 0
            if grade in ("again", "hard", "good", "easy"):
                break
            print("Note invalide. Utilisez again, hard, good ou easy.")
        duration = int(time.monotonic() - started)
        session, event = answer_session(
            store, content, session, grade, duration_seconds=duration
        )
        print(f"Card rescheduled to {event.due_after}.")
    summary = session_payload(session, content, store.load_progress())["summary"]
    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


def _drill(args, store: VcStore, content) -> int:
    if args.drill_action == "list":
        drills = [
            drill_payload(drill)
            for drill in content.drills
            if args.topic is None or drill.topic_id == args.topic
        ]
        _emit({"drills": drills}, args.json)
        return 0
    if args.drill_action == "run":
        drill = content.drill(args.drill_id)
    else:
        drill = random_drill(content.drills, topic_id=args.topic, seed=args.seed)
    if args.answer is None:
        _emit(drill_payload(drill), args.json)
        return 0
    result = grade_drill(drill, args.answer)
    from .dates import new_id, now_iso
    from .models import DrillAttempt

    given = result.get("given")
    given_value = None
    if isinstance(given, dict):
        given_value = given.get("value")
    store.append_drill_attempt(
        DrillAttempt(
            attempt_id=new_id("drill"),
            drill_id=drill.id,
            topic_id=drill.topic_id,
            answer=args.answer,
            accepted=bool(result.get("accepted")),
            expected=float(result.get("expected", drill.answer)),
            expected_unit=str(result.get("expected_unit", drill.answer_unit)),
            given_value=given_value,
            diagnostic=result.get("diagnostic"),
            submitted_at=now_iso(),
            message=str(result.get("message", "")),
        )
    )
    _emit(result, args.json)
    return 0


def _case(args, store: VcStore, content) -> int:
    if args.case_action == "list":
        cases = [
            {
                "case_id": case.id,
                "topic_id": case.topic_id,
                "title": case.title,
                "difficulty": case.difficulty,
            }
            for case in content.cases
            if args.topic is None or case.topic_id == args.topic
        ]
        _emit({"cases": cases}, args.json)
        return 0
    if args.case_action == "show":
        _emit(case_payload(content.case(args.case_id)), args.json)
        return 0
    try:
        answers = json.loads(args.answers.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise InputError(f"Answers file not found: {args.answers}") from error
    except json.JSONDecodeError as error:
        raise InputError(f"Invalid answers JSON: {error.msg}") from error
    if not isinstance(answers, dict):
        raise InputError("Answers file must be a JSON object mapping question -> text.")
    attempt = evaluate_case(content.case(args.case_id), answers)
    store.append_case_attempt(attempt)
    _emit(case_result_payload(attempt), args.json)
    return 0


def _read_answers(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise InputError(f"Answers file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise InputError(f"Invalid answers JSON: {error.msg}") from error
    if not isinstance(payload, dict):
        raise InputError("Answers file must be a JSON object mapping question -> answer.")
    answers: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            raise InputError(f"Invalid answer for {key}: text expected.")
        answers[str(key)] = "" if value is None else str(value)
    return answers


def _diagnostic(args, store: VcStore, content) -> int:
    action = getattr(args, "diagnostic_action", None) or "start"
    if action == "start":
        active = store.load_active_exam()
        if active is not None:
            store.clear_active_exam()
        exam = build_exam(content, questions=args.questions, minutes=args.minutes, seed=args.seed)
        store.save_active_exam(exam)
        payload = exam_payload(exam, content)
        payload["resumed"] = False
        payload["diagnostic"] = True
        payload["notice"] = "Diagnostic exam: answer honestly, do not guess."
        _emit(payload, args.json)
        return 0
    if action == "submit":
        active = store.load_active_exam()
        if active is None or active.exam_id != args.exam_id:
            raise InputError("Active exam not found. Restart `vc diagnostic start`.")
        active.answers.update(_read_answers(args.answers))
        result = grade_exam(active, content, now=args.now)
        record_exam_result(store, result)
        # Diagnostic summary
        per_topic = result.get("per_topic", {})
        for topic_id, value in per_topic.items():
            maximum = float(value.get("max", 0) or 0)
            earned = float(value.get("earned", 0) or 0)
            value["percent"] = round(100.0 * earned / maximum, 2) if maximum else 0.0
        sorted_topics = sorted(per_topic.items(), key=lambda item: item[1].get("percent", 0))
        weakest = [t for t, v in sorted_topics if v.get("percent", 100) < 60][:3]
        summary = {
            "exam_id": result["exam_id"],
            "score": result["score"],
            "per_topic": per_topic,
            "weakest_topics": weakest,
            "recommendation": ("Focus on: " + ", ".join(weakest)) if weakest else "All topics solid.",
            "next_step": "Run `vc plan --minutes 60` for a targeted revision plan.",
        }
        _emit(summary, args.json)
        return 0
    raise InputError("Unknown diagnostic action.")


def _time(args, store: VcStore, content) -> int:
    from .dates import now_iso

    action = getattr(args, "time_action", None) or "report"
    if action == "log":
        entry = {
            "topic_id": args.topic,
            "minutes": args.minutes,
            "recorded_at": now_iso(),
        }
        store.append_time_entry(entry)
        _emit({"logged": True, **entry}, args.json)
        return 0
    entries = store.load_time_entries()
    by_topic: dict[str, int] = {}
    for entry in entries:
        tid = entry.get("topic_id", "")
        by_topic[tid] = by_topic.get(tid, 0) + int(entry.get("minutes", 0) or 0)
    total = sum(by_topic.values())
    _emit({"total_minutes": total, "by_topic": by_topic, "entries": len(entries)}, args.json)
    return 0


def _exam(args, store: VcStore, content) -> int:
    if args.exam_action == "start":
        active = store.load_active_exam()
        if active is not None and not args.new:
            payload = exam_payload(active, content)
            payload["resumed"] = True
            _emit(payload, args.json)
            return 0
        if active is not None:
            store.clear_active_exam()
        exam = build_exam(
            content,
            questions=args.questions,
            minutes=args.minutes,
            seed=args.seed,
            topic_ids=args.topic,
        )
        store.save_active_exam(exam)
        payload = exam_payload(exam, content)
        payload["resumed"] = False
        _emit(payload, args.json)
        return 0

    if args.exam_action == "submit":
        active = store.load_active_exam()
        if active is None or active.exam_id != args.exam_id:
            raise InputError("Active exam not found. Restart `vc exam start`.")
        active.answers.update(_read_answers(args.answers))
        result = grade_exam(active, content, now=args.now)
        record_exam_result(store, result)
        _emit(result, args.json)
        return 0

    if args.exam_action == "review":
        history = store.load_exam_history()
        if not history:
            raise InputError("No exam history available.")
        result = history[-1]
        per_topic = result.get("per_topic", {})
        weak = [t for t, v in per_topic.items() if isinstance(v, dict) and (v.get("earned", 0) / max(v.get("max", 1), 1)) < 0.6]
        _emit({"exam_id": result.get("exam_id"), "score": result.get("score"), "per_topic": per_topic, "weak_topics": weak, "next_step": "Run `vc plan --minutes 60`."}, args.json)
        return 0

    raise InputError("Unknown exam action.")


def _oral(args, store: VcStore, content) -> int:
    if getattr(args, "grade", False):
        if not args.answers:
            raise InputError("--answers is required with --grade.")
        answers = _read_answers(args.answers)
        questions = oral_questions(content, args.topic_id, count=args.count)
        results = []
        for question in questions:
            card = content.card(question["question_id"])
            given = answers.get(question["question_id"], "")
            from .notes import normalize_text

            expected_words = set(normalize_text(card.answer).split())
            given_words = set(normalize_text(given).split())
            overlap = len(expected_words & given_words) / len(expected_words) if expected_words else 0.0
            results.append(
                {
                    "question_id": question["question_id"],
                    "score": round(overlap, 4),
                    "passed": overlap >= 0.5,
                }
            )
        _emit({"topic_id": args.topic_id, "results": results}, args.json)
        return 0
    questions = oral_questions(content, args.topic_id, count=args.count)
    _emit(
        {
            "topic_id": args.topic_id,
            "count": len(questions),
            "questions": questions,
            "notice": "Simulated oral: follow-ups never show the model solution.",
        },
        args.json,
    )
    return 0


def _notes(args, store: VcStore, content) -> int:
    from .notes import (
        approve_proposal,
        ingest_file,
        list_notes,
        reject_proposal,
    )

    if args.notes_action == "ingest":
        try:
            content.topic(args.topic)
        except ContentError as error:
            raise InputError(f"Unknown topic: {args.topic}") from error
        result = ingest_file(
            store, args.file, topic_id=args.topic, replace=args.replace
        )
        approved = 0
        if getattr(args, "auto_approve", False):
            for proposal in list_notes(store).get("proposals", []):
                if proposal.get("status") != "proposed":
                    continue
                if not proposal.get("answer"):
                    continue
                try:
                    approve_proposal(store, proposal["proposal_id"])
                    approved += 1
                except Exception:
                    continue
        result["auto_approved"] = approved
        _emit(result, args.json)
        return 0
    if args.notes_action == "list":
        _emit(list_notes(store), args.json)
        return 0
    if args.notes_action == "approve":
        card = approve_proposal(store, args.proposal_id, answer=args.answer)
        _emit({"approved": True, "card": card.to_dict()}, args.json)
        return 0
    if args.notes_action == "reject":
        reject_proposal(store, args.proposal_id)
        _emit({"rejected": True, "proposal_id": args.proposal_id}, args.json)
        return 0
    raise InputError("Action de notes inconnue.")


def _print_paper(paper, *, solutions: bool = False, section: str | None = None) -> None:
    if section:
        section = section.upper()
        known = {item["id"] for item in paper.sections}
        if section not in known:
            raise InputError(
                f"Section inconnue : {section}. Sections : {', '.join(sorted(known))}."
            )
    questions = [
        question
        for question in paper.questions
        if section is None or question.section == section
    ]
    print(f"{paper.title} — {paper.duration_minutes} min — {_pts(paper.points)}")
    print(f"Source : {paper.source}")
    print()
    for question in questions:
        print(
            f"Q{question.number} [{question.section}] {_pts(question.points)} "
            f"— {question.topic_id}"
        )
        print(question.prompt)
        for choice in question.choices:
            print(f"  {choice.label}. {choice.text}")
        for part in question.parts:
            print(f"  {part.id}. {part.prompt}")
            if solutions:
                if part.answer:
                    print(f"     Answer: {part.answer}")
                print(f"     Solution: {part.solution}")
        if solutions:
            if question.answer and not question.parts:
                print(f"  Answer: {question.answer}")
            if question.solution:
                print(f"  Solution: {question.solution}")
        print()


def _paper(args, store: VcStore, content) -> int:
    papers = load_papers()
    if args.paper_action == "list":
        payload = {
            "papers": [
                {
                    "year": paper.year,
                    "paper_id": paper.paper_id,
                    "title": paper.title,
                    "duration_minutes": paper.duration_minutes,
                    "questions": len(paper.questions),
                    "points": paper.points,
                    "sections": [section["id"] for section in paper.sections],
                }
                for paper in papers
            ],
            "notice": "Papers derived from EDHEC past exams; solutions included.",
        }
        _emit(payload, args.json)
        return 0

    paper = find_paper(args.year, papers)

    if args.paper_action == "show":
        if args.json:
            _emit(
                paper_payload(paper, solutions=args.solutions),
                True,
            )
        else:
            _print_paper(paper, solutions=args.solutions, section=args.section)
        return 0

    if args.paper_action == "template":
        template = answer_template(paper)
        if args.output:
            args.output.write_text(
                json.dumps(template, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            _emit({"written": str(args.output), "answers": len(template)}, args.json)
        else:
            _emit(template, args.json)
        return 0

    if args.paper_action == "grade":
        answers_path = args.answers
        try:
            answers = json.loads(answers_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise InputError(f"Answers file not found: {answers_path}") from error
        except json.JSONDecodeError as error:
            raise InputError(f"Invalid answers JSON: {error.msg}") from error
        result = grade_paper(paper, answers)
        from .dates import new_id, now_iso
        from .models import PaperAttempt

        per_topic: dict[str, dict[str, float]] = {}
        for item in result.get("items", []):
            if item.get("status") == "self_assess":
                continue
            topic_id = str(item.get("topic_id") or "")
            if not topic_id:
                continue
            bucket = per_topic.setdefault(topic_id, {"attempts": 0, "correct": 0, "earned": 0.0, "max": 0.0})
            bucket["attempts"] += 1
            if item.get("status") == "correct":
                bucket["correct"] += 1
            bucket["earned"] += float(item.get("earned") or 0.0)
            bucket["max"] += float(item.get("max") or 0.0)
        store.append_paper_attempt(
            PaperAttempt(
                attempt_id=new_id("paper"),
                paper_id=paper.paper_id,
                year=paper.year,
                submitted_at=now_iso(),
                auto_points=float(result.get("auto_points", 0.0)),
                auto_max=float(result.get("auto_max", 0.0)),
                auto_percent=float(result["auto_percent"]) if result.get("auto_percent") is not None else None,
                per_topic=per_topic,
                self_assessment_points=float(result.get("self_assessment_points", 0.0)),
                notice=str(result.get("notice", "")),
            )
        )
        if args.json:
            _emit(result, True)
            return 0
        print(
            f"{paper.title} — auto-correction : "
            f"{result['auto_points']:g}/{result['auto_max']:g} "
            f"({result['auto_percent']}%)"
        )
        for item in result["items"]:
            if item["status"] == "self_assess":
                print(f"- {item['question_id']} : to self-assess")
                continue
            marker = {
                "correct": "OK",
                "incorrect": "NON",
                "missing": "VIDE",
            }.get(item["status"], item["status"])
            expected = item.get("expected")
            given = item.get("given")
            print(
                f"- {item['question_id']} : {marker} "
                f"(given {given!r}, expected {expected!r})"
            )
            if item["status"] != "correct" and item.get("solution"):
                print(f"  Solution: {item['solution']}")
        print()
        print(result["notice"])
        return 0

    raise InputError("Action de sujet inconnue.")


def _predict(args, store: VcStore, content) -> int:
    from .dates import today_iso
    from .mastery import mastery_radar
    from .predict import predict_questions

    day = today_iso()
    records = mastery_radar(
        content, store.load_reviews(), today=day,
        case_attempts=store.load_case_attempts(),
        exam_results=store.load_exam_history(),
        drill_attempts=store.load_drill_attempts(),
        paper_attempts=store.load_paper_attempts(),
        progress=store.load_progress(),
    )
    questions = predict_questions(content, records, count=args.count)
    _emit({"questions": questions, "count": len(questions)}, args.json)
    return 0


def _formulas(args, store: VcStore, content) -> int:
    payload = formula_payload()
    if args.json:
        _emit(payload, True)
        return 0
    print("FICHE DE FORMULES VC — EDHEC")
    print()
    for group in FORMULA_GROUPS:
        print(group.title)
        for item in group.items:
            print(f"  • {item.name}")
            print(f"    {item.formula}")
            print(f"    {item.note}")
        print()
    print("LES PIÈGES QUI COÛTENT DES POINTS")
    for index, (wrong, right, why) in enumerate(TRAPS, start=1):
        print(f"  {index}. {wrong} → {right}")
        print(f"     {why}")
    return 0


def _cram(args, store: VcStore, content) -> int:
    minutes = args.minutes
    if getattr(args, "hours", None):
        minutes = args.hours * 60
    args.minutes = minutes
    papers = load_papers()
    blocks = plan_blocks(minutes)
    if getattr(args, "focus", "all") == "weak":
        from .dates import today_iso
        from .mastery import mastery_radar

        day = today_iso()
        records = mastery_radar(
            content, store.load_reviews(), today=day,
            case_attempts=store.load_case_attempts(),
            exam_results=store.load_exam_history(),
            drill_attempts=store.load_drill_attempts(),
            paper_attempts=store.load_paper_attempts(),
            progress=store.load_progress(),
        )
        weak = [r.topic_id for r in records if r.status in ("fragile", "untested", "developing")]
        if not args.json:
            print("WEAK TOPICS:", ", ".join(weak) if weak else "none")
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        args.html.write_text(
            render_html(papers, minutes=args.minutes), encoding="utf-8"
        )
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(
            render_markdown(papers, minutes=args.minutes), encoding="utf-8"
        )
    if args.json:
        _emit(
            {
                "minutes": args.minutes,
                "plan": blocks,
                "formulas": formula_payload(),
                "papers": [
                    {
                        "year": paper.year,
                        "questions": len(paper.questions),
                        "points": paper.points,
                    }
                    for paper in papers
                ],
                "html": str(args.html) if args.html else None,
                "markdown": str(args.markdown) if args.markdown else None,
            },
            True,
        )
        return 0
    print(f"PLAN DE BATAILLE — {args.minutes} MINUTES")
    for block in blocks:
        print(
            f"  [{block['start_minute']:>2}–{block['end_minute']:>2} min] "
            f"{block['title']} — {block['detail']}"
        )
    print()
    print("Commandes utiles :")
    print("  python nage.py vc formulas")
    print("  python nage.py vc paper list")
    print("  python nage.py vc paper show 2025")
    print("  python nage.py vc paper show 2025 --solutions")
    print("  python nage.py vc paper template 2025 --output answers.json")
    print("  python nage.py vc paper grade 2025 --answers answers.json")
    print()
    print("Sujets disponibles :", ", ".join(str(paper.year) for paper in papers))
    if args.html:
        print(f"HTML sheet written: {args.html}")
    if args.markdown:
        print(f"Markdown sheet written: {args.markdown}")
    return 0


def _radar(args, store: VcStore, content) -> int:
    from .dates import now_iso, today_iso

    day = args.today or today_iso()
    records = mastery_radar(
        content,
        store.load_reviews(),
        today=day,
        case_attempts=store.load_case_attempts(),
        exam_results=store.load_exam_history(),
        drill_attempts=store.load_drill_attempts(),
        paper_attempts=store.load_paper_attempts(),
        progress=store.load_progress(),
    )
    _emit(radar_payload(records, generated_at=now_iso()), args.json)
    return 0


def _coverage(args, store: VcStore, content) -> int:
    report = coverage_report(content)
    if args.json:
        _emit(report, True)
        return 0
    print(f"{'Topic':<7} {'Level':<8} {'Cards':>5} {'Drills':>6} {'Cases':>5} {'Papers':>6} {'Exams':>5}")
    for item in report:
        print(
            f"{item['topic_id']:<7} {item['level']:<8} {item['cards']:>5} "
            f"{item['drills']:>6} {item['cases']:>5} {item['papers']:>6} {item['exams']:>5}"
        )
    thin = [item["topic_id"] for item in report if item["level"] == "thin"]
    if thin:
        print(f"\nThin topics: {', '.join(thin)}")
    return 0


def _schedule(args, store: VcStore, content) -> int:
    from .dates import today_iso
    from .mastery import build_schedule

    day = args.today or today_iso()
    records = mastery_radar(
        content,
        store.load_reviews(),
        today=day,
        case_attempts=store.load_case_attempts(),
        exam_results=store.load_exam_history(),
        drill_attempts=store.load_drill_attempts(),
        paper_attempts=store.load_paper_attempts(),
        progress=store.load_progress(),
    )
    exam_date = args.exam_date or store.load_settings().get("exam_date")
    schedule = build_schedule(
        content, records, today=day, exam_date=exam_date,
        days=args.days, daily_minutes=args.daily_minutes,
    )
    _emit(schedule, args.json)
    return 0


def _plan(args, store: VcStore, content) -> int:
    from .dates import today_iso

    day = args.today or today_iso()
    records = mastery_radar(
        content,
        store.load_reviews(),
        today=day,
        case_attempts=store.load_case_attempts(),
        exam_results=store.load_exam_history(),
        drill_attempts=store.load_drill_attempts(),
        paper_attempts=store.load_paper_attempts(),
        progress=store.load_progress(),
    )
    exam_date = args.exam_date or store.load_settings().get("exam_date")
    plan = build_study_plan(
        content, records, minutes=args.minutes, today=day, exam_date=exam_date
    )
    _emit(plan.to_dict(), args.json)
    return 0


def _next(args, store: VcStore, content) -> int:
    from .dates import today_iso

    day = args.today or today_iso()
    records = mastery_radar(
        content,
        store.load_reviews(),
        today=day,
        case_attempts=store.load_case_attempts(),
        exam_results=store.load_exam_history(),
        drill_attempts=store.load_drill_attempts(),
        paper_attempts=store.load_paper_attempts(),
        progress=store.load_progress(),
    )
    exam_date = args.exam_date or store.load_settings().get("exam_date")
    plan = build_study_plan(
        content, records, minutes=args.minutes, today=day, exam_date=exam_date
    )
    activity = plan.activities[0] if plan.activities else None
    if activity is None:
        print("Rien à faire maintenant. Lancez `vc plan` pour plus de détails.")
        _emit({"activity": None, "plan": plan.to_dict()}, args.json)
        return 0
    if not args.json:
        print(f"{activity['kind']} — {activity['topic_id']} : {activity['reason']}")
    _emit({"activity": activity, "plan": plan.to_dict()}, args.json)
    return 0


def _export(args, store: VcStore, content) -> int:
    if getattr(args, "study_coach", False):
        from .study_coach_bridge import build_study_coach_payload, write_study_coach_payload

        if args.output:
            destination = write_study_coach_payload(store, args.output)
            _emit({"written": str(destination)}, args.json)
        else:
            _emit(build_study_coach_payload(store), args.json)
        return 0
    payload = {
        "settings": store.load_settings(),
        "progress": {k: v.to_dict() for k, v in store.load_progress().items()},
        "reviews": [e.to_dict() for e in store.load_reviews()],
        "drills": [d.to_dict() for d in store.load_drill_attempts()],
        "papers": [p.to_dict() for p in store.load_paper_attempts()],
        "cases": [c.to_dict() for c in store.load_case_attempts()],
    }
    if args.output:
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
        _emit({"written": str(args.output)}, args.json)
    else:
        _emit(payload, args.json)
    return 0


def _errors(args, store: VcStore, content) -> int:
    from .error_dashboard import error_dashboard

    dashboard = error_dashboard(
        content,
        reviews=store.load_reviews(),
        case_attempts=store.load_case_attempts(),
        drill_attempts=store.load_drill_attempts(),
        exam_results=store.load_exam_history(),
        paper_attempts=store.load_paper_attempts(),
    )
    _emit(dashboard, args.json)
    return 0


def _exam_date(args, store: VcStore) -> int:
    from datetime import datetime

    from .dates import parse_date

    settings = store.load_settings()
    if args.date is None:
        _emit(
            {
                "exam_date": settings["exam_date"],
                "exam_time": settings["exam_time"],
                "exam_duration_minutes": settings["exam_duration_minutes"],
                "source": "settings",
            },
            args.json,
        )
        return 0
    parse_date(args.date)
    exam_time = args.time or settings["exam_time"]
    try:
        datetime.strptime(exam_time, "%H:%M")
    except ValueError as error:
        raise InputError(f"heure attendue au format HH:MM : {exam_time!r}") from error
    duration = (
        args.duration if args.duration is not None else settings["exam_duration_minutes"]
    )
    if duration <= 0:
        raise InputError("Exam duration must be strictly positive.")
    settings.update(
        {
            "exam_date": args.date,
            "exam_time": exam_time,
            "exam_duration_minutes": duration,
        }
    )
    store.save_settings(settings)
    _emit(
        {
            "exam_date": settings["exam_date"],
            "exam_time": settings["exam_time"],
            "exam_duration_minutes": settings["exam_duration_minutes"],
            "saved": True,
        },
        args.json,
    )
    return 0


def _report(args, store: VcStore, content) -> int:
    from .dates import today_iso

    day = args.today or today_iso()
    report = build_progress_report(
        content,
        store.load_reviews(),
        today=day,
        days=args.days,
        output_dir=store.reports_dir,
        case_attempts=store.load_case_attempts(),
        exam_results=store.load_exam_history(),
        drill_attempts=store.load_drill_attempts(),
        paper_attempts=store.load_paper_attempts(),
        progress=store.load_progress(),
    )
    _emit(report.to_dict(), args.json)
    return 0


def _glossary(args, store: VcStore, content) -> int:
    from .glossary import search_glossary

    matches = search_glossary(content, args.query)
    payload = {
        "matches": [asdict(entry) for entry in matches],
        "notice": None if matches else "not documented",
    }
    _emit(payload, args.json)
    return 0


def _term_sheet(args, store: VcStore, content) -> int:
    from .glossary import decode_term_sheet

    try:
        text = args.file.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise InputError(f"File not found: {args.file}") from error
    except UnicodeDecodeError as error:
        raise InputError("The term sheet must be a UTF-8 text file.") from error
    _emit(decode_term_sheet(content, text), args.json)
    return 0


def run_vc(args) -> int:
    try:
        if getattr(args, "vc_action", None) is None:
            from types import SimpleNamespace

            print("NAGE VC — EDHEC revision, offline.")
            print("Quick start: 90-minute plan + formula sheet.")
            print("Tapez `python nage.py vc --help` pour toutes les commandes.")
            print()
            return _cram(
                SimpleNamespace(minutes=90, html=None, markdown=None, json=False),
                _store(args),
                load_content(),
            )
        store = _store(args)
        content = load_content().with_cards(store.load_deck())
        if args.vc_action == "review":
            return _review(args, store, content)
        if args.vc_action == "drill":
            return _drill(args, store, content)
        if args.vc_action == "case":
            return _case(args, store, content)
        if args.vc_action == "diagnostic":
            return _diagnostic(args, store, content)
        if args.vc_action == "exam":
            return _exam(args, store, content)
        if args.vc_action == "oral":
            return _oral(args, store, content)
        if args.vc_action == "notes":
            return _notes(args, store, content)
        if args.vc_action == "paper":
            return _paper(args, store, content)
        if args.vc_action == "cram":
            return _cram(args, store, content)
        if args.vc_action == "formulas":
            return _formulas(args, store, content)
        if args.vc_action == "radar":
            return _radar(args, store, content)
        if args.vc_action == "coverage":
            return _coverage(args, store, content)
        if args.vc_action == "plan":
            return _plan(args, store, content)
        if args.vc_action == "next":
            return _next(args, store, content)
        if args.vc_action == "predict":
            return _predict(args, store, content)
        if args.vc_action == "schedule":
            return _schedule(args, store, content)
        if args.vc_action == "exam-date":
            return _exam_date(args, store)
        if args.vc_action == "export":
            return _export(args, store, content)
        if args.vc_action == "errors":
            return _errors(args, store, content)
        if args.vc_action == "serve":
            return _serve(args, store, content)
        if args.vc_action == "report":
            return _report(args, store, content)
        if args.vc_action == "glossary":
            return _glossary(args, store, content)
        if args.vc_action == "term-sheet":
            return _term_sheet(args, store, content)
        if args.vc_action == "delete":
            store.delete_all(args.confirm)
            _emit({"deleted": True, "home": str(store.home)}, args.json)
            return 0
        if args.vc_action == "tutor":
            return _tutor(args, store, content)
        if args.vc_action == "master":
            return _master(args)
        raise InputError("Commande VC inconnue.")
    except ContentError as error:
        print(f"Contenu VC invalide : {error}", file=sys.stderr)
        return 4
    except StorageError as error:
        print(f"Stockage VC indisponible : {error}", file=sys.stderr)
        return 3
    except (VcError, ValueError, OSError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 2


def _serve(args, store: VcStore, content) -> int:
    from .server import run_server

    host = args.host
    port = args.port
    print(f"Serving offline VC hub on http://{host}:{port} (Ctrl+C to stop)")
    if getattr(args, "open", False):
        import webbrowser

        webbrowser.open(f"http://{host}:{port}/")
    try:
        run_server(store, host=host, port=port)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


def _tutor(args, store: VcStore, content) -> int:
    action = args.tutor_cmd
    topic_id = getattr(args, "topic", None)
    question = str(getattr(args, "question", None) or "").strip()
    if action == "oral":
        if topic_id:
            content.topic(topic_id)
        question = "Ask me one short oral-exam question grounded in my course. Wait for my answer before explaining."
        mode = "socratic"
    else:
        if not question:
            raise InputError("Provide --question for tutor explain or debug.")
        mode = "correct" if action == "debug" else "explain"
    from vc_tutor import VCTutor

    tutor = VCTutor(cloud=False, load_env=False, data_dir=store.home)
    result = tutor.tutor_chat(
        question, mode=mode, topic_id=topic_id,
        student_answer=getattr(args, "answer", None),
    )
    _emit(result, args.json)
    return 0


def _master(args) -> int:
    import subprocess

    script = Path(__file__).resolve().parents[2] / "vc_master.py"
    command = [sys.executable, str(script)]
    action = getattr(args, "master_cmd", None) or "status"
    if action == "status":
        command.append("status")
    elif action == "set-exam":
        command.extend(["set-exam", args.date])
        if args.time:
            command.append(args.time)
        if args.duration is not None:
            command.append(str(args.duration))
    elif action == "sprint":
        command.extend(["sprint", str(getattr(args, "hours", 3))])
    elif action in {"formulas", "terms", "cases", "revise"}:
        command.append(action)
    elif action == "simulate":
        command.extend(["simulate", str(getattr(args, "minutes", 60))])
    else:
        print(f"Commande master inconnue : {action}", file=sys.stderr)
        return 2
    try:
        completed = subprocess.run(command, check=False)
    except OSError as error:
        print(f"Erreur master : {error}", file=sys.stderr)
        return 2
    return completed.returncode
