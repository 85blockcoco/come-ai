"""Transparent 0-100 quality score for a generated application dossier (SPEC-042).

The score is deliberately boring: three factors, published formulas and
integer inputs that the person can inspect.  No probabilistic model is
involved — a provider may *write* a draft, but only local deterministic rules
decide whether the draft is supported by approved evidence.

Factors (weights are fixed and returned in the report):

``factuality`` (50 %)
    Share of supported claims, with explicit penalties for inflated,
    out-of-context and invented sentences and for ATS keyword stuffing.
``evidence`` (30 %)
    Which approved proof covers each claim, its level (declared, documented,
    verified, quantified) and whether the evidence service supplied a date.
``argument`` (20 %)
    Coverage of the offer requirements and of the recurring questionnaire
    answers, minus a penalty for generic unsupported arguments.

The report always exposes the numerator, the denominator and the formula, so
the result can be reproduced by hand.  A single invented fact or a fact moved
out of its context blocks the export step, whatever the total score.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from career.claim_check import (
    ClaimVerdict,
    Ruleset,
    build_evidence_ledger,
    check_claims,
    load_rules,
    readable_report,
)
from career.models import clean_text, normalized_text

FACTOR_WEIGHTS: dict[str, float] = {
    "factuality": 0.50,
    "evidence": 0.30,
    "argument": 0.20,
}

LEVEL_POINTS: dict[str, int] = {
    "declared": 55,
    "documented": 80,
    "verified": 95,
    "quantified": 100,
}

VERDICT_LABELS: dict[str, str] = {
    "ready": "prêt à relire et à exporter",
    "review": "à corriger avant export",
    "blocked": "export bloqué — corrections requises",
}

MAX_REQUIREMENTS = 200
MAX_ANSWERS = 200
MAX_REPORTED_ISSUES = 100

_REQUIREMENT_STOPWORDS: frozenset[str] = frozenset(
    {
        "avec", "avoir", "dans", "des", "du", "elle", "en", "est", "et", "être",
        "les", "leur", "leurs", "mais", "nous", "ou", "par", "pas", "plus",
        "pour", "que", "qui", "sans", "sera", "son", "sur", "une", "vos",
        "votre", "vous", "the", "and", "for", "with", "you", "your", "our",
        "are", "must", "have", "will", "this", "that", "from", "une", "aux",
    }
)

_CONTACT_KEYS: frozenset[str] = frozenset(
    {"display_name", "contact_email", "contact_phone", "linkedin_url"}
)


@dataclass(frozen=True, slots=True)
class QualityFactor:
    """One published factor of the global score."""

    key: str
    label: str
    weight: float
    score: int
    formula: str
    inputs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "weight": self.weight,
            "score": self.score,
            "formula": self.formula,
            "inputs": dict(self.inputs),
        }


@dataclass(frozen=True, slots=True)
class DossierQualityReport:
    """Complete, inspectable quality report for one dossier."""

    score: int
    verdict: str
    export_allowed: bool
    factors: tuple[QualityFactor, ...]
    counts: dict[str, int]
    diagnostics: dict[str, Any]
    claim_report: dict[str, Any]
    claim_report_markdown: str
    issues: tuple[dict[str, Any], ...] = ()
    rules_version: str = "unknown"
    warnings: tuple[str, ...] = ()

    @property
    def verdict_label(self) -> str:
        return VERDICT_LABELS.get(self.verdict, self.verdict)

    @property
    def factor_scores(self) -> dict[str, int]:
        return {factor.key: factor.score for factor in self.factors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "verdict": self.verdict,
            "verdict_label": self.verdict_label,
            "export_allowed": self.export_allowed,
            "rules_version": self.rules_version,
            "factors": [factor.to_dict() for factor in self.factors],
            "counts": dict(self.counts),
            "diagnostics": dict(self.diagnostics),
            "issues": list(self.issues),
            "warnings": list(self.warnings),
            "claim_report": dict(self.claim_report),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_markdown(self) -> str:
        lines = [
            "# Audit de qualité du dossier",
            "",
            f"**Score : {self.score}/100 — {self.verdict_label}**",
            "",
            f"- Export autorisé : {'oui' if self.export_allowed else 'non'}",
            f"- Règles : version {self.rules_version}",
            "",
            "## Facteurs et formules",
            "",
        ]
        for factor in self.factors:
            lines.append(
                f"- **{factor.label} : {factor.score}/100** (poids {round(factor.weight * 100)} %)"
            )
            lines.append(f"  - Formule : {factor.formula}")
            if factor.inputs:
                inputs = ", ".join(f"{key}={value}" for key, value in factor.inputs.items())
                lines.append(f"  - Valeurs : {inputs}")
        lines.extend(["", "## Diagnostics", ""])
        for key, value in self.diagnostics.items():
            lines.append(f"- {key} : {value}")
        if self.issues:
            lines.extend(["", "## Signaux prioritaires", ""])
            for issue in self.issues:
                lines.append(
                    f"- [{issue.get('label')}] « {issue.get('text')} » — {issue.get('suggestion')}"
                )
        if self.warnings:
            lines.extend(["", "## Avertissements", ""])
            lines.extend(f"- {warning}" for warning in self.warnings)
        lines.extend(["", "---", "", self.claim_report_markdown])
        return "\n".join(lines)


def _coerce_requirements(requirements: Any) -> list[tuple[str, int]]:
    if requirements is None:
        return []
    if isinstance(requirements, str):
        return [(requirements, 1)] if requirements.strip() else []
    if isinstance(requirements, Mapping):
        for key in ("requirements", "items", "records"):
            if key in requirements:
                return _coerce_requirements(requirements[key])
        text = requirements.get("text") or requirements.get("requirement") or requirements.get("value")
        return [(str(text), 1)] if text else []
    if not isinstance(requirements, Sequence):
        return []
    out: list[tuple[str, int]] = []
    for item in requirements:
        if isinstance(item, str):
            text = clean_text(item, limit=1_000)
            weight = 1
        elif isinstance(item, Mapping):
            text = clean_text(
                item.get("text") or item.get("requirement") or item.get("value"), limit=1_000
            )
            modality = normalized_text(item.get("modality") or item.get("required") or "")
            weight = 2 if modality in {"required", "obligatoire", "mandatory", "must"} else 1
        else:
            continue
        if text:
            out.append((text, weight))
        if len(out) >= MAX_REQUIREMENTS:
            break
    return out


def _coerce_answers(recurring_answers: Any) -> list[tuple[str, str]]:
    if recurring_answers is None:
        return []
    if isinstance(recurring_answers, Mapping):
        if "answers" in recurring_answers and isinstance(recurring_answers["answers"], Mapping):
            recurring_answers = recurring_answers["answers"]
        return [
            (clean_text(question, limit=300), clean_text(answer, limit=2_000))
            for question, answer in recurring_answers.items()
            if clean_text(question, limit=300)
        ][:MAX_ANSWERS]
    if not isinstance(recurring_answers, Sequence):
        return []
    out: list[tuple[str, str]] = []
    for item in recurring_answers:
        if isinstance(item, str):
            out.append((clean_text(item, limit=300), ""))
        elif isinstance(item, Mapping):
            question = clean_text(
                item.get("question") or item.get("prompt") or item.get("key"), limit=300
            )
            answer = clean_text(
                item.get("answer") or item.get("value") or item.get("text"), limit=2_000
            )
            if question:
                out.append((question, answer))
        if len(out) >= MAX_ANSWERS:
            break
    return out


def _requirement_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in normalized_text(text).split():
        if len(token) < 3 or token.isdigit() or token in _REQUIREMENT_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def _requirement_coverage(
    requirements: Sequence[tuple[str, int]],
    document: Mapping[str, str],
) -> tuple[float, int, int, list[dict[str, Any]]]:
    blob = normalized_text(" ".join(document.values()))
    covered_weight = 0
    total_weight = 0
    covered = 0
    detail: list[dict[str, Any]] = []
    for text, weight in requirements:
        tokens = _requirement_tokens(text)
        total_weight += weight
        ratio = (
            len(tokens & set(blob.split())) / len(tokens) if tokens else 0.0
        )
        is_covered = bool(tokens) and ratio >= 0.6
        if is_covered:
            covered += 1
            covered_weight += weight
        detail.append(
            {
                "requirement": clean_text(text, limit=240),
                "weight": weight,
                "token_coverage": round(ratio, 2),
                "covered": is_covered,
            }
        )
    coverage = covered_weight / total_weight if total_weight else 0.0
    return coverage, covered, len(requirements), detail


def _merge_ledger(*sources: Any) -> tuple[Any, ...]:
    merged: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        for evidence in build_evidence_ledger(source):
            key = (evidence.normalized, evidence.category)
            if key in seen:
                continue
            seen.add(key)
            merged.append(evidence)
    return tuple(merged)


def _compose_document(
    document: Any,
    *,
    cv: str | None,
    letter: str | None,
    answers: Any,
) -> dict[str, str]:
    sections: dict[str, str] = {}
    if isinstance(document, Mapping):
        for name, value in document.items():
            if isinstance(value, str) and value.strip():
                sections[str(name)] = value
    elif isinstance(document, str) and document.strip():
        sections["Document"] = document
    if cv and cv.strip():
        sections["CV généré"] = cv
    if letter and letter.strip():
        sections["Lettre générée"] = letter
    if isinstance(answers, Mapping):
        lines = [
            f"{clean_text(question, limit=200)} : {clean_text(answer, limit=2_000)}"
            for question, answer in answers.items()
            if clean_text(answer, limit=2_000)
        ]
        if lines:
            sections["Réponses de formulaire"] = "\n".join(lines)
    elif isinstance(answers, Sequence) and not isinstance(answers, (str, bytes)):
        lines = [clean_text(item, limit=2_000) for item in answers if clean_text(item, limit=2_000)]
        if lines:
            sections["Réponses de formulaire"] = "\n".join(lines)
    return sections


def _answer_facts(answers: Any) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for question, answer in _coerce_answers(answers):
        if not answer:
            continue
        facts.append(
            {
                "fact_id": f"answer_{len(facts):04d}",
                "category": "answer",
                "value": answer,
                "quote": f"{question} : {answer}" if question else answer,
                "level": "declared",
                "source": "intake",
                "topic": question,
            }
        )
    return facts


def _profile_contacts(profile: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(profile, Mapping):
        return []
    return [
        value
        for key in _CONTACT_KEYS
        if isinstance(value := profile.get(key), str) and value.strip()
    ]


def _factuality_factor(
    claims: Sequence[ClaimVerdict],
    counts: Mapping[str, int],
    ats_blocks: int,
) -> QualityFactor:
    total = len(claims)
    if total:
        raw = 100 * (
            counts.get("supported", 0)
            + 0.35 * counts.get("unverifiable", 0)
            - 0.50 * counts.get("inflated", 0)
            - 0.75 * counts.get("out_of_context", 0)
            - 1.00 * counts.get("invented", 0)
        ) / total - 5 * ats_blocks
    else:
        raw = 0.0
    score = max(0, min(100, int(round(raw))))
    return QualityFactor(
        key="factuality",
        label="Factualité (faits validés et exagérations)",
        weight=FACTOR_WEIGHTS["factuality"],
        score=score,
        formula=(
            "100 × (étayées + 0,35 × non vérifiables − 0,50 × exagérées − 0,75 × hors contexte "
            "− 1,00 × inventées) ÷ affirmations auditées − 5 × listes ATS, borné à 0..100"
        ),
        inputs={
            "affirmations": total,
            "étayées": counts.get("supported", 0),
            "non_vérifiables": counts.get("unverifiable", 0),
            "exagérées": counts.get("inflated", 0),
            "hors_contexte": counts.get("out_of_context", 0),
            "inventées": counts.get("invented", 0),
            "listes_ATS": ats_blocks,
        },
    )


def _evidence_factor(claims: Sequence[ClaimVerdict]) -> tuple[QualityFactor, dict[str, Any]]:
    total = len(claims)
    covered = 0
    quality_sum = 0.0
    dated = 0
    levels: dict[str, int] = {}
    for claim in claims:
        evidence = claim.best_evidence
        if not evidence:
            continue
        covered += 1
        level = str(evidence.get("level") or "declared")
        levels[level] = levels.get(level, 0) + 1
        quality_sum += LEVEL_POINTS.get(level, LEVEL_POINTS["declared"]) / 100
        if evidence.get("dated_at"):
            dated += 1
    coverage = covered / total if total else 0.0
    quality = quality_sum / covered if covered else 0.0
    dating = dated / covered if covered else 0.0
    raw = 100 * (0.50 * coverage + 0.35 * quality + 0.15 * dating)
    score = max(0, min(100, int(round(raw))))
    factor = QualityFactor(
        key="evidence",
        label="Preuve (niveau et date des faits approuvés)",
        weight=FACTOR_WEIGHTS["evidence"],
        score=score,
        formula=(
            "100 × (0,50 × part des affirmations couvertes + 0,35 × niveau moyen de la preuve "
            "+ 0,15 × part des preuves datées), borné à 0..100"
        ),
        inputs={
            "affirmations": total,
            "couvertes": covered,
            "couverture": round(coverage, 3),
            "niveau_moyen": round(quality, 3),
            "preuves_datées": dated,
            "part_datée": round(dating, 3),
            "niveaux": dict(sorted(levels.items())),
        },
    )
    return factor, {
        "claims_with_evidence": covered,
        "dated_evidence": dated,
        "evidence_levels": dict(sorted(levels.items())),
    }


def _argument_factor(
    claims: Sequence[ClaimVerdict],
    *,
    requirements: Sequence[tuple[str, int]],
    answers: Sequence[tuple[str, str]],
    document: Mapping[str, str],
    generic_count: int,
) -> tuple[QualityFactor, dict[str, Any]]:
    parts: list[tuple[float, float]] = []
    req_coverage = None
    req_detail: list[dict[str, Any]] = []
    if requirements:
        req_coverage, req_covered, req_total, req_detail = _requirement_coverage(requirements, document)
        parts.append((0.60, req_coverage))
    else:
        req_covered = req_total = 0

    answered = sum(1 for _question, answer in answers if answer.strip())
    answer_coverage = answered / len(answers) if answers else 0.0
    if answers:
        parts.append((0.40, answer_coverage))
    else:
        answered = 0

    total = len(claims)
    generic_density = generic_count / total if total else 0.0
    if parts:
        weighted = sum(weight * value for weight, value in parts) / sum(weight for weight, _ in parts)
        raw = 100 * weighted - 10 * generic_density
    else:
        raw = 50.0  # No requirement and no recurring answer: neutral, never a fake pass.
    score = max(0, min(100, int(round(raw))))
    factor = QualityFactor(
        key="argument",
        label="Argumentaire (exigences de l'offre et réponses récurrentes)",
        weight=FACTOR_WEIGHTS["argument"],
        score=score,
        formula=(
            "100 × (0,60 × exigences couvertes + 0,40 × réponses récurrentes renseignées, "
            "pondérations renormalisées si une entrée manque) − 10 × densité d'arguments génériques; "
            "50 neutre si aucune exigence ni réponse n'est fournie"
        ),
        inputs={
            "exigences": req_total,
            "exigences_couvertes": req_covered,
            "couverture_exigences": round(req_coverage, 3) if req_coverage is not None else None,
            "réponses": len(answers),
            "réponses_renseignées": answered,
            "couverture_réponses": round(answer_coverage, 3),
            "arguments_génériques": generic_count,
            "densité_générique": round(generic_density, 3),
        },
    )
    return factor, {
        "requirements_total": req_total,
        "requirements_covered": req_covered,
        "requirements_coverage": round(req_coverage, 3) if req_coverage is not None else None,
        "requirements_detail": req_detail,
        "recurring_answers_total": len(answers),
        "recurring_answers_answered": answered,
        "recurring_answers_coverage": round(answer_coverage, 3),
        "generic_arguments": generic_count,
        "generic_density": round(generic_density, 3),
    }


def audit_dossier(
    document: Any = None,
    *,
    cv: str | None = None,
    letter: str | None = None,
    answers: Any = None,
    profile: Mapping[str, Any] | None = None,
    evidence: Any = None,
    evidence_service: Any = None,
    extra_facts: Any = None,
    requirements: Any = None,
    recurring_answers: Any = None,
    rules: Ruleset | None = None,
    rules_path: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> DossierQualityReport:
    """Audit one generated dossier and return a transparent quality report.

    ``document`` may be a Markdown string, a mapping of sections
    (``{"CV": ..., "Lettre": ...}``), or be supplied through ``cv`` / ``letter``.
    ``requirements`` is the canonical offer requirement list; ``answers`` and
    ``recurring_answers`` are the questionnaire answers used to judge the
    argumentative coverage.
    """

    ruleset = rules if isinstance(rules, Ruleset) else load_rules(rules_path)
    sections = _compose_document(document, cv=cv, letter=letter, answers=answers or recurring_answers)

    ledger = _merge_ledger(
        evidence,
        profile,
        extra_facts,
        _answer_facts(answers or recurring_answers),
        evidence_service,
    )

    effective_context = dict(context or {})
    contacts = list(effective_context.get("contacts") or [])
    contacts.extend(_profile_contacts(profile))
    if contacts:
        effective_context["contacts"] = contacts

    claim_report = check_claims(
        sections,
        evidence=ledger,
        rules=ruleset,
        context=effective_context,
    )
    claims = claim_report.audited_claims
    counts = dict(claim_report.counts)

    ats_blocks = sum(
        1 for claim in claims if any(issue.code == "ats_keyword_stuffing" for issue in claim.issues)
    )
    generic_count = sum(
        1 for claim in claims if any(issue.code == "generic_argument" for issue in claim.issues)
    )

    factuality = _factuality_factor(claims, counts, ats_blocks)
    evidence_factor, evidence_diag = _evidence_factor(claims)
    requirement_items = _coerce_requirements(requirements)
    answer_items = _coerce_answers(recurring_answers if recurring_answers is not None else answers)
    argument, argument_diag = _argument_factor(
        claims,
        requirements=requirement_items,
        answers=answer_items,
        document=sections,
        generic_count=generic_count,
    )

    total = int(round(
        FACTOR_WEIGHTS["factuality"] * factuality.score
        + FACTOR_WEIGHTS["evidence"] * evidence_factor.score
        + FACTOR_WEIGHTS["argument"] * argument.score
    ))
    total = max(0, min(100, total))
    if not claims:
        total = 0

    risky = counts.get("invented", 0) + counts.get("out_of_context", 0) + counts.get("inflated", 0)
    if not claims:
        verdict = "blocked"
    elif counts.get("invented", 0) or counts.get("out_of_context", 0):
        verdict = "blocked"
    elif total < 60:
        verdict = "blocked"
    elif total >= 85 and risky == 0 and ats_blocks == 0:
        verdict = "ready"
    else:
        verdict = "review"
    export_allowed = verdict in {"ready", "review"}

    issues: list[dict[str, Any]] = []
    for claim in claims:
        if claim.label in {"supported"} and not any(
            issue.code == "ats_keyword_stuffing" for issue in claim.issues
        ):
            continue
        issues.append(
            {
                "index": claim.index,
                "section": claim.section,
                "label": claim.label,
                "label_label": claim.label_label,
                "text": claim.text,
                "suggestion": claim.suggestion,
                "evidence": claim.best_evidence,
                "issues": [issue.to_dict() for issue in claim.issues],
            }
        )
        if len(issues) >= MAX_REPORTED_ISSUES:
            break

    diagnostics = {
        "claim_count": len(claims),
        "supported_rate": claim_report.support_rate,
        "exaggeration_density": claim_report.exaggeration_density,
        "ats_stuffing_blocks": ats_blocks,
        "generic_arguments": generic_count,
        "skipped_claims": dict(claim_report.skipped),
        **evidence_diag,
        **argument_diag,
    }
    warnings = list(claim_report.warnings)
    if not sections:
        warnings.append("Aucun document fourni : le dossier ne peut pas être audité.")

    return DossierQualityReport(
        score=total,
        verdict=verdict,
        export_allowed=export_allowed,
        factors=(factuality, evidence_factor, argument),
        counts=counts,
        diagnostics=diagnostics,
        claim_report=claim_report.to_dict(),
        claim_report_markdown=readable_report(claim_report),
        issues=tuple(issues),
        rules_version=ruleset.version,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def build_dossier_quality_report(*args: Any, **kwargs: Any) -> DossierQualityReport:
    """Alias kept for callers that prefer an explicit builder name."""

    return audit_dossier(*args, **kwargs)


# Stable aliases.
quality_report = audit_dossier
audit_application_dossier = audit_dossier
