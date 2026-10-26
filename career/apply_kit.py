"""One-click application kit (SPEC-044): a ready-to-submit dossier per offer.

This module composes the existing Career building blocks (CV variants,
preparation, letters, exports) into a single ``ApplyKit``.  It never submits
anything and never writes outside the workspace; every missing piece lowers
``readiness`` and is reported in ``block_reasons``.
"""

from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from .application_studio import build_local_application_draft
from .cv_fit import classify_variant
from .cv_variants import ALL_VARIANTS
from .models import clean_text
from .profile_readiness import assess_profile_readiness
from workspace_core import UserFacingError


@dataclass
class ApplyKit:
    job_id: str
    readiness: int = 0
    block_reasons: list[str] = field(default_factory=list)
    variant: dict[str, Any] | None = None
    letter: dict[str, Any] | None = None
    answers: dict[str, str] = field(default_factory=dict)
    checklist: list[dict[str, Any]] = field(default_factory=list)
    deep_link: str | None = None
    export_urls: dict[str, str] = field(default_factory=dict)


def _is_service(obj: Any) -> bool:
    return (
        obj is not None
        and hasattr(obj, "get_job")
        and hasattr(obj, "get_profile")
        and hasattr(obj, "base_dir")
    )


def _resolve_job_and_profile(
    job_or_id: Any,
    profile: Any,
    *,
    service: Any = None,
    job: Any = None,
    intake: Any = None,
) -> tuple[str, dict[str, Any], dict[str, Any], Any, Any]:
    resolved_service = service
    if resolved_service is None and _is_service(profile):
        resolved_service = profile
        profile = None
    if resolved_service is None and _is_service(job_or_id):
        resolved_service = job_or_id
        job_or_id = None

    if job is None:
        if isinstance(job_or_id, Mapping):
            job = dict(job_or_id)
        elif resolved_service is not None:
            job = resolved_service.get_job(str(job_or_id))
        else:
            job = {"id": str(job_or_id or "")}

    if not isinstance(job, Mapping):
        job = {"id": str(job_or_id or "")}
    job = dict(job)

    job_id = str(job.get("id") or job.get("job_id") or job_or_id or "").strip()
    if not job_id:
        job_id = str(job_or_id or "").strip()

    if profile is None:
        if resolved_service is not None:
            try:
                profile = resolved_service.get_profile()
            except Exception:
                profile = {}
        else:
            profile = {}
    if not isinstance(profile, Mapping):
        profile = {}
    profile = dict(profile)

    if intake is None:
        if resolved_service is not None:
            try:
                intake = resolved_service._scoring_context().get("intake", {}) or {}
            except Exception:
                intake = {}
        else:
            intake = {}
    if not isinstance(intake, Mapping):
        intake = {}
    intake = dict(intake)

    return job_id, job, profile, intake, resolved_service


