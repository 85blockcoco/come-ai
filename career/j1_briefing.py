"""Briefing J-1 (SPEC-037) : la veille d'un entretien, un seul document local.

Agrège, pour une candidature suivie :

- la fiche entreprise sourcée (offre enregistrée, ``source_name`` + URL
  officielle uniquement si elle est http/https) ;
- les questions probables : SPEC-031 ``career.faq_mining`` quand la branche le
  porte, sinon repli local déterministe sur les champs de l'offre ;
- les worksheets STAR : SPEC-027 ``career.interview_sim`` quand des worksheets
  structurées sont présentes, sinon les séances du coach local avec complétude
  calculée sur les quatre volets STAR (situation/task/action/result) ;
- les blocages administratifs : SPEC-028 ``career.stage_admin_docs`` quand il
  est présent, seulement si c'est un stage à l'étranger ;
- les éléments du CV à relire (écarts du panneau de préparation).

100 % local et déterministe : aucune requête réseau, aucune clé, aucune donnée
réelle (fixtures synthétiques uniquement en test). Toute section vide ou
incomplète est publiée avec un marqueur « À COMPLÉTER » dans
``incomplete_sections`` : rien n'est jamais masqué.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

MARKER_PREFIX = "À COMPLÉTER"
STAR_THRESHOLD_DEFAULT = 0.8
MAX_COMPANY_FACTS = 20
MAX_QUESTIONS = 12
MAX_WORKSHEETS = 30
MAX_ADMIN_BLOCKERS = 20
MAX_CV_REREAD = 15
MAX_SESSION_LOOKUPS = 5
MAX_TEXT = 300
MAX_FACT_TEXT = 400

STAR_FIELDS: tuple[str, ...] = ("situation", "task", "action", "result")

_HTTP_URL = re.compile(r"^https?://[^\s\"'<>`]+$", re.IGNORECASE)

# Volets STAR détectés dans les réponses d'entretien (lexique fermé fr/en).
_STAR_PATTERNS: dict[str, re.Pattern[str]] = {
    "situation": re.compile(
        r"\b(quand|lorsque|pendant|durant|au d[ée]but|à l['’][ée]poque|dans le contexte|sur ce projet|when|during|at the time|in this context)\b",
        re.IGNORECASE,
    ),
    "task": re.compile(
        r"\b(mission|objectif|objectifs|tâche|tâches|il fallait|je devais|mon rôle|responsabilit|dans mon rôle|task|objective|goal|my role|my job)\b",
        re.IGNORECASE,
    ),
    "action": re.compile(
        r"(j['’]ai|nous avons|j['’]ai r[ée]alis|j['’]ai construit|j['’]ai analys|j['’]ai d[ée]velopp|j['’]ai mis en place|j['’]ai g[ée]r|j['’]ai utilis|j['’]ai pilot|j['’]ai orchestr"
        r"|I built|I led|I implemented|I designed|I developed|we delivered)",
        re.IGNORECASE,
    ),
    "result": re.compile(
        r"(\d+\s*%|\b(r[ée]sultat|r[ée]sultats|gain|gains|augment[ée]|r[ée]duit|am[ée]lior[ée]|obtenu|livr[ée]"
        r"|result|results|increased|reduced|improved|delivered|saved)\b)",
        re.IGNORECASE,
    ),
}


@dataclass
class BriefingDoc:
    """Contrat public SPEC-037 : le briefing complet en un seul objet."""

    application_id: str
    company_facts: list[str] = field(default_factory=list)
    top_questions: list[str] = field(default_factory=list)
    star_ready: list[str] = field(default_factory=list)
    admin_blockers: list[str] = field(default_factory=list)
    cv_section_reread: list[str] = field(default_factory=list)
    incomplete_sections: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Bornes et nettoyage
# ---------------------------------------------------------------------------

def _clean(value: Any, limit: int = MAX_TEXT) -> str:
    """Texte lisible, borné, sans contrôle de mise en page étranger."""
    if value is None or isinstance(value, bool):
        return ""
    text = value if isinstance(value, str) else str(value)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _bounded_texts(values: Iterable[Any] | None, cap: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in list(values or [])[: cap * 4]:
        text = _clean(value, MAX_FACT_TEXT)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= cap:
            break
    return out


def _bounded_threshold(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return STAR_THRESHOLD_DEFAULT
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        return STAR_THRESHOLD_DEFAULT
    return value


def _is_http_url(value: Any) -> bool:
    return isinstance(value, str) and bool(_HTTP_URL.match(value.strip()))


def _source_label(job: Mapping[str, Any]) -> str:
    name = _clean(job.get("source_name"), 80) or "offre enregistrée"
    url = job.get("official_url")
    if _is_http_url(url):
        return f"{name}, {url.strip()}"
    # URL non http(s) (javascript:, data:, relative…) : jamais publiée comme lien.
    return name


# ---------------------------------------------------------------------------
# Agrégateur pur
# ---------------------------------------------------------------------------

def _worksheet_label(worksheet: Mapping[str, Any]) -> str:
    for key in ("name", "title", "label", "question_id", "id"):
        label = _clean(worksheet.get(key), 160)
        if label:
            return label
    return "worksheet sans titre"


def _worksheet_completeness(worksheet: Mapping[str, Any]) -> float:
    """Complétude 0-1 : valeur explicite valide, sinon calcul sur les 4 volets."""
    raw = worksheet.get("completeness")
    if raw is not None and not isinstance(raw, bool):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = math.nan
        if math.isfinite(value) and 0.0 <= value <= 1.0:
            return value
    # Valeur absente, booléenne ou malformée (NaN, « 0.9x », -5, 42…) :
    # on recalcule sur les volets STAR renseignés, sinon 0 (jamais prêt).
    filled = sum(1 for name in STAR_FIELDS if _clean(worksheet.get(name)))
    return filled / len(STAR_FIELDS)


def star_dimensions(text: Any) -> tuple[str, ...]:
    """Volets STAR (situation/task/action/result) détectés dans un texte."""
    body = _clean(text, 20_000).casefold()
    if not body:
        return ()
    return tuple(name for name in STAR_FIELDS if _STAR_PATTERNS[name].search(body))


def build_j1_briefing(
    application_id: str,
    *,
    company_facts: Iterable[Any] | None = None,
    top_questions: Iterable[Any] | None = None,
    star_worksheets: Iterable[Any] | None = None,
    admin_blockers: Iterable[Any] | None = None,
    cv_section_reread: Iterable[Any] | None = None,
    cv_sections: Iterable[Any] | None = None,
    admin_applicable: bool = False,
    star_completeness_threshold: float = STAR_THRESHOLD_DEFAULT,
) -> BriefingDoc:
    """Construit le briefing ; toute lacune devient un marqueur « À COMPLÉTER ».

    ``cv_section_reread=None`` signale une analyse de couverture indisponible
    (marqueur explicite) ; une liste vide signale « rien à relire » (normal).
    ``cv_sections`` reste accepté comme alias rétrocompatible.
    ``admin_applicable=True`` avec aucune pièce bloquante devient un marqueur :
    un stage à l'étranger sans checklist n'est jamais présenté comme prêt.
    """
    threshold = _bounded_threshold(star_completeness_threshold)
    facts = _bounded_texts(company_facts, MAX_COMPANY_FACTS)
    questions = _bounded_texts(top_questions, MAX_QUESTIONS)
    blockers = _bounded_texts(admin_blockers, MAX_ADMIN_BLOCKERS)
    cv_source = cv_section_reread if cv_section_reread is not None else cv_sections
    cv_raw = list(cv_source) if cv_source is not None else None
    cv_entries = _bounded_texts(cv_raw, MAX_CV_REREAD) if cv_raw is not None else None

    worksheets = [w for w in (star_worksheets or []) if isinstance(w, Mapping)][:MAX_WORKSHEETS]

    incomplete: list[str] = []
    star_ready: list[str] = []
    if not worksheets:
        incomplete.append(f"{MARKER_PREFIX} : worksheets STAR (aucune préparation d'entretien enregistrée)")
    for worksheet in worksheets:
        label = _worksheet_label(worksheet)
        score = _worksheet_completeness(worksheet)
        if score >= threshold:
            star_ready.append(label)
        else:
            incomplete.append(f"{MARKER_PREFIX} : worksheet STAR « {label} » (complétude {score:.2f})")

    if not facts:
        incomplete.append(f"{MARKER_PREFIX} : fiche entreprise (aucune source disponible)")
    if not questions:
        incomplete.append(f"{MARKER_PREFIX} : questions probables (aucune source)")
    if admin_applicable and not blockers:
        incomplete.append(f"{MARKER_PREFIX} : checklist documents administratifs (SPEC-028)")
    if cv_entries is None:
        incomplete.append(f"{MARKER_PREFIX} : revue du CV (analyse de couverture indisponible)")

    return BriefingDoc(
        application_id=str(application_id or ""),
        company_facts=facts,
        top_questions=questions,
        star_ready=star_ready,
        admin_blockers=blockers,
        cv_section_reread=cv_entries or [],
        incomplete_sections=incomplete,
    )


def to_dict(doc: BriefingDoc) -> dict[str, Any]:
    return asdict(doc)


# ---------------------------------------------------------------------------
# Fiche entreprise sourcée
# ---------------------------------------------------------------------------

def company_facts_from_job(job: Mapping[str, Any] | None) -> list[str]:
    """Faits factuels de l'offre enregistrée, chacun avec sa source."""
    source = job if isinstance(job, Mapping) else {}
    if not source:
        return []
    label = _source_label(source)
    draft: list[str] = []

    company = _clean(source.get("company"), 120)
    title = _clean(source.get("title"), 160)
    contract = _clean(source.get("employment_type"), 80)
    if company and title:
        headline = f"{company} — {title}" + (f" ({contract})" if contract else "")
        draft.append(headline.strip())
    elif company or title:
        draft.append(company or title)

    city = _clean(source.get("city"), 80)
    country = _clean(source.get("country"), 80)
    place = " — ".join(part for part in (city, country) if part)
    if place:
        draft.append(f"Poste à {place}.")

    start = _clean(source.get("start_date"), 40)
    duration = source.get("duration_months")
    timing: list[str] = []
    if start:
        timing.append(f"démarrage {start}")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 0:
        timing.append(f"durée {int(duration)} mois")
    if timing:
        draft.append("Démarrage / durée : " + ", ".join(timing) + ".")

    deadline = _clean(source.get("deadline_date"), 40)
    if deadline:
        draft.append(f"Date limite de candidature : {deadline}.")

    if source.get("source_verified") is True:
        trust = _clean(source.get("official_source_trust_label"), 80)
        draft.append(f"Source officielle vérifiée{f' : {trust}' if trust else ''}.")

    return [f"{fact} (source : {label})" for fact in _bounded_texts(draft, MAX_COMPANY_FACTS)]


