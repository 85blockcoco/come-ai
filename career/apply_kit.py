"""One-call application kit assembly for a single Career offer.

This module composes the existing local Career building blocks (CV variant
classification, local letter generation, factual preparation, profile facts)
into a single ``ApplyKit`` value.  It never submits anything, never performs a
network call and never writes outside the workspace: document generation stays
in memory unless an explicit export is requested through the existing export
helpers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Mapping

from career.application_prep import prepare_application
from career.application_studio import build_kit_texts, build_local_application_draft
from career.cv_fit import classify_variant
from career.cv_variants import ALL_VARIANTS
from career.models import clean_text


@dataclass
class ApplyKit:
    """Ready-to-review application dossier for one offer (human action only)."""

    job_id: str
    readiness: int
    block_reasons: list[str]
    variant: dict[str, Any] | None
    letter: dict[str, Any] | None
    answers: dict[str, str]
    checklist: list[dict[str, Any]]
    deep_link: str | None
    export_urls: dict[str, str]


_REQUIRED_PROFILE_FIELDS: tuple[str, ...] = (
    "display_name",
    "education",
    "experience",
    "skills",
)


def _job_id_from(job_id: Any, job: Mapping | None) -> str:
    if isinstance(job_id, Mapping):
        candidate = job_id.get("id")
        if candidate is not None:
            return str(candidate)
    if job is not None and isinstance(job, Mapping):
        candidate = job.get("id")
        if candidate is not None:
            return str(candidate)
    return str(job_id or "").strip()


def _classify(job: Mapping[str, Any], profile: Mapping[str, Any]) -> tuple[Any, dict[str, Any] | None]:
    try:
        result = classify_variant(dict(job), dict(profile), ALL_VARIANTS)
    except Exception:  # pragma: no cover - defensive
        return None, None
    variant = result.primary_variant
    payload = asdict(variant)
    payload["scores"] = getattr(result, "scores", {}) or {}
    payload["rationale"] = getattr(result, "rationale", "") or ""
    return variant, payload


def _build_letter(profile: Mapping[str, Any], intake: Mapping[str, Any], job: Mapping[str, Any], language: str) -> dict[str, Any] | None:
    try:
        draft = build_local_application_draft(dict(profile), dict(intake), dict(job), language)
    except Exception:  # pragma: no cover - defensive
        return None
    return {
        "language": draft.language,
        "markdown": draft.letter_markdown,
        "letter_markdown": draft.letter_markdown,
        "cv_markdown": draft.cv_markdown,
        "checks": list(draft.checks),
    }


def _answers(profile: Mapping[str, Any], intake: Mapping[str, Any], job: Mapping[str, Any], language: str) -> dict[str, str]:
    answers: dict[str, str] = {}
    for field in ("display_name", "contact_email", "contact_phone", "linkedin_url", "education", "languages", "eligibility"):
        value = profile.get(field)
        if value is not None and str(value).strip():
            answers[field] = str(value).strip()
    intake_answers = intake.get("answers") if isinstance(intake.get("answers"), Mapping) else {}
    if isinstance(intake_answers, Mapping):
        for key, value in intake_answers.items():
            if value is not None and str(value).strip():
                answers[str(key)] = str(value).strip()
    try:
        kit_texts = build_kit_texts(dict(profile), dict(intake), dict(job), language)
    except Exception:  # pragma: no cover - defensive
        kit_texts = {}
    if isinstance(kit_texts, Mapping):
        for key in ("motivation_short", "availability"):
            value = kit_texts.get(key)
            if isinstance(value, str) and value.strip():
                answers[key] = value.strip()
    answers.setdefault("availability", str(profile.get("availability") or "").strip())
    return {key: value for key, value in answers.items() if str(value).strip()}


_DEADLINE_WARNING_DAYS = 14


def _deadline_note(deadline: str) -> tuple[str, bool]:
    """Human note for a deadline plus whether it needs immediate attention."""

    text = str(deadline or "").strip()
    if not text:
        return "", False
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return text, False
    days_left = (parsed - date.today()).days
    if days_left < 0:
        return f"{text} — échéance dépassée", True
    if days_left <= _DEADLINE_WARNING_DAYS:
        return f"{text} — échéance proche ({days_left} j)", True
    return text, False


def _readiness(
    profile: Mapping[str, Any],
    job: Mapping[str, Any],
    unverified: list[dict[str, Any]],
    *,
    variant: dict[str, Any] | None,
    letter: dict[str, Any] | None,
    deep_link: str | None,
) -> tuple[int, list[str]]:
    block_reasons: list[str] = []
    score = 100
    for field in _REQUIRED_PROFILE_FIELDS:
        if not str(profile.get(field) or "").strip():
            block_reasons.append(f"Profil incomplet : {field} manquant.")
            score -= 15
    eligibility = str(profile.get("eligibility") or "unknown").strip().lower()
    if eligibility in ("", "unknown"):
        block_reasons.append("Autorisation de travail non vérifiée.")
        score -= 25
    elif eligibility == "incompatible":
        block_reasons.append("Éligibilité incompatible avec l'offre.")
        score -= 50
    if unverified:
        count = len(unverified)
        block_reasons.append(f"{count} exigence(s) non étayée(s) dans le profil.")
        score -= min(30, 10 * count)
    if variant is None:
        block_reasons.append("Aucune variante CV n'a pu être sélectionnée.")
        score -= 20
    if letter is None:
        block_reasons.append("Lettre de motivation indisponible.")
        score -= 15
    # Offer-level sanity: a dossier is not ready without a place to apply.
    if not deep_link:
        block_reasons.append("Lien officiel de l'offre manquant.")
        score -= 10
    score = max(0, min(100, score))
    return score, block_reasons


def _checklist(
    profile: Mapping[str, Any],
    job: Mapping[str, Any],
    variant: dict[str, Any] | None,
    letter: dict[str, Any] | None,
    unverified: list[dict[str, Any]],
    export_urls: Mapping[str, str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    items.append({"id": "profile", "label": "Profil candidat complété", "done": all(str(profile.get(f) or "").strip() for f in _REQUIRED_PROFILE_FIELDS), "note": ""})
    items.append({"id": "eligibility", "label": "Autorisation de travail vérifiée", "done": str(profile.get("eligibility") or "").strip().lower() not in ("", "unknown"), "note": ""})
    items.append({"id": "variant", "label": "Variante CV sélectionnée", "done": variant is not None, "note": (variant or {}).get("label", "") if isinstance(variant, dict) else ""})
    items.append({"id": "letter", "label": "Lettre adaptée générée", "done": letter is not None, "note": ""})
    items.append({
        "id": "attach_cv",
        "label": "Joindre le CV au format PDF",
        "done": False,
        "note": str(export_urls.get("cv_pdf") or "Export à générer depuis l'application."),
    })
    items.append({
        "id": "attach_letter",
        "label": "Joindre la lettre au format PDF",
        "done": False,
        "note": str(export_urls.get("letter_pdf") or "Export à générer depuis l'application."),
    })
    items.append({"id": "official_url", "label": "Lien officiel de l'offre vérifié", "done": bool(str(job.get("official_url") or "").strip()), "note": str(job.get("official_url") or "").strip()})
    deadline = str(job.get("deadline_date") or "").strip()
    if deadline:
        note, urgent = _deadline_note(deadline)
        items.append({
            "id": "deadline",
            "label": "Date limite proche à vérifier" if urgent else "Date limite vérifiée",
            "done": False,
            "note": note,
            "urgent": urgent,
        })
    start_date = str(job.get("start_date") or "").strip()
    end_date = str(job.get("end_date") or "").strip()
    if start_date or end_date:
        items.append({
            "id": "dates",
            "label": "Dates du stage vérifiées",
            "done": False,
            "note": f"{start_date or '?'} → {end_date or '?'}",
        })
    for entry in unverified[:5]:
        req = clean_text(entry.get("requirement"), limit=200)
        items.append({"id": "evidence", "label": f"Preuve à apporter : {req}", "done": False, "note": clean_text(entry.get("note"), limit=200)})
    items.append({"id": "submit", "label": "Candidature déposée manuellement par le candidat", "done": False, "note": "Aucune soumission automatique."})
    return items


def build_apply_kit(
    job_id: Any,
    profile: Mapping[str, Any] | None = None,
    *,
    job: Mapping[str, Any] | None = None,
    intake: Mapping[str, Any] | None = None,
    service: Any = None,
    variant: str | None = None,
    language: str = "fr",
) -> ApplyKit:
    """Assemble an :class:`ApplyKit` for ``job_id``.

    ``profile`` may be omitted when ``service`` is provided; the job is fetched
    from ``service`` (or taken from ``job``) so callers can stay in memory.
    """

    profile = profile if isinstance(profile, Mapping) else {}
    intake = intake if isinstance(intake, Mapping) else {}
    resolved_job_id = _job_id_from(job_id, job)

    # Fetch job / profile / intake from a service when available.
    if job is None and service is not None:
        try:
            job = service.get_job(resolved_job_id)
        except Exception:
            job = None
    if not profile and service is not None:
        try:
            fetched = service.get_profile()
            if isinstance(fetched, Mapping):
                profile = fetched
        except Exception:
            profile = {}
    if not intake and service is not None:
        try:
            fetched = service.get_intake()
            if isinstance(fetched, Mapping):
                intake = fetched
        except Exception:
            intake = {}

    job = job if isinstance(job, Mapping) else {}
    if not job:
        # Without job facts we cannot build a dossier; surface a clear block.
        return ApplyKit(
            job_id=resolved_job_id,
            readiness=0,
            block_reasons=["Offre inconnue ou introuvable."],
            variant=None,
            letter=None,
            answers={},
            checklist=[{"id": "job", "label": "Offre introuvable", "done": False, "note": resolved_job_id}],
            deep_link=None,
            export_urls={},
        )

    normalized_language = str(language or "fr").strip().lower() or "fr"
    if normalized_language not in ("fr", "en", "it", "de"):
        normalized_language = "fr"

    # Variant classification.
    _variant_obj, variant_payload = _classify(job, profile)

    # Honour an explicit variant override when valid.
    if variant and isinstance(variant_payload, dict):
        allowed = {item.id for item in ALL_VARIANTS}
        if variant in allowed:
            variant_payload["id"] = variant
            # keep label in sync if possible
            for item in ALL_VARIANTS:
                if item.id == variant:
                    variant_payload["label"] = item.label
                    variant_payload["locale"] = item.locale
                    break

    # Local letter generation (in memory, no writes).
    letter_payload = _build_letter(profile, intake, job, normalized_language)

    # Preparation fact-check.
    try:
        prep = prepare_application(dict(profile), dict(intake), dict(job))
    except Exception:  # pragma: no cover - defensive
        prep = {}
    unverified = prep.get("unverified_elements", []) if isinstance(prep, Mapping) else []
    if not isinstance(unverified, list):
        unverified = []

    # Export urls: prefer a persisted draft when a service is available.
    export_urls: dict[str, str] = {}
    draft_id: str | None = None
    if service is not None:
        try:
            kit_result = service.create_application_kit(resolved_job_id, normalized_language, variant or (variant_payload or {}).get("id") or "m_a")
            if isinstance(kit_result, Mapping):
                draft = kit_result.get("draft")
                if isinstance(draft, Mapping):
                    draft_id = str(draft.get("id") or "").strip() or None
        except Exception:
            draft_id = None
    if draft_id:
        base = f"/api/career/application-drafts/{draft_id}/download"
        export_urls = {
            "cv_pdf": f"{base}/cv/pdf",
            "letter_pdf": f"{base}/letter/pdf",
            "cv_docx": f"{base}/cv/docx",
            "letter_docx": f"{base}/letter/docx",
        }

    deep_link = str(job.get("official_url") or "").strip() or None
    # Some connectors store an explicit apply URL.
    for key in ("apply_url", "application_url", "form_url", "ats_url"):
        value = job.get(key)
        if isinstance(value, str) and value.strip():
            deep_link = value.strip()
            break

    readiness, block_reasons = _readiness(
        profile,
        job,
        unverified,
        variant=variant_payload,
        letter=letter_payload,
        deep_link=deep_link,
    )
    checklist = _checklist(
        profile,
        job,
        variant_payload,
        letter_payload,
        unverified,
        export_urls,
    )
    answers = _answers(profile, intake, job, normalized_language)

    return ApplyKit(
        job_id=resolved_job_id,
        readiness=readiness,
        block_reasons=block_reasons,
        variant=variant_payload,
        letter=letter_payload,
        answers=answers,
        checklist=checklist,
        deep_link=deep_link,
        export_urls=export_urls,
    )
