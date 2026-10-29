"""One-call application kit assembly for a single Career offer.

This module composes the existing local Career building blocks (CV variant
classification, local letter generation, factual preparation, profile facts)
into a single ``ApplyKit`` value.  It never submits anything, never performs a
network call and never writes outside the workspace: document generation stays
in memory unless an explicit export is requested through the existing export
helpers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field as dataclass_field
from typing import Any, Mapping

from career.application_prep import prepare_application
from career.ats_guide import human_apply_guide
from career.application_studio import build_kit_texts, build_local_application_draft, scan_kit_placeholders
from career.cv_fit import classify_variant
from career.cv_variants import ALL_VARIANTS
from career.models import clean_text, deadline_state
from workspace_core import UserFacingError


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
    application: dict[str, Any] | None = None
    draft_id: str | None = None
    language: str = "fr"
    fact_checks: dict[str, Any] = dataclass_field(default_factory=dict)
    review_token: str | None = None
    ats_guide: dict[str, Any] | None = None
    # Step 2 of the one-click kit: the dossier is generated, then audited before
    # any export.  ``None`` only when no generated text exists to audit.
    quality_audit: dict[str, Any] | None = None


_REQUIRED_PROFILE_FIELDS: tuple[str, ...] = (
    "display_name",
    "education",
    "experience",
    "skills",
)


def _deadline_status(job: Mapping[str, Any]) -> str:
    raw = clean_text(job.get("deadline_date"), limit=32)
    if not raw:
        return "unknown"
    try:
        status = deadline_state(raw, "open")
    except UserFacingError:
        return "unknown"
    return "passed" if status == "closed" else "upcoming"


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


def _readiness(
    profile: Mapping[str, Any],
    job: Mapping[str, Any],
    unverified: list[dict[str, Any]],
    *,
    variant: dict[str, Any] | None,
    letter: dict[str, Any] | None,
    exports_ready: bool | None,
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
        block_reasons.append("Aucune variante de CV n'a pu être déterminée.")
        score -= 15
    if letter is None:
        block_reasons.append("Le brouillon de lettre locale n'a pas pu être généré.")
        score -= 15

    # A known offer is not automatically a suitable or verified offer. Reuse
    # the user's current Stage Hunter qualification and the canonical source
    # trust result supplied by CareerService; unknown stays a blocker.
    qualification = job.get("apply_qualification")
    if not isinstance(qualification, Mapping):
        qualification = job.get("qualification_facts")
    qualification = qualification if isinstance(qualification, Mapping) else {}
    qualification_status = clean_text(qualification.get("target_status"), limit=40) or "to_verify"
    if qualification_status != "conforming":
        reason = (
            "L'offre ne respecte pas les critères enregistrés."
            if qualification_status == "non_conforming"
            else "La qualification de l'offre reste à vérifier."
        )
        block_reasons.append(reason)
        score -= 35

    trust = job.get("official_source_trust")
    trust = trust if isinstance(trust, Mapping) else {}
    source_verified = bool(job.get("source_verified")) and trust.get("status") == "verified"
    if not source_verified:
        block_reasons.append("La source officielle de l'offre n'est pas vérifiée.")
        score -= 25

    source_status = clean_text(job.get("source_status"), limit=40).lower()
    if source_status == "closed":
        block_reasons.append("L'offre est indiquée comme clôturée.")
        score -= 25
    elif source_status != "open":
        block_reasons.append("La disponibilité de l'offre reste à vérifier.")
        score -= 10

    deadline_status = _deadline_status(job)
    if deadline_status == "passed":
        block_reasons.append("La date limite de l'offre est dépassée.")
        score -= 25
    elif deadline_status == "unknown":
        block_reasons.append("La date limite de l'offre reste à vérifier.")
        score -= 5
    if exports_ready is False:
        block_reasons.append("Les fichiers d'export du dossier ne sont pas disponibles.")
        score -= 10
    score = max(0, min(100, score))
    return score, block_reasons


def _quality_audit(
    profile: Mapping[str, Any],
    intake: Mapping[str, Any],
    job: Mapping[str, Any],
    letter: Mapping[str, Any] | None,
    prepped: Mapping[str, Any],
    service: Any = None,
) -> dict[str, Any] | None:
    """Run the deterministic dossier audit on the generated texts.

    The audit is the second step of the one-click kit: the person sees the
    quality report *before* choosing to export.  It never rewrites the draft
    and never calls a provider.
    """

    if not isinstance(letter, Mapping):
        return None
    cv_markdown = str(letter.get("cv_markdown") or "").strip()
    letter_markdown = str(letter.get("letter_markdown") or letter.get("markdown") or "").strip()
    if not cv_markdown and not letter_markdown:
        return None
    try:
        from career.dossier_quality import audit_dossier
    except Exception:  # pragma: no cover - defensive
        return None

    intake_answers = intake.get("answers") if isinstance(intake.get("answers"), Mapping) else {}
    extra_facts: list[dict[str, Any]] = []
    for question, answer in intake_answers.items():
        value = str(answer or "").strip()
        if not value:
            continue
        extra_facts.append(
            {
                "fact_id": f"intake_{len(extra_facts):04d}",
                "category": "answer",
                "value": value,
                "quote": f"{question} : {value}",
                "level": "declared",
                "source": "intake",
                "topic": str(question),
            }
        )
    requirements = prepped.get("requirements") if isinstance(prepped, Mapping) else []
    if not isinstance(requirements, list):
        requirements = []
    context = {
        "entities": [
            str(job.get(key)).strip()
            for key in ("company", "title", "city", "country", "source_name")
            if str(job.get(key) or "").strip()
        ],
        "terms": [
            str(job.get(key)).strip()
            for key in ("requirements", "description_original", "description", "missions")
            if str(job.get(key) or "").strip()
        ],
        "numbers": [
            str(job.get(key)).strip()
            for key in ("deadline_date", "start_date", "end_date", "duration_months")
            if str(job.get(key) or "").strip()
        ],
    }
    try:
        report = audit_dossier(
            cv=cv_markdown,
            letter=letter_markdown,
            profile=profile,
            extra_facts=extra_facts,
            requirements=requirements,
            recurring_answers=intake_answers,
            context=context,
            evidence_service=service,
        )
    except Exception:  # pragma: no cover - defensive
        return None
    return report.to_dict()


def _checklist(
    profile: Mapping[str, Any],
    job: Mapping[str, Any],
    variant: dict[str, Any] | None,
    letter: dict[str, Any] | None,
    unverified: list[dict[str, Any]],
    *,
    exports_ready: bool | None,
    quality_audit: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    items.append(
        {
            "id": "profile",
            "label": "Profil candidat complété",
            "done": all(str(profile.get(f) or "").strip() for f in _REQUIRED_PROFILE_FIELDS),
            "note": "",
        }
    )
    items.append(
        {
            "id": "eligibility",
            "label": "Autorisation de travail vérifiée",
            "done": str(profile.get("eligibility") or "").strip().lower() == "compatible",
            "note": "",
        }
    )
    items.append(
        {
            "id": "variant",
            "label": "Variante CV sélectionnée",
            "done": variant is not None,
            "note": (variant or {}).get("label", "") if isinstance(variant, dict) else "",
        }
    )
    items.append({"id": "letter", "label": "Lettre adaptée générée", "done": letter is not None, "note": ""})
    if isinstance(quality_audit, Mapping):
        score = quality_audit.get("score")
        verdict = str(quality_audit.get("verdict") or "")
        export_allowed = bool(quality_audit.get("export_allowed"))
        items.append(
            {
                "id": "quality_audit",
                "label": "Étape 2 — audit qualité du dossier avant export",
                "done": export_allowed,
                "note": (
                    f"Score {score}/100 — {quality_audit.get('verdict_label') or verdict}. "
                    + ("Audit validé, relis puis exporte." if export_allowed else "Corrige les signaux avant d'exporter.")
                ),
            }
        )
    else:
        items.append(
            {
                "id": "quality_audit",
                "label": "Étape 2 — audit qualité du dossier avant export",
                "done": False,
                "note": "Audit indisponible : aucun texte généré à contrôler.",
            }
        )
    trust = job.get("official_source_trust")
    trust = trust if isinstance(trust, Mapping) else {}
    source_verified = bool(job.get("source_verified")) and trust.get("status") == "verified"
    items.append(
        {
            "id": "official_url",
            "label": "Lien officiel de l'offre vérifié",
            "done": source_verified,
            "note": str(job.get("official_url") or "").strip() if source_verified else "À vérifier auprès de la source officielle.",
        }
    )
    qualification = job.get("apply_qualification")
    if not isinstance(qualification, Mapping):
        qualification = job.get("qualification_facts")
    qualification = qualification if isinstance(qualification, Mapping) else {}
    qualification_status = clean_text(qualification.get("target_status"), limit=40) or "to_verify"
    items.append(
        {
            "id": "qualification",
            "label": "Contrat, dates et durée conformes aux critères",
            "done": qualification_status == "conforming",
            "note": "; ".join(clean_text(value, limit=200) for value in qualification.get("reasons", []) if clean_text(value, limit=200))
            or ("À vérifier." if qualification_status != "conforming" else ""),
        }
    )
    deadline = str(job.get("deadline_date") or "").strip()
    if deadline:
        items.append(
            {
                "id": "deadline",
                "label": "Date limite vérifiée",
                "done": source_verified and _deadline_status(job) == "upcoming",
                "note": deadline,
            }
        )
    else:
        items.append(
            {"id": "deadline", "label": "Date limite vérifiée", "done": False, "note": "Aucune date limite fiable n'est enregistrée."}
        )
    if exports_ready is not None:
        items.append(
            {
                "id": "exports",
                "label": "Exports CV et lettre disponibles",
                "done": exports_ready,
                "note": "" if exports_ready else "Préparation des exports à vérifier.",
            }
        )
    for entry in unverified[:5]:
        req = clean_text(entry.get("requirement"), limit=200)
        items.append(
            {"id": "evidence", "label": f"Preuve à apporter : {req}", "done": False, "note": clean_text(entry.get("note"), limit=200)}
        )
    items.append(
        {
            "id": "submit",
            "label": "Candidature déposée manuellement par le candidat",
            "done": False,
            "note": "Aucune soumission automatique.",
        }
    )
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
    allowed_variants = {item.id for item in ALL_VARIANTS}
    if variant is not None and variant not in allowed_variants:
        raise ValueError("Variante CV inconnue.")

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
                    variant_payload["rationale"] = "Variante choisie explicitement par la personne."
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
    application_payload: dict[str, Any] | None = None
    fact_checks: dict[str, Any] = {}
    review_token: str | None = None
    kit_result: Mapping[str, Any] | None = None
    if service is not None:
        try:
            kit_result = service.create_application_kit(
                resolved_job_id, normalized_language, variant or (variant_payload or {}).get("id") or "m_a"
            )
            if isinstance(kit_result, Mapping):
                review_token = str(kit_result.get("review_token") or "") or None
                application = kit_result.get("application")
                if isinstance(application, Mapping):
                    application_payload = dict(application)
                kit_checks = kit_result.get("fact_checks")
                if isinstance(kit_checks, Mapping):
                    fact_checks = dict(kit_checks)
                draft = kit_result.get("draft")
                if isinstance(draft, Mapping):
                    draft_id = str(draft.get("id") or "").strip() or None
                    draft_letter = str(draft.get("letter_markdown") or "")
                    if draft_id and draft_letter.strip():
                        letter_payload = {
                            "language": str(draft.get("language") or normalized_language),
                            "markdown": draft_letter,
                            "letter_markdown": draft_letter,
                            "cv_markdown": str(draft.get("cv_markdown") or ""),
                            "checks": list(draft.get("checks") or []),
                        }
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

    guide_payload = None
    try:
        guide = human_apply_guide(dict(job))
        guide_payload = guide.to_dict()
        deep_link = guide.apply_url or None
    except UserFacingError as error:
        deep_link = None
        fact_checks["destination_error"] = str(error)

    exports_ready = bool(export_urls.get("cv_pdf") and export_urls.get("letter_pdf")) if service is not None else None
    readiness, block_reasons = _readiness(
        profile,
        job,
        unverified,
        variant=variant_payload,
        letter=letter_payload,
        exports_ready=exports_ready,
    )
    document_placeholders = scan_kit_placeholders(
        letter_payload or {}, fields=("cv_markdown", "letter_markdown")
    )
    fact_checks["document_placeholders"] = document_placeholders
    if document_placeholders:
        readiness = max(0, readiness - 20)
        block_reasons.append("Les documents CV/lettre contiennent des éléments à compléter avant le dépôt.")
    if fact_checks.get("destination_error"):
        readiness = max(0, readiness - 25)
        block_reasons.append(str(fact_checks["destination_error"]))
    answers = _answers(profile, intake, job, normalized_language)
    quality_audit = _quality_audit(profile, intake, job, letter_payload, prep, service)
    checklist = _checklist(
        profile,
        job,
        variant_payload,
        letter_payload,
        unverified,
        exports_ready=exports_ready,
        quality_audit=quality_audit,
    )
    checklist.insert(-1, {
        "id": "documents_complete",
        "label": "CV et lettre sans éléments à compléter",
        "done": not document_placeholders,
        "note": ", ".join(document_placeholders),
    })

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
        application=application_payload,
        draft_id=draft_id,
        language=str((letter_payload or {}).get("language") or normalized_language),
        fact_checks=fact_checks,
        review_token=review_token,
        ats_guide=guide_payload,
        quality_audit=quality_audit,
    )