# ---------------------------------------------------------------------------
# Questions probables (SPEC-031, repli local)
# ---------------------------------------------------------------------------

def _local_questions(job: Mapping[str, Any]) -> list[str]:
    questions: list[str] = []
    company = _clean(job.get("company"), 120)
    title = _clean(job.get("title"), 160)
    if company and title:
        questions.append(f"Pourquoi {company} pour ce poste de {title} ?")
    requirements = job.get("requirements")
    first_line = ""
    if isinstance(requirements, str):
        first_line = next((line.strip() for line in requirements.splitlines() if line.strip()), "")
    first_line = _clean(first_line, 160)
    if first_line:
        questions.append(f"Comment répondez-vous à l'exigence « {first_line} » ?")
    if _clean(job.get("start_date"), 40) or isinstance(job.get("duration_months"), (int, float)):
        questions.append("Quelle est votre disponibilité exacte (démarrage, durée) ?")
    questions.append("Qu'apporteriez-vous durant les premières semaines ?")
    return _bounded_texts(questions, MAX_QUESTIONS)


def _discover_faq_provider() -> Callable[[Mapping[str, Any]], Iterable[str]] | None:
    """SPEC-031 : présent sur la branche d'intégration, sinon absent → repli."""
    try:
        from .faq_mining import expected_questions, mine_sector_faq
    except Exception:
        return None

    def provider(job: Mapping[str, Any]) -> Iterable[str]:
        offer = {
            "sector": _clean(job.get("job_family"), 80) or "general",
            "description": _clean(job.get("description_original"), 4_000),
            "requirements": _clean(job.get("requirements"), 4_000),
        }
        faqs = mine_sector_faq([offer])
        if not faqs:
            return []
        return expected_questions(faqs[0])

    return provider


