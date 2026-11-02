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
from .drills import drill_payload, grade_drill, random_drill
from .errors import ContentError, InputError, StorageError, VcError
from .exams import (
    build_exam,
    exam_payload,
    grade_exam,
    oral_questions,
    record_exam_result,
)
from .mastery import build_study_plan, mastery_radar, radar_payload
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


def _store(args) -> VcStore:
    home = getattr(args, "home", None)
    return VcStore(Path(home) if home else None)


def _load_session(store: VcStore, session_id: str):
    session = store.load_active_session()
    if session is None or session.session_id != session_id:
        raise InputError("Session active introuvable. Relancez `vc review`.")
    return session


def _add_common(parser) -> None:
    parser.add_argument("--json", action="store_true", help="Sortie JSON")
    parser.add_argument("--home", type=Path, default=None, help="Dossier VC local")


def build_vc_parser(parser) -> None:
    sub = parser.add_subparsers(dest="vc_action", required=True)

    review = sub.add_parser("review", help="Session de rappel actif")
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

    exam = sub.add_parser("exam", help="Examen blanc chronométré")
    exam_sub = exam.add_subparsers(dest="exam_action", required=True)
    exam_start = exam_sub.add_parser("start", help="Démarrer ou reprendre un examen")
    exam_start.add_argument("--questions", type=int, default=20)
    exam_start.add_argument("--minutes", type=int, default=30)
    exam_start.add_argument("--seed", type=int, default=0)
    exam_start.add_argument("--topic", action="append", default=[])
    exam_start.add_argument("--new", action="store_true", help="Remplacer l'examen actif")
    _add_common(exam_start)
    exam_submit = exam_sub.add_parser("submit", help="Soumettre les réponses")
    exam_submit.add_argument("exam_id")
    exam_submit.add_argument("--answers", required=True, type=Path)
    exam_submit.add_argument("--now", default=None, help="Horloge injectée (tests)")
    _add_common(exam_submit)

    oral = sub.add_parser("oral", help="Oral simulé avec relances")
    oral.add_argument("topic_id")
    oral.add_argument("--count", type=int, default=5)
    _add_common(oral)

    notes = sub.add_parser("notes", help="Importer et approuver des notes de cours")
    notes_sub = notes.add_subparsers(dest="notes_action", required=True)
    notes_ingest = notes_sub.add_parser("ingest", help="Proposer des cartes citées")
    notes_ingest.add_argument("file", type=Path)
    notes_ingest.add_argument("--topic", required=True)
    notes_ingest.add_argument(
        "--replace", action="store_true", help="Remplacer une source modifiée"
    )
    _add_common(notes_ingest)
    notes_list = notes_sub.add_parser("list", help="Lister sources et propositions")
    _add_common(notes_list)
    notes_approve = notes_sub.add_parser("approve", help="Ajouter une carte au deck")
    notes_approve.add_argument("proposal_id")
    notes_approve.add_argument(
        "--answer", default=None, help="Compléter une proposition « à compléter »"
    )
    _add_common(notes_approve)
    notes_reject = notes_sub.add_parser("reject", help="Rejeter une proposition")
    notes_reject.add_argument("proposal_id")
    _add_common(notes_reject)

    radar = sub.add_parser("radar", help="Radar de maîtrise")
    radar.add_argument("--today", default=None)
    _add_common(radar)

    plan = sub.add_parser("plan", help="Plan de révision borné")
    plan.add_argument("--minutes", type=int, default=60)
    plan.add_argument("--today", default=None)
    plan.add_argument("--exam-date", default=None)
    _add_common(plan)

    report = sub.add_parser("report", help="Rapport de progression")
    report.add_argument("--days", type=int, default=30)
    report.add_argument("--today", default=None)
    _add_common(report)

    glossary = sub.add_parser("glossary", help="Lexique VC FR/EN")
    glossary_sub = glossary.add_subparsers(dest="glossary_action", required=True)
    glossary_search = glossary_sub.add_parser("search", help="Chercher un terme")
    glossary_search.add_argument("query")
    _add_common(glossary_search)

    term_sheet = sub.add_parser("term-sheet", help="Décoder un term sheet")
    term_sub = term_sheet.add_subparsers(dest="term_sheet_action", required=True)
    term_decode = term_sub.add_parser("decode", help="Décoder un fichier texte")
    term_decode.add_argument("file", type=Path)
    _add_common(term_decode)

    delete = sub.add_parser("delete", help="Supprimer les données VC locales")
    delete.add_argument("--confirm", required=True)
    _add_common(delete)


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
            input("Entrée pour révéler… ")
        except (EOFError, KeyboardInterrupt):
            print("\nSession conservée. Reprenez avec `vc review`.")
            return 0
        print(f"Réponse : {card.answer}")
        if card.explanation:
            print(f"Pourquoi : {card.explanation}")
        while True:
            try:
                grade = input("Note (again/hard/good/easy) : ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nSession conservée. Reprenez avec `vc review`.")
                return 0
            if grade in ("again", "hard", "good", "easy"):
                break
            print("Note invalide. Utilisez again, hard, good ou easy.")
        duration = int(time.monotonic() - started)
        session, event = answer_session(
            store, content, session, grade, duration_seconds=duration
        )
        print(f"Carte replanifiée au {event.due_after}.")
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
        raise InputError(f"Fichier de réponses introuvable : {args.answers}") from error
    except json.JSONDecodeError as error:
        raise InputError(f"Fichier de réponses JSON invalide : {error.msg}") from error
    if not isinstance(answers, dict):
        raise InputError("Le fichier de réponses doit être un objet JSON question -> texte.")
    attempt = evaluate_case(content.case(args.case_id), answers)
    store.append_case_attempt(attempt)
    _emit(case_result_payload(attempt), args.json)
    return 0


