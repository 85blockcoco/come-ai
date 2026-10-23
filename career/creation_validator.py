"""Real-time, local validation for creation wizard steps.

The rules are intentionally conservative: a blocking issue always names the
exact element to fix, and the anti-invention check is limited to verifiable
signals (declared claims, numeric achievements, unresolved placeholders and
unknown evidence references).  It never guesses that a sentence is false.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime, timezone
from typing import Any

from .creation_session import (
    CreationPreferences,
    CreationStep,
    CreationSession,
    Severity,
    _bounded_text,
)
from .models import clean_text, normalized_text


MAX_ISSUES = 60
MAX_TEXT_SCAN = 20_000

TEXT_KEYS = ("text", "content", "draft", "value")
_PLACEHOLDER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\{\{[^{}]{1,80}\}\}"),
    re.compile(
        r"\[\s*(?:votre|vos|nom|prénom|prenom|date|entreprise|poste|téléphone|telephone|"
        r"e-?mail|adresse|ville|école|ecole|diplôme|diplome|xxx|à compléter|a completer)"
        r"[^\[\]]{0,60}\]",
        re.IGNORECASE,
    ),
    re.compile(r"<[A-Za-zÀ-ÿ][^<>]{0,38}>"),
    re.compile(r"\b(?:TODO|FIXME|XXX+|LOREM IPSUM)\b", re.IGNORECASE),
)
_NUMERIC_FACT = re.compile(
    r"(?<![\w])(\d+(?:[.,]\d+)?)\s*(%|k€|K€|M€|m€|€|k\$|K\$|M\$|\$|ans?|years?|"
    r"personnes?|people|collaborateurs?|salariés?|salaries?|mois|months?)(?![\w])",
    re.UNICODE,
)
_INFORMAL = re.compile(
    r"\b(?:super|génial|genial|trop|hyper|vachement|lol|mdr|nickel|top)\b|!!+",
    re.IGNORECASE,
)
_DATE_RANGE = re.compile(
    r"\b(19\d{2}|20\d{2})\s*(?:-|–|—|/|à|to)\s*(19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)
_DUPLICATE_MIN_LENGTH = 24
_DEFAULT_MAX_CHARS = {"write": 2_200, "review": 1_600, "validate": 1_600}


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: Severity
    message: str
    field: str = ""
    step_number: int | None = None
    evidence_refs: list[str] = dataclass_field(default_factory=list)
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "field": self.field,
            "step_number": self.step_number,
            "evidence_refs": list(self.evidence_refs),
            "suggestion": self.suggestion,
        }


@dataclass
class ValidationReport:
    issues: list[ValidationIssue]
    checked_at: str
    step_number: int | None = None

    @property
    def blocking(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "blocking"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def infos(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "info"]

    @property
    def can_export(self) -> bool:
        return not self.blocking

    @property
    def score(self) -> int:
        value = 100 - 35 * len(self.blocking) - 12 * len(self.warnings) - 3 * len(self.infos)
        return max(0, min(100, value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "checked_at": self.checked_at,
            "can_export": self.can_export,
            "score": self.score,
            "counts": {
                "blocking": len(self.blocking),
                "warning": len(self.warnings),
                "info": len(self.infos),
            },
            "issues": [issue.to_dict() for issue in self.issues[:MAX_ISSUES]],
            "truncated": len(self.issues) > MAX_ISSUES,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _text_entries(user_input: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Flatten the known free-text slots of a step input."""
    if not isinstance(user_input, dict):
        return []
    entries: list[tuple[str, str]] = []
    for key in TEXT_KEYS:
        value = user_input.get(key)
        if isinstance(value, str) and value.strip():
            entries.append((key, _bounded_text(value, limit=MAX_TEXT_SCAN)))
    fields = user_input.get("fields")
    if isinstance(fields, dict):
        for key, value in fields.items():
            if isinstance(value, str) and value.strip():
                entries.append((f"fields.{clean_text(key, limit=80)}", _bounded_text(value, limit=MAX_TEXT_SCAN)))
    for key in ("blocks", "paragraphs", "answers"):
        values = user_input.get(key)
        if isinstance(values, list):
            for index, value in enumerate(values):
                if isinstance(value, str) and value.strip():
                    entries.append((f"{key}.{index}", _bounded_text(value, limit=MAX_TEXT_SCAN)))
                elif isinstance(value, dict):
                    text = value.get("text") or value.get("content")
                    if isinstance(text, str) and text.strip():
                        entries.append((f"{key}.{index}", _bounded_text(text, limit=MAX_TEXT_SCAN)))
    return entries