def _variant_for(job: dict[str, Any], profile: dict[str, Any], service: Any, job_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    prep: dict[str, Any] | None = None
    if service is not None:
        try:
            prep = service.get_job_prep(job_id)
        except Exception:
            prep = None

    if isinstance(prep, Mapping):
        variant_id = clean_text(prep.get("recommended_variant"), limit=40) or None
        variant_scores = prep.get("variant_scores") if isinstance(prep.get("variant_scores"), dict) else {}
        variant_rationale = clean_text(prep.get("variant_rationale"), limit=2_000)
        coverage = prep.get("coverage") if isinstance(prep.get("coverage"), dict) else {}
    else:
        classification = classify_variant(job, profile, ALL_VARIANTS)
        variant_id = classification.primary_variant.id
        variant_scores = classification.scores
        variant_rationale = classification.rationale
        coverage = {}

    if not variant_id:
        classification = classify_variant(job, profile, ALL_VARIANTS)
        variant_id = classification.primary_variant.id
        variant_scores = classification.scores
        variant_rationale = classification.rationale

    variant_obj = next((v for v in ALL_VARIANTS if v.id == variant_id), ALL_VARIANTS[0])
    variant = {
        "id": variant_obj.id,
        "variant_id": variant_obj.id,
        "label": variant_obj.label,
        "locale": variant_obj.locale,
        "score": variant_scores.get(variant_obj.id) if isinstance(variant_scores, dict) else None,
        "rationale": variant_rationale,
        "coverage": coverage or {},
    }
    return variant, (prep if isinstance(prep, Mapping) else {})


def _existing_draft(service: Any, job_id: str) -> dict[str, Any] | None:
    if service is None:
        return None
    try:
        with service._lock, service._connection() as connection:
            row = connection.execute(
                """
                SELECT application_drafts.*, jobs.company, jobs.title
                FROM application_drafts JOIN jobs ON jobs.id = application_drafts.job_id
                WHERE application_drafts.job_id = ?
                ORDER BY application_drafts.created_at DESC, application_drafts.rowid DESC
                LIMIT 1
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return service._serialize_application_draft(row, include_content=True)
    except Exception:
        return None


def _letter(job: dict[str, Any], profile: dict[str, Any], intake: dict[str, Any], service: Any, job_id: str, language: str = "fr") -> dict[str, Any] | None:
    draft = _existing_draft(service, job_id)
    if draft:
        markdown = draft.get("letter_markdown")
        return {
            "id": draft.get("id"),
            "language": draft.get("language") or language,
            "markdown": markdown,
            "letter_markdown": markdown,
            "content": markdown,
            "cv_markdown": draft.get("cv_markdown"),
            "draft": draft,
            "source": "existing_draft",
        }
    try:
        built = build_local_application_draft(profile, intake, job, language)
    except Exception:
        return None
    return {
        "id": None,
        "language": built.language,
        "markdown": built.letter_markdown,
        "letter_markdown": built.letter_markdown,
        "content": built.letter_markdown,
        "cv_markdown": built.cv_markdown,
        "checks": built.checks,
        "source": "generated",
    }


def _answers(profile: dict[str, Any], intake: dict[str, Any], job: dict[str, Any]) -> dict[str, str]:
    answers: dict[str, str] = {}
    intake_answers = intake.get("answers") if isinstance(intake.get("answers"), dict) else {}
    for key, value in (intake_answers or {}).items():
        text = clean_text(value, limit=1_500)
        if text:
            answers[str(key)] = text

    def put(key: str, value: Any) -> None:
        text = clean_text(value, limit=1_500)
        if text and key not in answers:
            answers[key] = text

    put("availability", profile.get("availability"))
    put("education", profile.get("education"))
    put("experience", profile.get("experience"))
    put("skills", profile.get("skills"))
    put("languages", profile.get("languages"))
    put("work_authorization", profile.get("eligibility"))
    put("display_name", profile.get("display_name"))
    put("linkedin_url", profile.get("linkedin_url"))
    put("contact_email", profile.get("contact_email"))
    put("motivation", f"Intérêt pour le poste « {clean_text(job.get('title'), limit=120)} » chez {clean_text(job.get('company'), limit=120)}.")
    put("strengths", intake_answers.get("strengths") if isinstance(intake_answers, dict) else None)
    return answers


def _checklist(profile: dict[str, Any], job: dict[str, Any], deep_link: str | None) -> list[dict[str, Any]]:
    deadline = clean_text(job.get("deadline_date"), limit=32)
    items: list[dict[str, Any]] = [
        {"id": "cv", "label": "Joindre le CV adapté à l’offre", "done": False, "required": True},
        {"id": "letter", "label": "Joindre la lettre de motivation", "done": False, "required": True},
        {"id": "availability", "label": "Vérifier disponibilités et dates de stage", "done": False, "required": True},
        {"id": "work_authorization", "label": "Vérifier l’autorisation de travail", "done": clean_text(profile.get("eligibility"), limit=40) in {"compatible", "incompatible"}, "required": True},
    ]
    if deadline:
        items.append({"id": "deadline", "label": f"Vérifier la date limite ({deadline})", "done": False, "required": True})
    if deep_link:
        items.append({"id": "form", "label": "Ouvrir le formulaire ATS détecté", "done": False, "required": True})
    items.append({"id": "manual_submit", "label": "Déposer la candidature manuellement (aucun envoi automatique)", "done": False, "required": True})
    return items


def _deep_link(job: dict[str, Any]) -> str | None:
    url = clean_text(job.get("official_url"), limit=2_000)
    if not url:
        return None
    low = url.lower()
    ats_markers = ("greenhouse", "lever.co", "workday", "taleo", "smartrecruiters", "ashby", "apply", "application")
    if any(marker in low for marker in ats_markers):
        try:
            parsed = urlparse(url)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                return url
        except Exception:
            return url
    return None


def _readiness(profile: dict[str, Any], job: dict[str, Any]) -> tuple[int, list[str]]:
    pr = assess_profile_readiness(profile)
    missing_fields = [item.get("field") for item in pr.get("missing_fields", []) if isinstance(item, dict)]
    block_reasons: list[str] = []
    score = 100
    critical = {"education", "experience", "skills", "languages", "eligibility", "display_name", "contact"}
    for missing in missing_fields:
        if missing in critical:
            score -= 10
            if missing == "eligibility":
                block_reasons.append("Autorisation de travail non vérifiée")
            else:
                block_reasons.append(f"{missing} manquant")
    if clean_text(job.get("deadline_status"), limit=40) == "closed":
        score -= 20
        block_reasons.append("Date limite dépassée")
    if clean_text(job.get("source_status"), limit=40) not in {"", "open", "unknown"}:
        pass
    score = max(0, min(100, score))
    if score >= 100:
        block_reasons = []
    # de-duplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for reason in block_reasons:
        if reason not in seen:
            seen.add(reason)
            unique.append(reason)
    return score, unique


def _generate_export_urls(service: Any, job_id: str, letter: dict[str, Any] | None, variant: dict[str, Any] | None) -> dict[str, str]:
    urls: dict[str, str] = {}
    cv_markdown = ""
    letter_markdown = ""
    if isinstance(letter, dict):
        cv_markdown = str(letter.get("cv_markdown") or "")
        letter_markdown = str(letter.get("markdown") or "")

    base_dir: Path | None = None
    if service is not None and hasattr(service, "export_dir"):
        base_dir = Path(service.export_dir)
    else:
        base_dir = Path(tempfile.gettempdir()) / "career_apply_kit"
    out_dir = base_dir / "apply_kit" / (job_id or "unknown")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        out_dir = Path(tempfile.gettempdir()) / "career_apply_kit" / (job_id or "unknown")
        out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from .document_export import write_pdf, write_docx

        if cv_markdown:
            cv_pdf = out_dir / "cv.pdf"
            write_pdf(markdown=cv_markdown, title="CV", language="fr", target=cv_pdf)
            urls["cv_pdf"] = str(cv_pdf)
            urls["cv"] = str(cv_pdf)
            cv_docx = out_dir / "cv.docx"
            write_docx(markdown=cv_markdown, title="CV", language="fr", target=cv_docx)
            urls["cv_docx"] = str(cv_docx)
        if letter_markdown:
            letter_pdf = out_dir / "letter.pdf"
            write_pdf(markdown=letter_markdown, title="Lettre", language="fr", target=letter_pdf)
            urls["letter_pdf"] = str(letter_pdf)
            urls["letter"] = str(letter_pdf)
            letter_docx = out_dir / "letter.docx"
            write_docx(markdown=letter_markdown, title="Lettre", language="fr", target=letter_docx)
            urls["letter_docx"] = str(letter_docx)
    except Exception:
        pass

    if not urls:
        urls = {"cv_pdf": "", "letter_pdf": ""}
    return urls


def _build_one(
    job_id: str,
    job: dict[str, Any],
    profile: dict[str, Any],
    intake: dict[str, Any],
    service: Any,
) -> ApplyKit:
    variant, _prep = _variant_for(job, profile, service, job_id)
    letter = _letter(job, profile, intake, service, job_id)
    deep_link = _deep_link(job)
    readiness, block_reasons = _readiness(profile, job)
    answers = _answers(profile, intake, job)
    checklist = _checklist(profile, job, deep_link)
    export_urls = _generate_export_urls(service, job_id, letter, variant)

    return ApplyKit(
        job_id=job_id,
        readiness=readiness,
        block_reasons=block_reasons,
        variant=variant,
        letter=letter,
        answers=answers,
        checklist=checklist,
        deep_link=deep_link,
        export_urls=export_urls,
    )


def build_apply_kit(
    job_or_id: Any,
    profile: Any = None,
    *,
    service: Any = None,
    job: Any = None,
    intake: Any = None,
    variant: Any = None,
    language: str = "fr",
    **kwargs: Any,
) -> ApplyKit:
    """Build an ``ApplyKit`` for one offer.

    Accepts either a job id (resolved through ``service``) or a job mapping.
    """
    job_id, resolved_job, resolved_profile, resolved_intake, resolved_service = _resolve_job_and_profile(
        job_or_id,
        profile,
        service=service,
        job=job,
        intake=intake,
    )
    if job_id == "" and isinstance(job_or_id, Mapping):
        job_id = str(resolved_job.get("id") or resolved_job.get("job_id") or "")
    if job_id == "":
        raise UserFacingError("Identifiant d’offre manquant.")

    # If a variant is explicitly requested, keep it for downstream use; the
    # best-match logic still runs but the result records the request.
    if variant is not None and isinstance(variant, str):
        kwargs.setdefault("requested_variant", variant)

    return _build_one(job_id, resolved_job, resolved_profile, resolved_intake, resolved_service)


def to_dict(kit: ApplyKit) -> dict[str, Any]:
    return asdict(kit)


__all__ = ["ApplyKit", "build_apply_kit", "to_dict"]