def _top_questions(
    job: Mapping[str, Any], faq_provider: Callable[[Mapping[str, Any]], Iterable[str]] | None
) -> tuple[list[str], str]:
    provider = faq_provider if faq_provider is not None else _discover_faq_provider()
    if provider is not None:
        try:
            produced = provider(dict(job))
        except Exception:
            produced = None
        questions = _bounded_texts(produced, MAX_QUESTIONS)
        if questions:
            return questions, "spec-031"
    return _local_questions(job), "local"


def top_questions_from_job(
    job: Mapping[str, Any] | None,
    *,
    faq_provider: Callable[[Mapping[str, Any]], Iterable[str]] | None = None,
) -> list[str]:
    source = job if isinstance(job, Mapping) else {}
    return _top_questions(source, faq_provider)[0]


# ---------------------------------------------------------------------------
# Worksheets STAR (séances du coach / SPEC-027)
# ---------------------------------------------------------------------------

def star_worksheets_from_sessions(sessions: Iterable[Any] | None) -> list[dict[str, Any]]:
    """Worksheets STAR pour les séances liées à la candidature.

    Une séance qui porte déjà des worksheets structurées (SPEC-027 quand la
    branche le stocke) est utilisée telle quelle ; sinon la complétude est
    calculée de façon déterministe sur les volets STAR des réponses données.
    """
    worksheets: list[dict[str, Any]] = []
    for session in list(sessions or [])[:MAX_WORKSHEETS]:
        if not isinstance(session, Mapping):
            continue
        explicit = session.get("star_worksheets")
        if not isinstance(explicit, list) or not explicit:
            explicit = session.get("worksheets")
        if isinstance(explicit, list) and explicit:
            worksheets.extend(dict(item) for item in explicit if isinstance(item, Mapping))
            continue
        answers: list[str] = []
        turns = session.get("turns")
        if isinstance(turns, list):
            for turn in turns:
                if not isinstance(turn, Mapping):
                    continue
                answer = _clean(turn.get("answer"), 6_000)
                if answer:
                    answers.append(answer)
        dimensions = star_dimensions(" ".join(answers))
        mode = _clean(session.get("mode"), 60) or "entretien"
        date = _clean(session.get("completed_at") or session.get("started_at"), 40)
        label = f"Séance {mode}" + (f" du {date[:10]}" if date else "")
        worksheets.append(
            {
                "name": label,
                "completeness": round(len(dimensions) / len(STAR_FIELDS), 2),
                "dimensions": list(dimensions),
                "session_id": _clean(session.get("id"), 80),
                "source": "interview_session",
            }
        )
    return worksheets[:MAX_WORKSHEETS]