def _evidence_corpus(evidence: list[dict[str, Any]] | None) -> str:
    parts: list[str] = []
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        for key in ("text", "quote", "excerpt", "content"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value)
    return "\n".join(parts)


def _fact_key(value: str) -> str:
    return re.sub(r"\s+", "", value.replace(",", ".").casefold())


def _known_evidence_ids(evidence: list[dict[str, Any]] | None) -> set[str]:
    return {
        clean_text(item.get("id"), limit=80)
        for item in evidence or []
        if isinstance(item, dict) and clean_text(item.get("id"), limit=80)
    }


def _attached_refs(user_input: dict[str, Any] | None) -> list[str]:
    if not isinstance(user_input, dict):
        return []
    raw = user_input.get("evidence_refs")
    if not isinstance(raw, list):
        return []
    return [clean_text(item, limit=80) for item in raw if clean_text(item, limit=80)]


def _placeholder_issues(entries: list[tuple[str, str]]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for field_name, text in entries:
        for pattern in _PLACEHOLDER_PATTERNS:
            for match in pattern.finditer(text):
                issues.append(
                    ValidationIssue(
                        code="placeholder_unresolved",
                        severity="blocking",
                        message=f"Placeholder non résolu : « {clean_text(match.group(0), limit=80)} ».",
                        field=field_name,
                        suggestion="Remplacez le placeholder par un fait vérifié ou supprimez-le avant l’export.",
                    )
                )
    return issues


def _anti_invention_issues(entries: list[tuple[str, str]], evidence: list[dict[str, Any]] | None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    corpus = _fact_key(_evidence_corpus(evidence))
    for field_name, text in entries:
        for match in _NUMERIC_FACT.finditer(text):
            key = _fact_key(match.group(0))
            if not key:
                continue
            if corpus and key in corpus:
                continue
            issues.append(
                ValidationIssue(
                    code="anti_invention_numeric",
                    severity="blocking",
                    message=(
                        f"Le fait chiffré « {clean_text(match.group(0), limit=80)} » n’est étayé par aucune preuve attachée."
                    ),
                    field=field_name,
                    suggestion="Ajoutez une preuve qui contient exactement ce chiffre, ou retirez-le.",
                )
            )
    return issues


def _claim_issues(entries: list[tuple[str, str]], evidence: list[dict[str, Any]] | None, user_input: dict[str, Any] | None) -> list[ValidationIssue]:
    if not isinstance(user_input, dict):
        return []
    claims = user_input.get("claims")
    if not isinstance(claims, list) or not claims:
        return []
    corpus = normalized_text(_evidence_corpus(evidence))
    issues: list[ValidationIssue] = []
    for claim in claims:
        text = _bounded_text(claim, limit=400)
        key = normalized_text(text)
        if not key or len(key) < 3:
            continue
        if key in corpus:
            continue
        issues.append(
            ValidationIssue(
                code="anti_invention_claim",
                severity="blocking",
                message=f"L’affirmation « {text} » n’est étayée par aucune preuve attachée.",
                field="claims",
                suggestion="Ajoutez la preuve correspondante ou retirez l’affirmation.",
            )
        )
    return issues


def _evidence_ref_issues(user_input: dict[str, Any] | None, evidence: list[dict[str, Any]] | None) -> list[ValidationIssue]:
    known = _known_evidence_ids(evidence)
    issues: list[ValidationIssue] = []
    for reference in _attached_refs(user_input):
        if reference not in known:
            issues.append(
                ValidationIssue(
                    code="evidence_ref_unknown",
                    severity="blocking",
                    message=f"La preuve « {reference} » est introuvable dans les preuves disponibles.",
                    field="evidence_refs",
                    evidence_refs=[reference],
                    suggestion="Retirez cette référence ou rattachez une preuve existante.",
                )
            )
    return issues


def _required_evidence_issues(
    user_input: dict[str, Any] | None,
    evidence: list[dict[str, Any]] | None,
    required_evidence: list[dict[str, Any]] | None,
) -> list[ValidationIssue]:
    required = [item for item in required_evidence or [] if isinstance(item, dict)]
    if not required:
        return []
    available = {
        clean_text(item.get("id"), limit=80): normalized_text(item.get("requirement") or item.get("text") or "")
        for item in evidence or []
        if isinstance(item, dict)
    }
    attached = set(_attached_refs(user_input))
    issues: list[ValidationIssue] = []
    for item in required:
        label = clean_text(item.get("requirement") or item.get("label"), limit=200)
        if not label:
            continue
        explicit_ids = [clean_text(value, limit=80) for value in item.get("evidence_ids") or [] if clean_text(value, limit=80)]
        matching_ids = [
            identifier
            for identifier, requirement in available.items()
            if requirement and (normalized_text(label) in requirement or requirement in normalized_text(label))
        ]
        accepted = set(explicit_ids) | set(matching_ids)
        if accepted and attached & accepted:
            continue
        if not accepted and not attached:
            continue
        issues.append(
            ValidationIssue(
                code="required_evidence_missing",
                severity="blocking",
                message=f"Preuve manquante obligatoire pour « {label} ».",
                field="evidence_refs",
                suggestion="Attachez une preuve vérifiable à cette exigence ou retirez l’exigence du bloc.",
            )
        )
    return issues


def _date_issues(entries: list[tuple[str, str]]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for field_name, text in entries:
        for match in _DATE_RANGE.finditer(text):
            start, end = int(match.group(1)), int(match.group(2))
            if start > end:
                issues.append(
                    ValidationIssue(
                        code="date_incoherence",
                        severity="warning",
                        message=f"Dates incohérentes : « {match.group(0)} » (début après fin).",
                        field=field_name,
                        suggestion="Corrigez l’ordre des années ou précisez la période exacte.",
                    )
                )
    return issues


def _length_issues(step: CreationStep, entries: list[tuple[str, str]]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    configured = step.content.get("max_chars")
    maximum = int(configured) if isinstance(configured, (int, float)) else _DEFAULT_MAX_CHARS.get(step.type, 2_200)
    total = sum(len(text) for _, text in entries)
    if total > maximum:
        issues.append(
            ValidationIssue(
                code="length_exceeded",
                severity="warning",
                message=f"Longueur dépassée : {total} caractères pour un maximum conseillé de {maximum}.",
                field="text",
                suggestion="Raccourcissez les répétitions et gardez les faits vérifiables.",
            )
        )
    for field_name, text in entries:
        if len(text) > max(800, maximum):
            issues.append(
                ValidationIssue(
                    code="length_exceeded_block",
                    severity="warning",
                    message=f"Le bloc « {field_name} » dépasse {max(800, maximum)} caractères.",
                    field=field_name,
                    suggestion="Découpez ce bloc en paragraphes plus courts.",
                )
            )
    return issues


def _tone_issues(entries: list[tuple[str, str]]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for field_name, text in entries:
        match = _INFORMAL.search(text)
        if match:
            issues.append(
                ValidationIssue(
                    code="tone_informal",
                    severity="info",
                    message=f"Ton informel détecté : « {clean_text(match.group(0), limit=40)} ».",
                    field=field_name,
                    suggestion="Adoptez un ton professionnel adapté au secteur et à l’entreprise.",
                )
            )
    return issues


def _duplicate_issues(entries: list[tuple[str, str]]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen: dict[str, str] = {}
    for field_name, text in entries:
        for line in text.splitlines():
            key = normalized_text(line)
            if len(key) < _DUPLICATE_MIN_LENGTH:
                continue
            if key in seen:
                issues.append(
                    ValidationIssue(
                        code="duplicate_line",
                        severity="warning",
                        message=f"Ligne en double : « {clean_text(line, limit=120)} ».",
                        field=field_name,
                        suggestion="Supprimez la répétition pour garder un document dense.",
                    )
                )
                break
            seen[key] = field_name
    return issues


def _completeness_issues(step: CreationStep, entries: list[tuple[str, str]]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if step.status == "skipped":
        return issues
    if step.type in {"write", "review", "validate"} and not entries:
        issues.append(
            ValidationIssue(
                code="completeness_empty",
                severity="warning",
                message="Cette étape ne contient encore aucun texte vérifiable.",
                field="text",
                suggestion="Renseignez le bloc ou marquez explicitement l’étape comme ignorée.",
            )
        )
    required_fields = step.content.get("required_fields")
    if isinstance(required_fields, list):
        fields = step.user_input.get("fields") if isinstance(step.user_input, dict) else None
        fields = fields if isinstance(fields, dict) else {}
        for raw_field in required_fields:
            name = clean_text(raw_field, limit=120)
            if name and not clean_text(fields.get(name), limit=MAX_TEXT_SCAN):
                issues.append(
                    ValidationIssue(
                        code="completeness_required_field",
                        severity="blocking",
                        message=f"Champ obligatoire manquant : « {name} ».",
                        field=f"fields.{name}",
                        suggestion="Renseignez ce champ avec un fait vérifié.",
                    )
                )
    return issues


def _require_evidence_issue(step: CreationStep, user_input: dict[str, Any] | None, evidence: list[dict[str, Any]] | None) -> list[ValidationIssue]:
    if not step.content.get("require_evidence"):
        return []
    if _attached_refs(user_input):
        return []
    return [
        ValidationIssue(
            code="required_evidence_missing",
            severity="blocking",
            message="Aucune preuve n’est attachée à cette étape alors qu’elle l’exige.",
            field="evidence_refs",
            suggestion="Attachez au moins une preuve issue de votre profil ou ajoutez une preuve vérifiable.",
        )
    ]


def validate_step(
    step: CreationStep,
    *,
    evidence: list[dict[str, Any]] | None = None,
    preferences: CreationPreferences | None = None,
    required_evidence: list[dict[str, Any]] | None = None,
    checked_at: str | None = None,
) -> ValidationReport:
    """Validate one step without any network or model call."""
    del preferences  # reserved for future preference-aware copy checks
    entries = _text_entries(step.user_input)
    issues: list[ValidationIssue] = []
    issues.extend(_placeholder_issues(entries))
    issues.extend(_anti_invention_issues(entries, evidence))
    issues.extend(_claim_issues(entries, evidence, step.user_input))
    issues.extend(_evidence_ref_issues(step.user_input, evidence))
    issues.extend(_required_evidence_issues(step.user_input, evidence, required_evidence))
    issues.extend(_require_evidence_issue(step, step.user_input, evidence))
    issues.extend(_date_issues(entries))
    issues.extend(_length_issues(step, entries))
    issues.extend(_tone_issues(entries))
    issues.extend(_duplicate_issues(entries))
    issues.extend(_completeness_issues(step, entries))
    issues = [
        ValidationIssue(
            code=issue.code,
            severity=issue.severity,
            message=issue.message,
            field=issue.field,
            step_number=issue.step_number or step.step_number,
            evidence_refs=issue.evidence_refs,
            suggestion=issue.suggestion,
        )
        for issue in issues
    ]
    return ValidationReport(issues=issues[:MAX_ISSUES], checked_at=checked_at or _now(), step_number=step.step_number)


def validate_session(
    session: CreationSession,
    *,
    evidence: list[dict[str, Any]] | None = None,
    preferences: CreationPreferences | None = None,
    required_evidence: list[dict[str, Any]] | None = None,
    require_all_steps: bool = True,
    checked_at: str | None = None,
) -> ValidationReport:
    """Aggregate step reports and block export until every prior step is done."""
    timestamp = checked_at or _now()
    issues: list[ValidationIssue] = []
    for step in session.steps:
        report = validate_step(
            step,
            evidence=evidence,
            preferences=preferences,
            required_evidence=required_evidence,
            checked_at=timestamp,
        )
        issues.extend(report.issues)
    if require_all_steps:
        # The final "choose/export" step cannot be completed before exporting,
        # so only the preceding steps are required here.
        export_step_numbers = {
            step.step_number
            for step in session.steps
            if step.type == "choose" and step.step_number == session.total_steps
        }
        for step in session.steps:
            if step.step_number in export_step_numbers:
                continue
            if step.status not in {"completed", "skipped"}:
                issues.append(
                    ValidationIssue(
                        code="step_incomplete",
                        severity="blocking",
                        message=f"L’étape {step.step_number} « {step.title} » n’est pas terminée.",
                        field="status",
                        step_number=step.step_number,
                        suggestion="Terminez l’étape ou marquez-la comme ignorée explicitement.",
                    )
                )
    return ValidationReport(issues=issues[:MAX_ISSUES], checked_at=timestamp)


def describe_blockers(report: ValidationReport) -> str:
    """Return one short, user-facing sentence for an export refusal."""
    messages = [issue.message for issue in report.blocking[:3]]
    suffix = " …" if len(report.blocking) > 3 else ""
    return " ; ".join(messages) + suffix


def today_iso() -> str:
    return date.today().isoformat()
