"""Deterministic, local queue for preparing several Career applications.

The sprint is an orchestration view over existing qualification and CV facts.
It does not fetch offers, generate new facts, create tracker rows, send a
message or submit an application.  Unknown evidence remains explicitly
unknown and must be reviewed by the person.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import re
from typing import Any

from .models import clean_text, normalized_text

MAX_SPRINT_ITEMS = 30
MAX_SPRINT_CANDIDATES = 150
MAX_CV_PRIORITIES = 12
MAX_STRENGTHS = 10

_GAP_THEMES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("anglais professionnel", ("english", "anglais", "fluent english")),
    ("autre langue requise", ("german", "allemand", "italian", "italien", "spanish", "espagnol")),
    ("niveau de diplôme", ("bachelor", "master", "degree", "diplome", "graduate", "graduation")),
    ("finance et marchés", ("financial", "financial market", "capital market", "finance", "investment banking", "m&a")),
    ("analyse quantitative", ("quantitative", "mathematics", "probability", "statistics", "mathematique", "statistique")),
    ("modélisation financière", ("financial model", "financial modelling", "financial modeling", "valuation", "valorisation")),
    ("bloomberg", ("bloomberg",)),
    ("Excel", ("excel", "vba")),
    ("Python et programmation", ("python", "programming", "coding", "sql")),
    ("communication", ("communication", "written", "verbal", "presentation")),
    ("travail en équipe", ("teamwork", "team player", "collaboration", "stakeholder")),
    ("autorisation de travail", ("work authorization", "right to work", "visa", "eligible to work")),
    ("disponibilité", ("availability", "available", "full-time opportunities", "start date")),
)

_SPEAKER_LANGUAGE = re.compile(
    r"\b(?P<language>italian|german|spanish|french|dutch|portuguese|arabic|mandarin|japanese|"
    r"italien|allemand|espagnol|fran[cç]ais|n[ée]erlandais|portugais|arabe|chinois|japonais)\s+speaker\b",
    re.I,
)
_LANGUAGE_ALIASES = {
    "italian": ("italian", "italien"), "italien": ("italian", "italien"),
    "german": ("german", "allemand"), "allemand": ("german", "allemand"),
    "spanish": ("spanish", "espagnol"), "espagnol": ("spanish", "espagnol"),
    "french": ("french", "francais"), "français": ("french", "francais"),
    "dutch": ("dutch", "neerlandais"), "néerlandais": ("dutch", "neerlandais"),
    "portuguese": ("portuguese", "portugais"), "portugais": ("portuguese", "portugais"),
    "arabic": ("arabic", "arabe"), "arabe": ("arabic", "arabe"),
    "mandarin": ("mandarin", "chinois"), "chinois": ("mandarin", "chinois"),
    "japanese": ("japanese", "japonais"), "japonais": ("japanese", "japonais"),
}


def _qualification_status(match: dict[str, Any]) -> str:
    stage_match = match.get("stage_match") if isinstance(match.get("stage_match"), dict) else {}
    qualification = match.get("qualification") if isinstance(match.get("qualification"), dict) else {}
    return clean_text(
        stage_match.get("qualification_status") or qualification.get("target_status"), limit=40
    ) or "to_verify"


def _score(match: dict[str, Any]) -> int:
    stage_match = match.get("stage_match") if isinstance(match.get("stage_match"), dict) else {}
    try:
        job = match.get("job") if isinstance(match.get("job"), dict) else {}
        scoring = job.get("scoring") if isinstance(job.get("scoring"), dict) else {}
        return max(0, min(100, int(stage_match.get("score") or scoring.get("score") or 0)))
    except (TypeError, ValueError):
        return 0


def _language(job: dict[str, Any], coverage: dict[str, Any]) -> str:
    return clean_text(
        coverage.get("target_language")
        or job.get("language")
        or job.get("language_code")
        or job.get("detected_language"),
        limit=40,
    ) or "à confirmer"


def _priority_keyword(action: dict[str, Any]) -> str:
    requirement = normalized_text(action.get("requirement"))
    return _theme_for_text(requirement)


def _theme_for_text(text: Any) -> str:
    normalized = normalized_text(text)
    if not normalized:
        return ""
    padded = f" {normalized} "
    for label, markers in _GAP_THEMES:
        if any(f" {normalized_text(marker)} " in padded for marker in markers):
            return label
    return ""


def build_application_sprint(
    matches: list[dict[str, Any]],
    preparations: dict[str, dict[str, Any]],
    applications: list[dict[str, Any]],
    *,
    limit: int = 12,
    profile: dict[str, Any] | None = None,
    criteria: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded preparation queue from already-local application facts."""
    bounded_limit = max(1, min(MAX_SPRINT_ITEMS, int(limit or 12)))
    profile = profile or {}
    criteria = criteria or {}
    profile_education = normalized_text(profile.get("education"))
    profile_languages = normalized_text(profile.get("languages"))
    selected_months = {
        month for month in (criteria.get("start_months") or []) if type(month) is int and 1 <= month <= 12
    }
    application_by_job = {
        clean_text(item.get("job_id"), limit=80): item
        for item in applications
        if clean_text(item.get("job_id"), limit=80)
    }
    ordered = sorted(
        matches,
        key=lambda item: (
            {"conforming": 0, "to_verify": 1, "non_conforming": 2}.get(
                _qualification_status(item), 1
            ),
            -_score(item),
            clean_text((item.get("job") or {}).get("company"), limit=240).casefold(),
            clean_text((item.get("job") or {}).get("title"), limit=300).casefold(),
        ),
    )

    queue: list[dict[str, Any]] = []
    gap_counts: Counter[str] = Counter()
    gap_offers: dict[str, set[str]] = defaultdict(set)
    gap_requirements: dict[str, str] = {}
    strength_counts: Counter[str] = Counter()
    missing_fact_offers: dict[str, set[str]] = defaultdict(set)
    excluded_non_conforming = 0

    for match in ordered:
        status = _qualification_status(match)
        if status == "non_conforming":
            excluded_non_conforming += 1
            continue
        job = match.get("job") if isinstance(match.get("job"), dict) else {}
        job_id = clean_text(job.get("id"), limit=80)
        if not job_id:
            continue
        prep = preparations.get(job_id) if isinstance(preparations.get(job_id), dict) else {}
        coverage = prep.get("cv_coverage") if isinstance(prep.get("cv_coverage"), dict) else {}
        unverified = prep.get("unverified_elements") if isinstance(prep.get("unverified_elements"), list) else []
        uncertainty = prep.get("uncertainty") if isinstance(prep.get("uncertainty"), list) else []
        missing_facts = (match.get("qualification") or {}).get("missing_fields") or []
        normalized_title = normalized_text(job.get("title"))
        candidate_warnings: list[str] = []
        if re.search(r"\bph\s*d\b|\bdoctoral\b", normalized_title) and not re.search(
            r"\bph\s*d\b|\bdoctoral\b|\bdoctorat\b", profile_education
        ):
            candidate_warnings.append("Le titre demande explicitement un profil PhD/doctoral, non trouvé dans la formation approuvée.")
        if re.search(r"\bmba\b", normalized_title) and "mba" not in profile_education:
            candidate_warnings.append("Le titre demande explicitement un MBA, non trouvé dans la formation approuvée.")
        speaker = _SPEAKER_LANGUAGE.search(clean_text(job.get("title"), limit=300))
        if speaker:
            aliases = _LANGUAGE_ALIASES.get(speaker.group("language").casefold(), ())
            if aliases and not any(normalized_text(alias) in profile_languages for alias in aliases):
                candidate_warnings.append(
                    f"Le titre demande {speaker.group('language')} ; cette langue n’est pas trouvée dans le profil approuvé."
                )
        if selected_months and re.search(r"\bsummer\b|\bete\b", normalized_title) and not selected_months.intersection({6, 7, 8}):
            candidate_warnings.append(
                "Le titre annonce une période Summer, probablement hors des mois sélectionnés ; le mois exact reste à confirmer."
            )
        blockers: list[str] = []
        if status == "to_verify":
            blockers.append("Des critères de l’offre restent à vérifier avant de décider.")
        blockers.extend(clean_text(value, limit=300) for value in uncertainty if clean_text(value, limit=300))
        if missing_facts:
            blockers.append("Informations manquantes dans l’offre : " + ", ".join(map(str, missing_facts[:6])))
        if unverified:
            blockers.append(f"{len(unverified)} exigence(s) ne sont pas encore étayées par ton profil.")

        if candidate_warnings:
            readiness = "candidate_to_verify"
        elif status == "to_verify" or missing_facts or uncertainty:
            readiness = "offer_to_verify"
        elif unverified:
            readiness = "profile_to_complete"
        else:
            readiness = "prepare_now"

        next_actions: list[str] = []
        if readiness == "offer_to_verify":
            next_actions.append("Relire l’offre officielle et confirmer les informations manquantes.")
        if unverified:
            next_actions.append("Vérifier les exigences non étayées et compléter le profil uniquement avec des preuves réelles.")
        next_actions.append("Adapter le CV et la lettre dans la langue de l’offre, puis les relire.")
        next_actions.append("Créer ou mettre à jour le suivi local après ton dépôt manuel.")

        application = application_by_job.get(job_id)
        tracking = None
        if application:
            tracking = {
                "application_id": clean_text(application.get("id"), limit=80),
                "stage": clean_text(application.get("stage"), limit=80) or "inconnu",
            }

        for action in prep.get("cv_action_plan") or []:
            if not isinstance(action, dict) or action.get("status") != "needs_evidence":
                continue
            keyword = _priority_keyword(action)
            if not keyword:
                continue
            gap_counts[keyword] += 1
            gap_offers[keyword].add(job_id)
            gap_requirements.setdefault(keyword, clean_text(action.get("requirement"), limit=300))
        for missing_fact in missing_facts:
            label = clean_text(missing_fact, limit=120)
            if label:
                missing_fact_offers[label].add(job_id)
        for element in prep.get("matched_elements") or []:
            if not isinstance(element, dict):
                continue
            theme = _theme_for_text(
                " ".join(
                    [
                        clean_text(element.get("requirement"), limit=300),
                        " ".join(str(value) for value in (element.get("matched_on") or [])),
                    ]
                )
            )
            if theme:
                strength_counts[theme] += 1

        queue.append(
            {
                "job_id": job_id,
                "company": clean_text(job.get("company"), limit=240) or "Entreprise à vérifier",
                "title": clean_text(job.get("title"), limit=300) or "Intitulé à vérifier",
                "location": ", ".join(
                    part for part in (
                        clean_text(job.get("city"), limit=160),
                        clean_text(job.get("country"), limit=120),
                    ) if part
                ) or "Localisation à vérifier",
                "official_url": clean_text(job.get("official_url"), limit=2_000),
                "language": _language(job, coverage),
                "qualification_status": status,
                "match_score": _score(match),
                "readiness": readiness,
                "coverage_percent": int(coverage.get("coverage_percent") or 0),
                "supported_requirements": int(coverage.get("supported") or 0),
                "requirements_to_verify": int(coverage.get("to_verify") or len(unverified)),
                "blockers": blockers[:8],
                "candidate_warnings": candidate_warnings,
                "next_actions": next_actions,
                "tracking": tracking,
                "submission_status": "manual_only_not_submitted",
            }
        )

    # Readiness comes before a merely high topical score: the user wants to
    # complete good applications quickly, not open twenty equally scored ads
    # whose dates, language and eligibility are all still unknown.
    queue.sort(
        key=lambda item: (
            {"prepare_now": 0, "profile_to_complete": 1, "offer_to_verify": 2}.get(item["readiness"], 3),
            len(item["blockers"]),
            item["requirements_to_verify"],
            -item["coverage_percent"],
            -item["match_score"],
            item["company"].casefold(),
            item["title"].casefold(),
        )
    )
    queue = queue[:bounded_limit]

    priorities = [
        {
            "keyword": keyword,
            "requirement": gap_requirements.get(keyword, keyword),
            "offer_count": len(gap_offers[keyword]),
            "occurrences": count,
            "status": "needs_evidence",
            "advice": (
                "N’ajoute pas ce mot-clé sans preuve. Si tu le maîtrises réellement, ajoute au profil puis au CV "
                "un exemple précis : contexte, action, outil utilisé et résultat vérifiable."
            ),
        }
        for keyword, count in sorted(
            gap_counts.items(), key=lambda item: (-len(gap_offers[item[0]]), -item[1], item[0])
        )[:MAX_CV_PRIORITIES]
    ]
    strengths = [
        {"keyword": keyword, "offer_count": count, "advice": "Rends cette preuve existante plus visible dans le CV adapté."}
        for keyword, count in strength_counts.most_common(MAX_STRENGTHS)
    ]
    readiness_counts = Counter(item["readiness"] for item in queue)
    return {
        "queue": queue,
        "stats": {
            "selected": len(queue),
            "prepare_now": readiness_counts["prepare_now"],
            "profile_to_complete": readiness_counts["profile_to_complete"],
            "offer_to_verify": readiness_counts["offer_to_verify"],
            "candidate_to_verify": readiness_counts["candidate_to_verify"],
            "already_tracked": sum(1 for item in queue if item["tracking"]),
            "excluded_non_conforming": excluded_non_conforming,
        },
        "cv_advice": {"priorities": priorities, "strengths": strengths},
        "verification_summary": [
            {"field": field, "offer_count": len(job_ids)}
            for field, job_ids in sorted(
                missing_fact_offers.items(), key=lambda item: (-len(item[1]), item[0].casefold())
            )
        ],
        "automatic_submission": False,
        "disclaimer": (
            "Cette file automatise la préparation locale, pas le dépôt. Les scores mesurent l’adéquation "
            "documentaire ; ils ne sont ni une probabilité d’embauche ni une note de recruteur. "
            "Aucun e-mail, message ou formulaire n’est envoyé automatiquement."
        ),
    }
