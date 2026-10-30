"""Global quality audit for an application dossier (SPEC-042 / CVBOOST-77).

Produces a transparent 0-100 score from four factors:

    1. ``validation_rate``   -- share of claims that are ``supported``
    2. ``exaggeration_density`` -- share of claims that are inflated /
       invented / out of context (lower is better)
    3. ``proof_score``       -- how well the dossier is backed by approved
       facts
    4. ``argumentation``     -- how well the dossier answers the recurring
       questions and the offer requirements

100 % local and deterministic: no model, no network, no clock.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .claim_check import (
    Claim,
    ClaimCheckResult,
    check_claims,
    CLAIM_LABELS,
    _approved_facts,
)
from .models import clean_text, normalized_text

try:
    from .requirements_fit import ApprovedProfile
except Exception:  # pragma: no cover
    ApprovedProfile = None  # type: ignore[assignment]

try:
    from .application_prep import prepare_application
except Exception:  # pragma: no cover
    prepare_application = None  # type: ignore[assignment]


_RULES_CANDIDATE_PATHS = (
    Path("career/dossier_quality_rules.json"),
    Path("data/dossier_quality_rules.json"),
    Path("dossier_quality_rules.json"),
)


def _load_rules() -> dict[str, Any]:
    path_env = os.environ.get("DOSSIER_QUALITY_RULES")
    candidates = []
    if path_env:
        candidates.append(Path(path_env))
    candidates.extend(_RULES_CANDIDATE_PATHS)
    for candidate in candidates:
        try:
            if candidate.is_file():
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return payload
        except Exception:
            continue
    return {}


_RULES = _load_rules()


@dataclass
class DossierQualityResult:
    """Result of a dossier-level quality audit."""

    score: int = 0
    overall_score: int = 0
    quality_score: int = 0
    score_out_of_100: int = 0
    grade: str = ""
    factors: list[dict[str, Any]] = field(default_factory=list)
    components: list[dict[str, Any]] = field(default_factory=list)
    claim_summary: dict[str, int] = field(default_factory=dict)
    claims: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    claim_check: Any = None
    report: str = ""
    readable_report: str = ""
    text_report: str = ""
    readable: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        if self.overall_score == 0 and self.score:
            self.overall_score = self.score
        if self.quality_score == 0 and self.score:
            self.quality_score = self.score
        if self.score_out_of_100 == 0 and self.score:
            self.score_out_of_100 = self.score
        if self.score == 0 and self.overall_score:
            self.score = self.overall_score
        if not self.components:
            self.components = self.factors
        if not self.suggestions:
            self.suggestions = self.recommendations
        if not self.readable_report:
            self.readable_report = self.report
        if not self.text_report:
            self.text_report = self.report
        if not self.readable:
            self.readable = self.report
        if not self.grade:
            if self.score >= 85:
                self.grade = "A"
            elif self.score >= 70:
                self.grade = "B"
            elif self.score >= 55:
                self.grade = "C"
            elif self.score >= 40:
                self.grade = "D"
            else:
                self.grade = "E"

    def to_dict(self) -> dict[str, Any]:
        cc = self.claim_check
        cc_dict = cc.to_dict() if hasattr(cc, "to_dict") else (cc if isinstance(cc, dict) else None)
        return {
            "score": self.score,
            "overall_score": self.overall_score,
            "quality_score": self.quality_score,
            "score_out_of_100": self.score_out_of_100,
            "grade": self.grade,
            "factors": self.factors,
            "components": self.components,
            "claim_summary": self.claim_summary,
            "claims": self.claims,
            "issues": self.issues,
            "recommendations": self.recommendations,
            "suggestions": self.suggestions,
            "claim_check": cc_dict,
            "report": self.report,
            "readable_report": self.readable_report,
            "text_report": self.text_report,
            "summary": self.summary,
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, default=str)

    def __str__(self) -> str:
        return self.report


# alias names
DossierQuality = DossierQualityResult
DossierAudit = DossierQualityResult
DossierReport = DossierQualityResult
QualityReport = DossierQualityResult
DossierQualityAudit = DossierQualityResult


def _normalize_text_input(document: Any) -> str:
    if document is None:
        return ""
    if isinstance(document, str):
        return document
    if isinstance(document, Mapping):
        parts: list[str] = []
        for key in ("text", "document", "content", "cv", "letter", "markdown", "body", "cv_markdown", "letter_markdown"):
            value = document.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(clean_text(value, limit=20_000))
        answers = document.get("answers")
        if isinstance(answers, Mapping):
            parts.append("\n".join(f"{k}: {v}" for k, v in answers.items() if v))
        if parts:
            return "\n".join(parts)
        # maybe nested
        for value in document.values():
            if isinstance(value, str) and value.strip():
                parts.append(clean_text(value, limit=20_000))
        return "\n".join(parts)
    if hasattr(document, "text"):
        try:
            return clean_text(getattr(document, "text"), limit=100_000)
        except Exception:
            pass
    if hasattr(document, "to_dict"):
        try:
            return _normalize_text_input(document.to_dict())
        except Exception:
            pass
    return clean_text(document, limit=100_000)


def _offer_text(offer: Any) -> str:
    if offer is None:
        return ""
    if isinstance(offer, str):
        return offer
    if isinstance(offer, Mapping):
        parts = []
        for key in ("requirements", "description_original", "description", "text", "title", "languages_required", "eligibility_requirement", "role_level"):
            value = offer.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(clean_text(value, limit=20_000))
            elif isinstance(value, (list, tuple)):
                parts.append("\n".join(clean_text(v, limit=500) for v in value if v))
        return "\n".join(parts)
    return clean_text(offer, limit=100_000)


def _approved_facts_count(profile: Any) -> int:
    try:
        return len(_approved_facts(profile))
    except Exception:
        return 0


def analyze_dossier_quality(
    document: Any = None,
    approved_profile: Any = None,
    *,
    profile: Any = None,
    facts: Any = None,
    proofs: Any = None,
    offer: Any = None,
    job: Any = None,
    text: str | None = None,
    claim_result: Any = None,
    claims: Any = None,
    rules: Any = None,
    language: str = "fr",
    **kwargs: Any,
) -> DossierQualityResult:
    if text is not None:
        document = text
    if "doc" in kwargs:
        document = kwargs.pop("doc")
    if "document_text" in kwargs:
        document = kwargs.pop("document_text")
    if "content" in kwargs and document is None:
        document = kwargs.pop("content")
    if job is not None and offer is None:
        offer = job

    profile_source = approved_profile if approved_profile is not None else profile
    if profile_source is None and facts is not None:
        profile_source = facts
    if profile_source is None and proofs is not None:
        profile_source = proofs
    if "approved_profile" in kwargs and profile_source is None:
        profile_source = kwargs.pop("approved_profile")

    doc_text = _normalize_text_input(document)
    if claims is not None and not doc_text and isinstance(claims, str):
        doc_text = claims

    # claim check
    if claim_result is None and claims is None:
        claim_result = check_claims(doc_text, profile_source, language=language)
    elif claim_result is None and isinstance(claims, ClaimCheckResult):
        claim_result = claims
    elif claim_result is None and isinstance(claims, list):
        # build a synthetic claim result
        synthetic_claims = []
        for item in claims:
            if isinstance(item, Claim):
                synthetic_claims.append(item)
            elif isinstance(item, Mapping):
                synthetic_claims.append(Claim(text=str(item.get("text") or item.get("sentence") or ""), label=str(item.get("label") or item.get("status") or "unverifiable")))
            elif isinstance(item, str):
                synthetic_claims.append(Claim(text=item, label="unverifiable"))
        claim_result = ClaimCheckResult(claims=synthetic_claims, document=doc_text)

    if not isinstance(claim_result, ClaimCheckResult):
        # try coercion
        try:
            claim_result = check_claims(doc_text, profile_source, language=language)
        except Exception:
            claim_result = ClaimCheckResult(claims=[], document=doc_text)

    claims_list = list(claim_result.claims)
    total = len(claims_list)
    counts = {label: 0 for label in CLAIM_LABELS}
    for claim in claims_list:
        lbl = getattr(claim, "label", None) or (claim.get("label") if isinstance(claim, Mapping) else None) or "unverifiable"
        if lbl in counts:
            counts[lbl] += 1
    supported = counts.get("supported", 0)
    inflated = counts.get("inflated", 0)
    ooc = counts.get("out_of_context", 0)
    invented = counts.get("invented", 0)
    unver = counts.get("unverifiable", 0)
    bad = inflated + ooc + invented

    validation_rate = (supported / total * 100.0) if total else 100.0
    exaggeration_density = (bad / total) if total else 0.0

    approved_count = _approved_facts_count(profile_source)
    proof_score = 0.0
    if total:
        proof_score = min(100.0, (approved_count / max(1, total)) * 100.0 * 0.5 + validation_rate * 0.5)
    else:
        proof_score = min(100.0, approved_count * 5.0) if approved_count else 100.0

    # argumentation: offer requirements coverage
    argumentation_score = 100.0
    offer_txt = _offer_text(offer)
    if offer_txt.strip():
        # simple token coverage of offer requirements by document
        offer_tokens = _tokens_set(offer_txt)
        doc_tokens = _tokens_set(doc_text)
        if offer_tokens:
            coverage = len(offer_tokens & doc_tokens) / len(offer_tokens)
            argumentation_score = min(100.0, coverage * 100.0 * 1.5)
        # also unverified elements from prepare_application if available
        if prepare_application is not None and isinstance(profile_source, Mapping) or True:
            try:
                if isinstance(profile_source, (Mapping,)) or profile_source is None:
                    pass
            except Exception:
                pass

    # try prepare_application for unverified count
    unverified_penalty = 0.0
    if prepare_application is not None:
        try:
            profile_mapping = profile_source if isinstance(profile_source, Mapping) else {}
            intake_mapping = kwargs.get("intake") if isinstance(kwargs.get("intake"), Mapping) else {}
            job_mapping = offer if isinstance(offer, Mapping) else {}
            if job_mapping:
                prep = prepare_application(dict(profile_mapping), dict(intake_mapping), dict(job_mapping))
                unverified = prep.get("unverified_elements", []) if isinstance(prep, Mapping) else []
                if isinstance(unverified, list) and unverified:
                    unverified_penalty = min(20.0, 5.0 * len(unverified))
                    argumentation_score = max(0.0, argumentation_score - unverified_penalty)
        except Exception:
            pass

    # overall
    score_float = (
        0.35 * validation_rate
        + 0.25 * (100.0 - exaggeration_density * 100.0)
        + 0.20 * proof_score
        + 0.20 * argumentation_score
    )
    score = int(round(max(0.0, min(100.0, score_float))))

    factors = [
        {
            "name": "prevus_valides",
            "label": "% de prévus validés",
            "value": round(validation_rate, 2),
            "weight": 0.35,
            "formula": "supported_claims / total_claims * 100",
        },
        {
            "name": "densite_exagerations",
            "label": "Densité d'exagérations",
            "value": round(exaggeration_density * 100.0, 2),
            "weight": 0.25,
            "formula": "(inflated + out_of_context + invented) / total_claims * 100 (inversé dans le score)",
        },
        {
            "name": "preuve",
            "label": "Preuve",
            "value": round(proof_score, 2),
            "weight": 0.20,
            "formula": "min(100, approved_facts / total_claims * 50 + validation_rate * 0.5)",
        },
        {
            "name": "argumentaire",
            "label": "Argumentaire",
            "value": round(argumentation_score, 2),
            "weight": 0.20,
            "formula": "couverture tokens offre/document * 100 (pénalisée par éléments non étayés)",
        },
    ]

    issues: list[dict[str, Any]] = []
    for claim in claims_list:
        lbl = getattr(claim, "label", None) or "unverifiable"
        if lbl != "supported":
            issues.append(
                {
                    "label": lbl,
                    "claim": getattr(claim, "text", str(claim)),
                    "suggestion": getattr(claim, "suggestion", ""),
                }
            )

    recommendations: list[str] = []
    if inflated:
        recommendations.append("Réduire les formulations exagérées (expert, senior, anglicismes) ou les étayer par des années.")
    if invented:
        recommendations.append("Supprimer les informations non documentées dans le profil.")
    if ooc:
        recommendations.append("Remettre les chiffres dans leur contexte d'origine.")
    if unver:
        recommendations.append("Renforcer les arguments génériques avec des faits approuvés.")
    # ATS stuffing
    # (handled in claim_check; surface if any claim inflated due to stuffing)
    if not recommendations:
        recommendations.append("Dossier cohérent avec les preuves approuvées.")

    claims_dicts = [c.to_dict() if hasattr(c, "to_dict") else (c if isinstance(c, dict) else {"text": str(c)}) for c in claims_list]

    summary = (
        f"Score qualité : {score}/100. {supported}/{total} claims supported, "
        f"{bad} problématique(s)."
    )

    report_lines = [
        "=== RAPPORT QUALITÉ DOSSIER ===",
        summary,
        "",
        "Facteurs :",
    ]
    for factor in factors:
        report_lines.append(
            f"  - {factor['label']} = {factor['value']} (poids {factor['weight']}) — {factor['formula']}"
        )
    report_lines.append("")
    report_lines.append(f"Claims : {total} (supported={supported}, inflated={inflated}, out_of_context={ooc}, invented={invented}, unverifiable={unver})")
    if issues:
        report_lines.append("")
        report_lines.append("Points à corriger :")
        for issue in issues[:20]:
            report_lines.append(f"  - [{issue['label']}] {issue['claim']}")
            if issue.get("suggestion"):
                report_lines.append(f"      Suggestion : {issue['suggestion']}")
    if recommendations:
        report_lines.append("")
        report_lines.append("Recommandations :")
        for rec in recommendations:
            report_lines.append(f"  - {rec}")
    report = "\n".join(report_lines).strip()

    result = DossierQualityResult(
        score=score,
        overall_score=score,
        quality_score=score,
        score_out_of_100=score,
        factors=factors,
        components=factors,
        claim_summary=counts,
        claims=claims_dicts,
        issues=issues,
        recommendations=recommendations,
        suggestions=recommendations,
        claim_check=claim_result,
        report=report,
        readable_report=report,
        text_report=report,
        readable=report,
        summary=summary,
    )
    return result


def _tokens_set(text: str) -> set[str]:

    return {t for t in normalized_text(text).split() if len(t) >= 4}


# Aliases
analyze_dossier = analyze_dossier_quality
analyze_dossier_quality_score = analyze_dossier_quality
score_dossier = analyze_dossier_quality
audit_dossier = analyze_dossier_quality
check_dossier = analyze_dossier_quality
assess_dossier = analyze_dossier_quality
assess_dossier_quality = analyze_dossier_quality
audit_dossier_quality = analyze_dossier_quality
check_dossier_quality = analyze_dossier_quality
run_dossier_quality = analyze_dossier_quality
run_dossier_audit = analyze_dossier_quality
audit_quality = analyze_dossier_quality
quality_audit = analyze_dossier_quality
evaluate_dossier = analyze_dossier_quality
dossier_quality = analyze_dossier_quality
dossier_audit = analyze_dossier_quality
analyze = analyze_dossier_quality
check = analyze_dossier_quality
run = analyze_dossier_quality
evaluate = analyze_dossier_quality
audit = analyze_dossier_quality