# ---------------------------------------------------------------------------
# Blocages administratifs (SPEC-028, stage à l'étranger)
# ---------------------------------------------------------------------------

def admin_applicability(job: Mapping[str, Any] | None) -> tuple[bool, str]:
    """(applicable, pays) : checklist exigée seulement pour un stage à l'étranger."""
    source = job if isinstance(job, Mapping) else {}
    country = _clean(source.get("country"), 80)
    abroad = country.casefold().strip() not in {"", "france", "fr"}
    contract_text = " ".join(
        _clean(source.get(key), 120) for key in ("employment_type", "job_family", "title")
    ).casefold()
    internship = any(
        token in contract_text for token in ("stage", "intern", "alternance", "apprentiss")
    )
    return abroad and internship, country


def _discover_admin_provider() -> Callable[[str], Any] | None:
    """SPEC-028 : présent sur sa branche d'origine, sinon absent → marqueur."""
    try:
        from .stage_admin_docs import build_admin_checklist
    except Exception:
        return None
    return build_admin_checklist


def _blockers_from_checklist(checklist: Any) -> list[str]:
    keys: Any = None
    item_rows: Any = None
    if isinstance(checklist, Mapping):
        keys = checklist.get("blocking_missing")
        item_rows = checklist.get("items")
    else:
        keys = getattr(checklist, "blocking_missing", None)
        item_rows = getattr(checklist, "items", None)
        if keys is None:
            to_dict_method = getattr(checklist, "to_dict", None)
            if callable(to_dict_method):
                try:
                    data = to_dict_method()
                except Exception:
                    data = None
                if isinstance(data, Mapping):
                    keys = data.get("blocking_missing")
                    item_rows = data.get("items")
    if not isinstance(keys, (list, tuple)):
        return []
    labels: dict[str, str] = {}
    if isinstance(item_rows, (list, tuple)):
        for row in item_rows:
            if isinstance(row, Mapping):
                key = _clean(row.get("key"), 80)
                label = _clean(row.get("label_fr") or row.get("label"), 120)
                if key and label:
                    labels[key] = label
    out: list[str] = []
    for raw_key in keys:
        key = _clean(raw_key, 80)
        if not key:
            continue
        label = labels.get(key)
        out.append(f"{label} ({key})" if label else key)
    return out