def _read_answers(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise InputError(f"Fichier de réponses introuvable : {path}") from error
    except json.JSONDecodeError as error:
        raise InputError(f"Fichier de réponses JSON invalide : {error.msg}") from error
    if not isinstance(payload, dict):
        raise InputError("Le fichier de réponses doit être un objet JSON question -> réponse.")
    answers: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            raise InputError(f"Réponse invalide pour {key} : texte attendu.")
        answers[str(key)] = "" if value is None else str(value)
    return answers


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
            raise InputError("Examen actif introuvable. Relancez `vc exam start`.")
        active.answers.update(_read_answers(args.answers))
        result = grade_exam(active, content, now=args.now)
        record_exam_result(store, result)
        _emit(result, args.json)
        return 0

    raise InputError("Action d'examen inconnue.")


def _oral(args, store: VcStore, content) -> int:
    questions = oral_questions(content, args.topic_id, count=args.count)
    _emit(
        {
            "topic_id": args.topic_id,
            "count": len(questions),
            "questions": questions,
            "notice": "Oral simulé : les relances n'affichent jamais la réponse modèle.",
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
            raise InputError(f"Topic inconnu : {args.topic}") from error
        result = ingest_file(
            store, args.file, topic_id=args.topic, replace=args.replace
        )
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


def _radar(args, store: VcStore, content) -> int:
    from .dates import now_iso, today_iso

    day = args.today or today_iso()
    records = mastery_radar(
        content,
        store.load_reviews(),
        today=day,
        case_attempts=store.load_case_attempts(),
        exam_results=store.load_exam_history(),
        progress=store.load_progress(),
    )
    _emit(radar_payload(records, generated_at=now_iso()), args.json)
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
        progress=store.load_progress(),
    )
    exam_date = args.exam_date or store.load_settings().get("exam_date")
    plan = build_study_plan(
        content, records, minutes=args.minutes, today=day, exam_date=exam_date
    )
    _emit(plan.to_dict(), args.json)
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
        progress=store.load_progress(),
    )
    _emit(report.to_dict(), args.json)
    return 0


def _glossary(args, store: VcStore, content) -> int:
    from .glossary import search_glossary

    matches = search_glossary(content, args.query)
    payload = {
        "matches": [asdict(entry) for entry in matches],
        "notice": None if matches else "non documenté",
    }
    _emit(payload, args.json)
    return 0


def _term_sheet(args, store: VcStore, content) -> int:
    from .glossary import decode_term_sheet

    try:
        text = args.file.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise InputError(f"Fichier introuvable : {args.file}") from error
    except UnicodeDecodeError as error:
        raise InputError("Le term sheet doit être un fichier texte UTF-8.") from error
    _emit(decode_term_sheet(content, text), args.json)
    return 0


def run_vc(args) -> int:
    try:
        store = _store(args)
        content = load_content().with_cards(store.load_deck())
        if args.vc_action == "review":
            return _review(args, store, content)
        if args.vc_action == "drill":
            return _drill(args, store, content)
        if args.vc_action == "case":
            return _case(args, store, content)
        if args.vc_action == "exam":
            return _exam(args, store, content)
        if args.vc_action == "oral":
            return _oral(args, store, content)
        if args.vc_action == "notes":
            return _notes(args, store, content)
        if args.vc_action == "radar":
            return _radar(args, store, content)
        if args.vc_action == "plan":
            return _plan(args, store, content)
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