def admin_blockers_for_job(
    job: Mapping[str, Any] | None,
    *,
    checklist_provider: Callable[[str], Any] | None = None,
) -> tuple[list[str], bool]:
    """(pièces bloquantes, applicable). Sans fournisseur : applicable mais vide."""
    applicable, country = admin_applicability(job)
    if not applicable:
        return [], False
    provider = checklist_provider if checklist_provider is not None else _discover_admin_provider()
    if provider is None or not country:
        return [], True
    try:
        checklist = provider(country)
    except Exception:
        return [], True
    return _bounded_texts(_blockers_from_checklist(checklist), MAX_ADMIN_BLOCKERS), True


# ---------------------------------------------------------------------------
# Éléments du CV à relire
# ---------------------------------------------------------------------------

def cv_reread_from_prep(prep: Any) -> list[str] | None:
    """Écarts du panneau de préparation ; ``None`` = analyse indisponible."""
    if prep is None:
        return None
    gaps = prep.get("gaps") if isinstance(prep, Mapping) else None
    if not isinstance(gaps, list):
        return None
    entries: list[str] = []
    for gap in gaps[:MAX_CV_REREAD]:
        if not isinstance(gap, Mapping):
            continue
        requirement = _clean(gap.get("requirement"), 160)
        if not requirement:
            continue
        state = _clean(gap.get("current_state"), 60)
        adapted = _clean(gap.get("adapted_state"), MAX_TEXT)
        entry = f"CV — {requirement}" + (f" [{state}]" if state else "")
        if adapted:
            entry += f" : {adapted}"
        entries.append(entry)
    return _bounded_texts(entries, MAX_CV_REREAD)


# ---------------------------------------------------------------------------
# Assemblage pour une candidature (lecture seule, via CareerService)
# ---------------------------------------------------------------------------

def briefing_for_application(
    service: Any,
    application_id: str,
    *,
    faq_provider: Callable[[Mapping[str, Any]], Iterable[str]] | None = None,
    admin_provider: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Briefing complet d'une candidature suivie (aucune écriture, aucun réseau).

    Le service inconnu lève ``UserFacingError`` (réponse 400 gérée par
    ``create_app()``) ; les lectures secondaires (panneau de préparation,
    séances) sont non bloquantes : leur absence devient un marqueur explicite.
    """
    application = service.get_application(application_id)
    job_id = str(application.get("job_id") or "")
    job: dict[str, Any] = service.get_job(job_id) if job_id else {}

    prep: Any = None
    if job_id:
        try:
            prep = service.get_job_prep(job_id)
        except Exception:
            prep = None

    sessions: list[dict[str, Any]] = []
    try:
        sessions = [
            dict(session)
            for session in service.list_interview_sessions(limit=100)
            if isinstance(session, Mapping)
            and str(session.get("application_id") or "") == str(application_id)
        ]
    except Exception:
        sessions = []

    # L'historique listé n'embarque pas les réponses : on relit (au plus
    # MAX_SESSION_LOOKUPS, lecture seule) les séances concernées pour évaluer
    # les volets STAR. Un échec de lecture laisse la séance sans réponses —
    # la worksheet apparaît alors comme « À COMPLÉTER », jamais comme prête.
    detailed_sessions: list[dict[str, Any]] = []
    for summary in sessions[:MAX_SESSION_LOOKUPS]:
        session_id = str(summary.get("id") or "")
        enriched = dict(summary)
        if session_id:
            try:
                enriched = dict(service.get_interview_session(session_id))
            except Exception:
                enriched = dict(summary)
        detailed_sessions.append(enriched)

    company_facts = company_facts_from_job(job)
    questions, questions_source = _top_questions(job, faq_provider)
    worksheets = star_worksheets_from_sessions(detailed_sessions)
    blockers, admin_applicable = admin_blockers_for_job(job, checklist_provider=admin_provider)
    _, admin_country = admin_applicability(job)
    cv_section_reread = cv_reread_from_prep(prep)

    doc = build_j1_briefing(
        application_id,
        company_facts=company_facts,
        top_questions=questions,
        star_worksheets=worksheets,
        admin_blockers=blockers,
        cv_section_reread=cv_section_reread,
        admin_applicable=admin_applicable,
    )
    payload = to_dict(doc)
    payload["meta"] = {
        "job_id": job_id,
        "company": _clean(job.get("company"), 120),
        "title": _clean(job.get("title"), 160),
        "questions_source": questions_source,
        "star_threshold": STAR_THRESHOLD_DEFAULT,
        "star_worksheets_count": len(worksheets),
        "admin_applicable": admin_applicable,
        "admin_country": admin_country if admin_applicable else "",
        "sections_incomplete": len(doc.incomplete_sections),
        "automated_submission": False,
    }
    return payload


# ---------------------------------------------------------------------------
# Export Markdown (le même document, un seul lien)
# ---------------------------------------------------------------------------

_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Fiche entreprise (avec sources)", "company_facts"),
    ("Questions probables", "top_questions"),
    ("Worksheets STAR prêtes", "star_ready"),
    ("Blocs administratifs", "admin_blockers"),
    ("Éléments du CV à relire", "cv_section_reread"),
    ("Sections à compléter", "incomplete_sections"),
)


def render_markdown(payload: BriefingDoc | Mapping[str, Any]) -> str:
    data = asdict(payload) if isinstance(payload, BriefingDoc) else dict(payload)
    lines = [
        "# Briefing J-1 — veille d'entretien",
        "",
        f"Candidature : {_clean(data.get('application_id'), 80) or '—'}",
        "",
    ]
    for title, key in _SECTIONS:
        lines.append(f"## {title}")
        values = [str(value) for value in (data.get(key) or [])]
        if values:
            lines.extend(f"- {value}" for value in values)
        else:
            lines.append("- (aucun élément)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "BriefingDoc",
    "MARKER_PREFIX",
    "STAR_THRESHOLD_DEFAULT",
    "admin_applicability",
    "admin_blockers_for_job",
    "briefing_for_application",
    "build_j1_briefing",
    "company_facts_from_job",
    "cv_reread_from_prep",
    "render_markdown",
    "star_dimensions",
    "star_worksheets_from_sessions",
    "to_dict",
    "top_questions_from_job",
]
