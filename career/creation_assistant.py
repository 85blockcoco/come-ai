"""Deterministic creation assistant: wizard guidance, suggestions, export.

The assistant is a local orchestrator.  It proposes only what the stored
profile, the selected offer and the attached evidence can support, explains
every proposal, validates in real time, and learns from explicit decisions.
It never calls a model, never contacts a network service and never submits an
application.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .application_prep import extract_requirements, prepare_application
from .creation_session import (
    CREATION_LABELS,
    CREATION_TYPES,
    MAX_TEXT,
    CreationPreferences,
    CreationSession,
    CreationStep,
    CreationStore,
    Suggestion,
    ValidationRule,
    _bounded_text,
    apply_preferences,
    choice,
    learn_from_decision,
    new_session_id,
    preference_match_score,
    record_session_use,
)
from .creation_validator import (
    ValidationReport,
    describe_blockers,
    validate_session,
    validate_step,
)
from .document_export import write_docx, write_pdf
from .models import clean_text, normalized_text, utc_now
from workspace_core import UserFacingError


SCORE_WEIGHTS: dict[str, float] = {
    "evidence_relevance": 0.4,
    "offer_alignment": 0.3,
    "user_preference_match": 0.2,
    "best_practice_score": 0.1,
}
SHOW_THRESHOLD = 0.6
MAX_SUGGESTIONS = 8
MAX_EVIDENCE = 16
MAX_GAPS = 10
EXPORT_FORMATS = ("json", "docx", "pdf")

_STEP_ACCEPTS: dict[str, set[str]] = {
    "select": {"structure", "proof", "addition"},
    "choose": {"structure", "proof", "text", "reorder"},
    "write": {"text", "reformulation", "removal", "proof", "addition"},
    "review": {"proof", "reformulation", "text", "removal", "structure", "reorder", "addition"},
    "attach": {"proof", "addition"},
    "validate": {"proof", "addition", "removal", "text"},
}

_REFORMULATIONS: tuple[tuple[str, str], ...] = (
    (r"gestion\s+d[’']?\s*[ée]quipe", "management d’équipe"),
    (r"gestion\s+de\s+l[’']?\s*[ée]quipe", "management d’équipe"),
    (r"g[ée]r[ée]\s+une\s+[ée]quipe", "dirigé une équipe"),
    (r"\bg[ée]r[ée]\b", "dirigé"),
    (r"analyse\s+financi[èe]re", "financial analysis"),
    (r"mod[ée]lisation\s+financi[èe]re", "financial modeling"),
    (r"mod[ée]lisation\s+lbo", "LBO modeling"),
    (r"recherche\s+quantitative", "quantitative research"),
    (r"gestion\s+de\s+projet", "project management"),
    (r"n[ée]gociation", "negotiation"),
    (r"gestion\s+de\s+portefeuille", "portfolio management"),
)
_PLACEHOLDER_HINT = re.compile(
    r"\{\{[^{}]{1,80}\}\}|\b(?:TODO|FIXME|XXX+)\b|\[\s*(?:votre|nom|date|entreprise|poste|à compléter)[^\[\]]{0,60}\]",
    re.IGNORECASE,
)
_INFORMAL_HINT = re.compile(r"\b(?:super|génial|trop|hyper|lol|mdr|nickel)\b|!!+", re.IGNORECASE)


@dataclass(frozen=True)
class WizardStepSpec:
    title: str
    description: str
    type: str
    content: dict[str, Any] = field(default_factory=dict)
    validation: ValidationRule | None = None


def _wizard_step(
    title: str,
    description: str,
    type_: str,
    content: dict[str, Any] | None = None,
    *,
    rule_id: str = "",
    rule_label: str = "",
    severity: str = "warning",
) -> WizardStepSpec:
    rule = None
    if rule_id:
        rule = ValidationRule(rule_id=rule_id, label=rule_label or title, severity=severity, check=rule_id, params={})
    return WizardStepSpec(title=title, description=description, type=type_, content=content or {}, validation=rule)


WIZARDS: dict[str, tuple[WizardStepSpec, ...]] = {
    "cv": (
        _wizard_step(
            "Sélection de l’offre",
            "Choisissez l’offre cible : les exigences et les preuves guideront la relecture.",
            "select",
            {"offer_required": True, "hint": "Une offre officielle déjà enregistrée dans Career."},
            rule_id="offer_selected",
            rule_label="Une offre cible est sélectionnée",
            severity="blocking",
        ),
        _wizard_step(
            "Choix de la variante",
            "Sélectionnez la variante de CV adaptée au métier de l’offre.",
            "choose",
            {"options": ["m_a", "markets", "corporate_finance"]},
            rule_id="variant_selected",
            rule_label="Une variante de CV est choisie",
        ),
        _wizard_step(
            "Relecture bloc par bloc",
            "Relisez chaque bloc : les suggestions citent la preuve et expliquent pourquoi.",
            "review",
            {"max_chars": 1_400},
            rule_id="blocks_reviewed",
            rule_label="Les blocs principaux sont relus",
        ),
        _wizard_step(
            "Validation des preuves",
            "Attachez une preuve vérifiable à chaque affirmation et vérifiez l’absence d’invention.",
            "validate",
            {"require_evidence": True},
            rule_id="proofs_attached",
            rule_label="Les preuves sont attachées",
            severity="blocking",
        ),
        _wizard_step(
            "Export final",
            "Exportez le CV en Word, PDF ou JSON après validation.",
            "choose",
            {"formats": ["docx", "pdf", "json"]},
            rule_id="export_ready",
            rule_label="Le document est prêt à être exporté",
        ),
    ),
    "cover_letter": (
        _wizard_step(
            "Sélection de l’offre et du CV",
            "Choisissez l’offre et la version du CV qui serviront de base factuelle.",
            "select",
            {"offer_required": True},
            rule_id="offer_selected",
            rule_label="Une offre cible est sélectionnée",
            severity="blocking",
        ),
        _wizard_step(
            "Structure de la lettre",
            "Rédigez l’accroche, le corps et la conclusion en annonçant les preuves.",
            "write",
            {"max_chars": 2_400, "sections": ["Accroche", "Corps", "Conclusion"]},
            rule_id="letter_structured",
            rule_label="La lettre est structurée",
        ),
        _wizard_step(
            "Preuves par paragraphe",
            "Chaque paragraphe s’appuie sur une preuve citée exactement.",
            "attach",
            {"require_evidence": True},
            rule_id="letter_proofs",
            rule_label="Chaque paragraphe est étayé",
            severity="blocking",
        ),
        _wizard_step(
            "Ton et style",
            "Adaptez le ton au secteur et à l’entreprise sans modifier les faits.",
            "write",
            {"max_chars": 1_200, "tone": True},
            rule_id="tone_adapted",
            rule_label="Le ton est adapté",
        ),
        _wizard_step(
            "Relecture finale",
            "Relisez la lettre complète puis exportez-la.",
            "choose",
            {"formats": ["docx", "pdf", "json"]},
            rule_id="export_ready",
            rule_label="La lettre est prête à être exportée",
        ),
    ),
    "profile": (
        _wizard_step(
            "Source du profil",
            "Importez un CV ou partez du profil existant, sans connexion réseau.",
            "select",
            {"sources": ["cv", "existing_profile", "manual"], "local_only": True},
            rule_id="profile_source",
            rule_label="Une source locale est choisie",
        ),
        _wizard_step(
            "Faits extraits",
            "Approuvez chaque fait un par un : formation, expériences, compétences, langues.",
            "write",
            {"max_chars": 2_000, "required_fields": ["formation"]},
            rule_id="facts_approved",
            rule_label="Les faits sont approuvés",
        ),
        _wizard_step(
            "Preuves par champ",
            "Associez une preuve à chaque fait important avant de l’activer.",
            "attach",
            {"require_evidence": True},
            rule_id="facts_proved",
            rule_label="Les faits importants sont étayés",
            severity="blocking",
        ),
        _wizard_step(
            "Complétion des manques",
            "Documentez les compétences manquantes ou laissez-les absentes : rien n’est inventé.",
            "validate",
            {"max_chars": 1_600},
            rule_id="gaps_handled",
            rule_label="Les manques sont traités honnêtement",
        ),
        _wizard_step(
            "Activation du profil",
            "Activez le profil validé pour le matching local.",
            "choose",
            {"actions": ["activate", "keep_draft"]},
            rule_id="profile_ready",
            rule_label="Le profil est prêt",
        ),
    ),
    "application": (
        _wizard_step(
            "Kit de candidature",
            "Choisissez l’offre et le profil pour préparer le kit complet.",
            "select",
            {"offer_required": True},
            rule_id="offer_selected",
            rule_label="Une offre cible est sélectionnée",
            severity="blocking",
        ),
        _wizard_step(
            "Relecture du CV et de la lettre",
            "Relisez les deux documents et ajustez uniquement les faits vérifiables.",
            "review",
            {"max_chars": 1_600},
            rule_id="kit_reviewed",
            rule_label="Le kit est relu",
        ),
        _wizard_step(
            "Checklist des pièces",
            "Vérifiez les pièces jointes demandées avant l’export.",
            "attach",
            {"checklist": ["CV", "Lettre", "Relevés", "Références"]},
            rule_id="documents_checked",
            rule_label="Les pièces sont vérifiées",
        ),
        _wizard_step(
            "Validation finale",
            "Lancez la validation anti-invention et les contrôles de cohérence.",
            "validate",
            {"require_evidence": True},
            rule_id="application_validated",
            rule_label="Le dossier est validé",
            severity="blocking",
        ),
        _wizard_step(
            "Export du dossier",
            "Exportez le dossier prêt à déposer manuellement.",
            "choose",
            {"formats": ["docx", "pdf", "json"]},
            rule_id="export_ready",
            rule_label="Le dossier est prêt à être exporté",
        ),
    ),
    "interview_prep": (
        _wizard_step(
            "Sélection de l’offre",
            "Choisissez l’offre pour préparer les questions et les preuves pertinentes.",
            "select",
            {"offer_required": True},
            rule_id="offer_selected",
            rule_label="Une offre cible est sélectionnée",
        ),
        _wizard_step(
            "Notes de préparation",
            "Rédigez vos exemples concrets : contexte, action, résultat réel.",
            "write",
            {"max_chars": 2_000},
            rule_id="notes_ready",
            rule_label="Les exemples sont rédigés",
        ),
        _wizard_step(
            "Relecture des réponses",
            "Relisez chaque réponse et vérifiez qu’elle s’appuie sur une preuve.",
            "review",
            {"max_chars": 1_600},
            rule_id="answers_reviewed",
            rule_label="Les réponses sont relues",
        ),
        _wizard_step(
            "Validation",
            "Vérifiez l’absence d’invention et la cohérence des exemples.",
            "validate",
            {"require_evidence": True},
            rule_id="prep_validated",
            rule_label="La préparation est validée",
            severity="blocking",
        ),
        _wizard_step(
            "Finalisation",
            "Finalisez vos notes d’entretien.",
            "choose",
            {"formats": ["json", "docx", "pdf"]},
            rule_id="prep_ready",
            rule_label="La préparation est prête",
        ),
    ),
}


@dataclass
class CreationContext:
    offer: dict[str, Any] | None = None
    profile: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    requirements: list[dict[str, Any]] = field(default_factory=list)
    required_evidence: list[dict[str, Any]] = field(default_factory=list)
    prepared: dict[str, Any] | None = None


def _tokens(value: Any) -> list[str]:
    return [token for token in normalized_text(value).split() if len(token) > 2]


def _offer_text(offer: dict[str, Any] | None) -> str:
    if not isinstance(offer, dict):
        return ""
    parts = [
        offer.get("title"),
        offer.get("company"),
        offer.get("requirements"),
        offer.get("description_original"),
        offer.get("description"),
    ]
    return " ".join(clean_text(item, limit=12_000) for item in parts if item)


def _step_text(step: CreationStep) -> str:
    user_input = step.user_input if isinstance(step.user_input, dict) else {}
    parts: list[str] = []
    for key in ("text", "content", "draft"):
        value = user_input.get(key)
        if isinstance(value, str):
            parts.append(value)
    fields = user_input.get("fields")
    if isinstance(fields, dict):
        parts.extend(value for value in fields.values() if isinstance(value, str))
    for key in ("blocks", "paragraphs", "answers"):
        values = user_input.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, dict):
                    text = value.get("text") or value.get("content")
                    if isinstance(text, str):
                        parts.append(text)
    return "\n".join(parts)


def _replace_in_input(user_input: dict[str, Any], target: str, replacement: str) -> bool:
    changed = False

    def replace(value: str) -> str:
        nonlocal changed
        if target and target in value:
            changed = True
            return value.replace(target, replacement, 1)
        return value

    for key in ("text", "content", "draft"):
        if isinstance(user_input.get(key), str):
            user_input[key] = replace(user_input[key])
    fields = user_input.get("fields")
    if isinstance(fields, dict):
        for key, value in list(fields.items()):
            if isinstance(value, str):
                fields[key] = replace(value)
    for key in ("blocks", "paragraphs", "answers"):
        values = user_input.get(key)
        if isinstance(values, list):
            for index, value in enumerate(values):
                if isinstance(value, str):
                    values[index] = replace(value)
                elif isinstance(value, dict):
                    text_key = "text" if isinstance(value.get("text"), str) else "content"
                    if isinstance(value.get(text_key), str):
                        value[text_key] = replace(value[text_key])
    return changed


def _remove_from_input(user_input: dict[str, Any], target: str) -> bool:
    changed = False

    def remove(value: str) -> str:
        nonlocal changed
        if target and target in value:
            changed = True
            return value.replace(target, "", 1)
        return value

    for key in ("text", "content", "draft"):
        if isinstance(user_input.get(key), str):
            user_input[key] = remove(user_input[key])
    fields = user_input.get("fields")
    if isinstance(fields, dict):
        for key, value in list(fields.items()):
            if isinstance(value, str):
                fields[key] = remove(value)
    for key in ("blocks", "paragraphs", "answers"):
        values = user_input.get(key)
        if isinstance(values, list):
            for index, value in enumerate(values):
                if isinstance(value, str):
                    values[index] = remove(value)
                elif isinstance(value, dict):
                    text_key = "text" if isinstance(value.get("text"), str) else "content"
                    if isinstance(value.get(text_key), str):
                        value[text_key] = remove(value[text_key])
    return changed


def _append_text(user_input: dict[str, Any], text: str) -> None:
    current = user_input.get("text")
    if isinstance(current, str) and current.strip():
        user_input["text"] = f"{current.rstrip()}\n{text.strip()}"[:MAX_TEXT]
    else:
        user_input["text"] = text.strip()[:MAX_TEXT]


def _normalize_evidence(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if isinstance(item, str):
            text = _bounded_text(item, limit=1_200)
            identifier = f"proof-{index + 1}"
            payload = {"id": identifier, "text": text, "source": "contexte"}
        elif isinstance(item, dict):
            text = _bounded_text(
                item.get("text") or item.get("quote") or item.get("excerpt") or item.get("content"),
                limit=1_200,
            )
            identifier = clean_text(item.get("id"), limit=80) or f"proof-{index + 1}"
            payload = {
                "id": identifier,
                "text": text,
                "source": clean_text(item.get("source"), limit=160) or "contexte",
                "requirement": clean_text(item.get("requirement"), limit=300),
                "profile_field": clean_text(item.get("profile_field"), limit=80),
            }
        else:
            continue
        if not payload["text"] or identifier in seen:
            continue
        seen.add(identifier)
        normalized.append(payload)
    return normalized


def _normalize_requirements(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            text = clean_text(item, limit=300)
            if text:
                normalized.append({"text": text, "source": "contexte"})
        elif isinstance(item, dict):
            text = clean_text(item.get("text") or item.get("requirement"), limit=300)
            if text:
                normalized.append({"text": text, "source": clean_text(item.get("source"), limit=80) or "offre"})
    return normalized


def _normalize_required(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            text = clean_text(item, limit=300)
            if text:
                normalized.append({"requirement": text})
        elif isinstance(item, dict):
            label = clean_text(item.get("requirement") or item.get("label"), limit=300)
            if label:
                normalized.append(
                    {
                        "requirement": label,
                        **(
                            {"evidence_ids": [clean_text(value, limit=80) for value in item.get("evidence_ids") or []]}
                            if item.get("evidence_ids")
                            else {}
                        ),
                    }
                )
    return normalized


def _sanitize_json(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_TEXT]
    if isinstance(value, Path):
        return value.name
    if isinstance(value, dict):
        return {
            clean_text(key, limit=120): _sanitize_json(item, depth=depth + 1)
            for key, item in list(value.items())[:100]
            if clean_text(key, limit=120)
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_json(item, depth=depth + 1) for item in value[:100]]
    return clean_text(value, limit=500)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class SuggestionEngine:
    """Build contextual suggestions with the documented weighted formula."""

    def __init__(self, *, threshold: float = SHOW_THRESHOLD, limit: int = MAX_SUGGESTIONS) -> None:
        self.threshold = threshold
        self.limit = limit

    def score(self, components: dict[str, float]) -> float:
        total = sum(SCORE_WEIGHTS[key] * max(0.0, min(1.0, components.get(key, 0.0))) for key in SCORE_WEIGHTS)
        return round(max(0.0, min(1.0, total)), 2)

    def generate(
        self,
        session: CreationSession,
        step: CreationStep,
        *,
        context: CreationContext,
        preferences: CreationPreferences,
        now: str,
    ) -> list[Suggestion]:
        del now
        candidates: list[Suggestion] = []
        candidates.extend(self._proof_candidates(session, step, context, preferences))
        candidates.extend(self._gap_candidates(session, step, context, preferences))
        candidates.extend(self._reformulation_candidates(session, step, context, preferences))
        candidates.extend(self._structure_candidates(session, step, context, preferences))
        candidates.extend(self._removal_candidates(session, step))
        candidates.extend(self._text_candidates(session, step, preferences))
        accepted = _STEP_ACCEPTS.get(step.type, set())
        unique: dict[tuple[str, str], Suggestion] = {}
        for suggestion in candidates:
            if suggestion.type not in accepted:
                continue
            if suggestion.confidence < self.threshold:
                continue
            key = (suggestion.type, normalized_text(suggestion.content))
            previous = unique.get(key)
            if previous is None or suggestion.confidence > previous.confidence:
                unique[key] = suggestion
        ordered = sorted(
            unique.values(),
            key=lambda item: (-item.confidence, item.type, item.suggestion_id),
        )
        return ordered[: self.limit]

    def _make(
        self,
        session: CreationSession,
        step: CreationStep,
        *,
        type_: str,
        content: str,
        rationale: str,
        components: dict[str, float],
        evidence_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        alternatives: list[str] | None = None,
    ) -> Suggestion:
        confidence = self.score(components)
        digest_source = "|".join(
            [session.session_id, str(step.step_number), type_, normalized_text(content)]
        )
        suggestion_id = "sug-" + hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:12]
        return Suggestion(
            suggestion_id=suggestion_id,
            type=type_,  # type: ignore[arg-type]
            content=content[:4_000],
            rationale=rationale[:4_000],
            evidence_refs=list(dict.fromkeys(evidence_refs or [])),
            confidence=confidence,
            alternatives=list(alternatives or ["Conserver la formulation actuelle", "Reformuler manuellement"]),
            metadata=dict(metadata or {}),
            score_components={key: round(value, 3) for key, value in components.items()},
        )

    def _evidence_relevance(self, evidence_text: str, requirement: str) -> float:
        requirement_tokens = set(_tokens(requirement))
        if not requirement_tokens:
            return 0.6
        overlap = requirement_tokens & set(_tokens(evidence_text))
        return round(min(1.0, 0.55 + 0.45 * (len(overlap) / len(requirement_tokens))), 3)

    @staticmethod
    def _offer_alignment(requirement: str, offer_text: str) -> float:
        if not offer_text:
            return 0.5
        return 1.0 if normalized_text(requirement) and normalized_text(requirement) in normalized_text(offer_text) else 0.75

    def _proof_candidates(
        self,
        session: CreationSession,
        step: CreationStep,
        context: CreationContext,
        preferences: CreationPreferences,
    ) -> list[Suggestion]:
        offer_text = _offer_text(context.offer)
        suggestions: list[Suggestion] = []
        for item in context.evidence[:MAX_EVIDENCE]:
            text = clean_text(item.get("text"), limit=300)
            if not text:
                continue
            requirement = clean_text(item.get("requirement"), limit=300)
            source = clean_text(item.get("source"), limit=160) or "profil local"
            components = {
                "evidence_relevance": self._evidence_relevance(text, requirement) if requirement else 0.7,
                "offer_alignment": self._offer_alignment(requirement, offer_text) if requirement else 0.6,
                "user_preference_match": preference_match_score(preferences),
                "best_practice_score": 0.85,
            }
            if requirement:
                rationale = (
                    f"Cette preuve provient de {source} et correspond à l’exigence « {requirement} » de l’offre. "
                    "Elle est citée sans être réécrite : la citation reste vérifiable."
                )
                content = f"Attacher la preuve « {text} » pour l’exigence « {requirement} »."
            else:
                rationale = f"Cette preuve provient de {source}. L’attacher rend le bloc vérifiable."
                content = f"Attacher la preuve « {text} » ({source})."
            suggestions.append(
                self._make(
                    session,
                    step,
                    type_="proof",
                    content=content,
                    rationale=rationale,
                    components=components,
                    evidence_refs=[clean_text(item.get("id"), limit=80)],
                    metadata={
                        "evidence_id": clean_text(item.get("id"), limit=80),
                        "requirement": requirement,
                        "source": source,
                        "profile_field": clean_text(item.get("profile_field"), limit=80),
                    },
                    alternatives=["Reformuler sans modifier les faits", "Laisser ce bloc tel quel"],
                )
            )
        return suggestions

    def _gap_candidates(
        self,
        session: CreationSession,
        step: CreationStep,
        context: CreationContext,
        preferences: CreationPreferences,
    ) -> list[Suggestion]:
        offer_text = _offer_text(context.offer)
        suggestions: list[Suggestion] = []
        for gap in context.gaps[:MAX_GAPS]:
            requirement = clean_text(gap.get("requirement"), limit=300)
            if not requirement:
                continue
            components = {
                "evidence_relevance": 0.8,
                "offer_alignment": self._offer_alignment(requirement, offer_text),
                "user_preference_match": preference_match_score(preferences),
                "best_practice_score": 0.95,
            }
            suggestions.append(
                self._make(
                    session,
                    step,
                    type_="addition",
                    content=f"Documenter « {requirement} » avec une preuve vérifiable avant de l’ajouter.",
                    rationale=(
                        f"L’offre demande « {requirement} », mais aucune preuve locale ne l’étaye. "
                        "L’assistant ne l’invente pas : ajoutez une preuve réelle ou laissez le point absent."
                    ),
                    components=components,
                    metadata={
                        "requirement": requirement,
                        "gap": True,
                        "missing_keywords": list(gap.get("missing_keywords") or [])[:8],
                    },
                    alternatives=["Laisser le point absent", "Ajouter une preuve depuis le profil"],
                )
            )
        return suggestions

    def _reformulation_candidates(
        self,
        session: CreationSession,
        step: CreationStep,
        context: CreationContext,
        preferences: CreationPreferences,
    ) -> list[Suggestion]:
        text = _step_text(step)
        if not text:
            return []
        offer_text = _offer_text(context.offer)
        offer_normalized = normalized_text(offer_text)
        suggestions: list[Suggestion] = []
        for pattern, replacement in _REFORMULATIONS:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            target = match.group(0)
            replacement_normalized = normalized_text(replacement)
            if offer_normalized and replacement_normalized not in offer_normalized:
                if normalized_text(target) not in offer_normalized:
                    continue
            components = {
                "evidence_relevance": 0.7,
                "offer_alignment": 1.0 if replacement_normalized in offer_normalized else 0.5,
                "user_preference_match": preference_match_score(
                    preferences,
                    preferred_term=replacement,
                    avoided_term=target,
                ),
                "best_practice_score": 0.8,
            }
            rationale = (
                f"L’offre emploie « {replacement} ». La formulation actuelle « {target} » peut être alignée "
                "sans modifier le fait."
                if offer_normalized
                else f"« {replacement} » est plus direct que « {target} » et conserve le fait."
            )
            suggestions.append(
                self._make(
                    session,
                    step,
                    type_="reformulation",
                    content=replacement,
                    rationale=rationale,
                    components=components,
                    metadata={
                        "target": target,
                        "replacement": replacement,
                        "preferred_term": replacement,
                        "avoided_term": target,
                    },
                )
            )

        if preferences.active:
            for avoided, preferred in preferences.preferred_verbs.items():
                if not re.search(rf"(?<!\w){re.escape(avoided)}(?!\w)", text, flags=re.IGNORECASE):
                    continue
                replacement_normalized = normalized_text(preferred)
                components = {
                    "evidence_relevance": 0.65,
                    "offer_alignment": 0.6 if replacement_normalized not in offer_normalized else 1.0,
                    "user_preference_match": 1.0,
                    "best_practice_score": 0.7,
                }
                suggestions.append(
                    self._make(
                        session,
                        step,
                        type_="reformulation",
                        content=preferred,
                        rationale=(
                            f"Vous avez préféré « {preferred} » à « {avoided} » lors de vos décisions précédentes. "
                            "Cette préférence est appliquée sans changer le fait."
                        ),
                        components=components,
                        metadata={
                            "target": avoided,
                            "replacement": preferred,
                            "preferred_term": preferred,
                            "avoided_term": avoided,
                        },
                    )
                )
        return suggestions

    def _structure_candidates(
        self,
        session: CreationSession,
        step: CreationStep,
        context: CreationContext,
        preferences: CreationPreferences,
    ) -> list[Suggestion]:
        del context
        section_by_type = {
            "cv": ("Projets clés", "Expériences", "Ajoute une section « Projets clés » avant « Expériences » pour rendre les réalisations vérifiables."),
            "cover_letter": ("Preuves", "Conclusion", "Structure la lettre en trois blocs : accroche, preuves, projection."),
            "profile": ("Résultats vérifiables", "Expériences", "Ajoute une rubrique « Résultats vérifiables » pour rendre chaque fait comparable."),
            "application": ("Pièces jointes", "Export", "Ajoute une checklist des pièces jointes avant l’export."),
            "interview_prep": ("Contexte · Action · Résultat", "Conclusion", "Structure chaque réponse : contexte, action, résultat réel."),
        }
        section, before, content = section_by_type.get(session.creation_type, section_by_type["cv"])
        components = {
            "evidence_relevance": 0.7,
            "offer_alignment": 0.5,
            "user_preference_match": preference_match_score(preferences, section=section),
            "best_practice_score": 1.0,
        }
        suggestions = [
            self._make(
                session,
                step,
                type_="structure",
                content=content,
                rationale=(
                    "Cette structure est une bonne pratique de lecture recruteur : elle met les faits vérifiables "
                    "avant les développements et ne crée aucun contenu."
                ),
                components=components,
                metadata={"section": section, "section_before": before},
                alternatives=["Conserver l’ordre actuel", "Choisir un autre ordre"],
            )
        ]
        if preferences.active and preferences.section_order:
            preferred_section = preferences.section_order[0]
            suggestions.append(
                self._make(
                    session,
                    step,
                    type_="reorder",
                    content=f"Placer « {preferred_section} » en premier dans le document.",
                    rationale=(
                        f"Vous avez placé « {preferred_section} » en premier lors de vos sessions précédentes ; "
                        "cet ordre est réappliqué sans modifier le contenu."
                    ),
                    components={
                        "evidence_relevance": 0.75,
                        "offer_alignment": 0.4,
                        "user_preference_match": 1.0,
                        "best_practice_score": 0.8,
                    },
                    metadata={"section": preferred_section, "preferred_term": preferred_section},
                    alternatives=["Conserver l’ordre actuel"],
                )
            )
        return suggestions

    def _removal_candidates(self, session: CreationSession, step: CreationStep) -> list[Suggestion]:
        text = _step_text(step)
        if not text:
            return []
        suggestions: list[Suggestion] = []
        placeholder = _PLACEHOLDER_HINT.search(text)
        if placeholder:
            target = placeholder.group(0)
            suggestions.append(
                self._make(
                    session,
                    step,
                    type_="removal",
                    content=f"Supprimer le placeholder non résolu « {target} ».",
                    rationale=(
                        "Un placeholder visible enverrait un document inachevé au recruteur. "
                        "Remplacez-le par un fait vérifié ou supprimez-le."
                    ),
                    components={
                        "evidence_relevance": 1.0,
                        "offer_alignment": 0.3,
                        "user_preference_match": 0.5,
                        "best_practice_score": 0.8,
                    },
                    metadata={"target": target},
                    alternatives=["Remplacer par un fait vérifié"],
                )
            )
        seen: dict[str, str] = {}
        for line in text.splitlines():
            key = normalized_text(line)
            if len(key) < 24:
                continue
            if key in seen:
                suggestions.append(
                    self._make(
                        session,
                        step,
                        type_="removal",
                        content=f"Supprimer la ligne en double : « {clean_text(line, limit=120)} ».",
                        rationale="Cette ligne répète un fait déjà présent ; la supprimer rend le document plus dense.",
                        components={
                            "evidence_relevance": 0.9,
                            "offer_alignment": 0.3,
                            "user_preference_match": 0.5,
                            "best_practice_score": 0.7,
                        },
                        metadata={"target": line},
                        alternatives=["Fusionner les deux lignes"],
                    )
                )
                break
            seen[key] = line
        return suggestions

    def _text_candidates(
        self,
        session: CreationSession,
        step: CreationStep,
        preferences: CreationPreferences,
    ) -> list[Suggestion]:
        text = _step_text(step)
        suggestions: list[Suggestion] = []
        if text and len(text) < 80:
            suggestions.append(
                self._make(
                    session,
                    step,
                    type_="text",
                    content="Développe ce bloc avec un contexte, une action et un résultat réel (sans inventer de chiffre).",
                    rationale="Un bloc trop court ne permet pas au recruteur de vérifier le contexte ni le résultat.",
                    components={
                        "evidence_relevance": 0.8,
                        "offer_alignment": 0.5,
                        "user_preference_match": preference_match_score(preferences),
                        "best_practice_score": 0.8,
                    },
                    metadata={"detail_level": "detailed", "manual": True},
                    alternatives=["Laisser le bloc tel quel"],
                )
            )
        if text and len(text) > 900:
            suggestions.append(
                self._make(
                    session,
                    step,
                    type_="text",
                    content="Raccourcis ce bloc : garde le fait vérifiable et retire les répétitions.",
                    rationale="Un bloc trop long dilue la preuve ; la synthèse garde le fait et améliore la lecture.",
                    components={
                        "evidence_relevance": 0.75,
                        "offer_alignment": 0.4,
                        "user_preference_match": preference_match_score(preferences),
                        "best_practice_score": 0.8,
                    },
                    metadata={"detail_level": "synthetic", "manual": True},
                    alternatives=["Conserver la version détaillée"],
                )
            )
        if preferences.active and preferences.detail_level == "synthetic" and text and len(text) > 400:
            suggestions.append(
                self._make(
                    session,
                    step,
                    type_="text",
                    content="Version synthétique : garde un fait par ligne et supprime les développements secondaires.",
                    rationale="Vous préférez un niveau de détail synthétique dans vos documents.",
                    components={
                        "evidence_relevance": 0.8,
                        "offer_alignment": 0.4,
                        "user_preference_match": 1.0,
                        "best_practice_score": 0.8,
                    },
                    metadata={"detail_level": "synthetic", "manual": True},
                    alternatives=["Conserver le niveau détaillé"],
                )
            )
        if preferences.active and preferences.detail_level == "detailed" and text and len(text) < 500:
            suggestions.append(
                self._make(
                    session,
                    step,
                    type_="text",
                    content="Ajoute le contexte et le résultat vérifiable de cette expérience.",
                    rationale="Vous préférez un niveau de détail développé dans vos documents.",
                    components={
                        "evidence_relevance": 0.75,
                        "offer_alignment": 0.4,
                        "user_preference_match": 1.0,
                        "best_practice_score": 0.8,
                    },
                    metadata={"detail_level": "detailed", "manual": True},
                    alternatives=["Conserver la version courte"],
                )
            )
        if text and _INFORMAL_HINT.search(text):
            suggestions.append(
                self._make(
                    session,
                    step,
                    type_="text",
                    content="Remplace le ton informel par une formulation professionnelle adaptée au secteur.",
                    rationale="Le ton informel peut distraire du contenu ; la forme doit rester sobre et vérifiable.",
                    components={
                        "evidence_relevance": 0.6,
                        "offer_alignment": 0.4,
                        "user_preference_match": preference_match_score(preferences),
                        "best_practice_score": 0.9,
                    },
                    metadata={"tone": "formal", "manual": True},
                    alternatives=["Conserver le ton actuel"],
                )
            )
        return suggestions


class CreationAssistant:
    """Orchestrates sessions, suggestions, validation, learning and export."""

    def __init__(
        self,
        store: CreationStore,
        *,
        service: Any | None = None,
        export_dir: Path | None = None,
        clock: Callable[[], str] = utc_now,
        engine: SuggestionEngine | None = None,
    ) -> None:
        self.store = store
        self.service = service
        self.export_dir = Path(export_dir) if export_dir else self.store.directory / "exports"
        self._clock = clock
        self.engine = engine or SuggestionEngine()

    # ------------------------------------------------------------------ state

    def _now(self) -> str:
        return self._clock()

    def _load(self, session_id: str) -> CreationSession:
        return CreationSession.from_dict(self.store.get_session(session_id))

    def _save(self, session: CreationSession) -> dict[str, Any]:
        session.updated_at = self._now()
        session.total_steps = len(session.steps)
        return self.store.save_session(session)

    def create_session(
        self,
        *,
        user_id: str = "local-user",
        creation_type: str,
        target_offer_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        creation = choice(creation_type, CREATION_TYPES, "Type de création")
        identifier = new_session_id()
        now = self._now()
        specs = WIZARDS[creation]
        steps = [
            CreationStep(
                step_id=f"{identifier}-step-{index}",
                step_number=index,
                title=spec.title,
                description=spec.description,
                type=spec.type,  # type: ignore[arg-type]
                content=json.loads(json.dumps(spec.content)),
                validation=spec.validation,
                status="pending",
            )
            for index, spec in enumerate(specs, start=1)
        ]
        if not steps:
            raise UserFacingError("Le parcours de création demandé n’est pas disponible.")
        steps[0].status = "in_progress"
        steps[0].started_at = now
        session = CreationSession(
            session_id=identifier,
            user_id=_bounded_text(user_id, limit=80) or "local-user",
            creation_type=creation,  # type: ignore[arg-type]
            target_offer_id=_bounded_text(target_offer_id, limit=80) or None,
            status="draft",
            current_step=1,
            total_steps=len(steps),
            context=self._sanitize_context(context or {}, creation=creation, offer_id=target_offer_id),
            steps=steps,
            created_at=now,
            updated_at=now,
        )
        return self.store.save_session(session)

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self.store.get_session(session_id)

    def list_sessions(self, *, user_id: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_sessions(user_id=user_id)

    def delete_session(self, session_id: str) -> None:
        self.store.delete_session(session_id)

    def update_session(
        self,
        session_id: str,
        *,
        current_step: int | None = None,
        status: str | None = None,
        context: dict[str, Any] | None = None,
        step_number: int | None = None,
        user_input: dict[str, Any] | None = None,
        complete_step: bool = False,
        skip_step: bool = False,
    ) -> dict[str, Any]:
        session = self._load(session_id)
        now = self._now()
        if step_number is not None:
            self._save_step_input(
                session,
                step_number,
                user_input or {},
                complete=complete_step,
                skip=skip_step,
                now=now,
            )
        if context is not None:
            merged = dict(session.context)
            merged.update(self._sanitize_context(context, creation=session.creation_type, offer_id=session.target_offer_id))
            session.context = merged
        if current_step is not None:
            if current_step < 1 or current_step > len(session.steps):
                raise UserFacingError("Étape de création inconnue.")
            session.current_step = current_step
            target = session.steps[current_step - 1]
            if target.status == "pending":
                target.status = "in_progress"
                target.started_at = target.started_at or now
        if status is not None:
            if status not in {"draft", "reviewing", "validating", "finalized", "exported"}:
                raise UserFacingError("Statut de session inconnu.")
            session.status = status  # type: ignore[assignment]
            if status in {"finalized", "exported"}:
                session.completed_at = session.completed_at or now
        return self._save(session)

    def _save_step_input(
        self,
        session: CreationSession,
        step_number: int,
        user_input: dict[str, Any],
        *,
        complete: bool,
        skip: bool,
        now: str,
    ) -> CreationStep:
        if step_number < 1 or step_number > len(session.steps):
            raise UserFacingError("Étape de création inconnue.")
        step = session.steps[step_number - 1]
        if not isinstance(user_input, dict):
            raise UserFacingError("Le contenu de l’étape doit être un objet JSON.")
        step.user_input = self._sanitize_user_input(user_input)
        if skip:
            step.status = "skipped"
            step.completed_at = now
        elif complete:
            step.status = "completed"
            step.completed_at = now
        elif step.status == "pending":
            step.status = "in_progress"
            step.started_at = step.started_at or now
        if step.status in {"completed", "skipped"}:
            self._advance(session, now)
        return step

    def _advance(self, session: CreationSession, now: str) -> None:
        for step in session.steps:
            if step.status in {"completed", "skipped"}:
                continue
            session.current_step = step.step_number
            if step.status == "pending":
                step.status = "in_progress"
                step.started_at = step.started_at or now
            return
        session.current_step = session.total_steps
        if session.status in {"draft", "reviewing"}:
            session.status = "reviewing"

    def _sanitize_user_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        if len(payload) > 30:
            raise UserFacingError("Le contenu de l’étape contient trop de champs.")
        sanitized = _sanitize_json(payload)
        return sanitized if isinstance(sanitized, dict) else {}

    def _sanitize_context(self, payload: dict[str, Any], *, creation: str, offer_id: str | None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise UserFacingError("Le contexte de création doit être un objet JSON.")
        allowed = {
            "offer",
            "profile",
            "intake",
            "evidence",
            "gaps",
            "requirements",
            "required_evidence",
            "notes",
            "offer_id",
            "user_evidence",
            "section_order",
            "acknowledged_gaps",
        }
        sanitized: dict[str, Any] = {}
        for key, value in payload.items():
            name = clean_text(key, limit=80)
            if name not in allowed:
                continue
            sanitized[name] = _sanitize_json(value)
        sanitized.setdefault("offer_id", offer_id or "")
        sanitized.setdefault("creation_type", creation)
        return sanitized

    # ------------------------------------------------------------ suggestions

    def _context(self, session: CreationSession) -> CreationContext:
        context = session.context if isinstance(session.context, dict) else {}
        offer = context.get("offer") if isinstance(context.get("offer"), dict) else None
        profile = context.get("profile") if isinstance(context.get("profile"), dict) else None
        intake = context.get("intake") if isinstance(context.get("intake"), dict) else None
        if offer is None and self.service is not None and session.target_offer_id:
            try:
                offer = self.service.get_job(session.target_offer_id)
            except (KeyError, TypeError, ValueError, UserFacingError):
                offer = None
        if profile is None and self.service is not None:
            try:
                profile = self.service.get_profile()
            except (KeyError, TypeError, ValueError, UserFacingError):
                profile = None

        prepared: dict[str, Any] | None = None
        explicit_evidence = "evidence" in context or "user_evidence" in context
        evidence: list[dict[str, Any]]
        gaps: list[dict[str, Any]]
        requirements: list[dict[str, Any]]
        if offer is not None:
            prepared = prepare_application(profile or {}, intake or {}, offer)
            requirements = _normalize_requirements(prepared.get("requirements"))
            evidence = []
            if not explicit_evidence:
                evidence = [
                    {
                        "id": f"proof-{index}",
                        "text": clean_text(item.get("evidence"), limit=1_200),
                        "source": f"profile.{clean_text(item.get('profile_field'), limit=80) or 'profil'}",
                        "requirement": clean_text(item.get("requirement"), limit=300),
                        "profile_field": clean_text(item.get("profile_field"), limit=80),
                    }
                    for index, item in enumerate(prepared.get("matched_elements") or [], start=1)
                    if isinstance(item, dict) and clean_text(item.get("evidence"), limit=1_200)
                ]
            gaps = [
                {
                    "requirement": clean_text(item.get("requirement"), limit=300),
                    "missing_keywords": list(item.get("missing_keywords") or [])[:8],
                    "note": clean_text(item.get("note"), limit=600),
                }
                for item in prepared.get("unverified_elements") or []
                if isinstance(item, dict) and clean_text(item.get("requirement"), limit=300)
            ]
        else:
            requirements = _normalize_requirements(context.get("requirements"))
            evidence = []
            gaps = []

        if "evidence" in context or "user_evidence" in context:
            raw_evidence = [
                *(context.get("evidence") if isinstance(context.get("evidence"), list) else []),
                *(context.get("user_evidence") if isinstance(context.get("user_evidence"), list) else []),
            ]
            evidence = _normalize_evidence(raw_evidence)
        if "gaps" in context:
            raw_gaps = context.get("gaps")
            if isinstance(raw_gaps, list):
                gaps = [
                    {
                        "requirement": clean_text(item.get("requirement") if isinstance(item, dict) else item, limit=300),
                        "missing_keywords": list(item.get("missing_keywords") or [])[:8] if isinstance(item, dict) else [],
                    }
                    for item in raw_gaps
                    if clean_text(item.get("requirement") if isinstance(item, dict) else item, limit=300)
                ]
        if not requirements and offer is not None:
            requirements = _normalize_requirements(extract_requirements(offer))

        required = _normalize_required(context.get("required_evidence"))
        return CreationContext(
            offer=offer,
            profile=profile,
            evidence=evidence[:MAX_EVIDENCE],
            gaps=gaps[:MAX_GAPS],
            requirements=requirements,
            required_evidence=required,
            prepared=prepared,
        )

    def suggest(self, session_id: str, step_number: int | None = None) -> list[dict[str, Any]]:
        session = self._load(session_id)
        step = self._step(session, step_number)
        bundle = self._context(session)
        preferences = self.store.get_preferences(session.user_id)
        generated = self.engine.generate(
            session,
            step,
            context=bundle,
            preferences=preferences,
            now=self._now(),
        )
        treated = [item for item in step.suggestions if item.action != "defer"]
        treated_ids = {item.suggestion_id for item in treated}
        step.suggestions = treated + [item for item in generated if item.suggestion_id not in treated_ids]
        self._save(session)
        return [item.to_dict() for item in step.suggestions if item.action == "defer"]

    def _step(self, session: CreationSession, step_number: int | None = None) -> CreationStep:
        number = step_number if step_number is not None else session.current_step
        if number < 1 or number > len(session.steps):
            raise UserFacingError("Étape de création inconnue.")
        return session.steps[number - 1]

    def _find_suggestion(
        self, session: CreationSession, suggestion_id: str
    ) -> tuple[CreationStep, Suggestion]:
        identifier = clean_text(suggestion_id, limit=80)
        for step in session.steps:
            for suggestion in step.suggestions:
                if suggestion.suggestion_id == identifier:
                    return step, suggestion
        raise UserFacingError("Cette suggestion n’existe pas ou a expiré. Régénérez les suggestions de l’étape.")

    def accept_suggestion(
        self,
        session_id: str,
        suggestion_id: str,
        *,
        modification: str | None = None,
    ) -> dict[str, Any]:
        session = self._load(session_id)
        step, suggestion = self._find_suggestion(session, suggestion_id)
        if suggestion.action != "defer":
            raise UserFacingError("Cette suggestion a déjà été traitée.")
        now = self._now()
        applied = _bounded_text(modification, limit=4_000) if modification else suggestion.content
        self._apply_suggestion(session, step, suggestion, applied, modification is not None)
        suggestion.action = "modify" if modification else "accept"
        suggestion.applied_at = now
        suggestion.applied_by = "user"
        preferences = self.store.get_preferences(session.user_id)
        learn_from_decision(
            preferences,
            suggestion,
            "modify" if modification else "accept",
            session_id=session.session_id,
            now=now,
        )
        self.store.save_preferences(preferences)
        return {
            "session": self._save(session),
            "suggestion": suggestion.to_dict(),
            "preferences": preferences.to_dict(),
        }

    def reject_suggestion(
        self,
        session_id: str,
        suggestion_id: str,
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        session = self._load(session_id)
        step, suggestion = self._find_suggestion(session, suggestion_id)
        if suggestion.action != "defer":
            raise UserFacingError("Cette suggestion a déjà été traitée.")
        del step
        now = self._now()
        suggestion.action = "reject"
        suggestion.applied_at = now
        suggestion.applied_by = "user"
        if reason:
            suggestion.metadata["rejection_reason"] = _bounded_text(reason, limit=600)
        preferences = self.store.get_preferences(session.user_id)
        learn_from_decision(preferences, suggestion, "reject", session_id=session.session_id, now=now)
        self.store.save_preferences(preferences)
        return {
            "session": self._save(session),
            "suggestion": suggestion.to_dict(),
            "preferences": preferences.to_dict(),
        }

    def _apply_suggestion(
        self,
        session: CreationSession,
        step: CreationStep,
        suggestion: Suggestion,
        applied: str,
        modified: bool,
    ) -> None:
        user_input = dict(step.user_input or {})
        metadata = suggestion.metadata or {}
        if suggestion.type == "proof":
            references = list(user_input.get("evidence_refs") or [])
            identifier = clean_text(metadata.get("evidence_id"), limit=80)
            if identifier and identifier not in references:
                references.append(identifier)
            user_input["evidence_refs"] = references
        elif suggestion.type == "reformulation":
            target = clean_text(metadata.get("target"), limit=400)
            replacement = applied if modified else clean_text(metadata.get("replacement") or applied, limit=400)
            if not _replace_in_input(user_input, target, replacement):
                _append_text(user_input, replacement)
        elif suggestion.type == "removal":
            target = clean_text(metadata.get("target"), limit=400)
            _remove_from_input(user_input, target)
        elif suggestion.type in {"structure", "reorder"}:
            section = clean_text(metadata.get("section") or suggestion.content, limit=160)
            if section:
                ordered = [section] + [
                    item for item in list(session.context.get("section_order") or []) if item != section
                ]
                session.context["section_order"] = ordered[:50]
        elif suggestion.type == "addition":
            requirement = clean_text(metadata.get("requirement"), limit=300)
            acknowledged = list(session.context.get("acknowledged_gaps") or [])
            if requirement and requirement not in acknowledged:
                acknowledged.append(requirement)
            session.context["acknowledged_gaps"] = acknowledged[:50]
            if requirement:
                existing = user_input.get("acknowledged_gaps")
                values = existing if isinstance(existing, list) else []
                user_input["acknowledged_gaps"] = values + [requirement]
        elif suggestion.type == "text":
            target = clean_text(metadata.get("target"), limit=400)
            replacement = clean_text(metadata.get("replacement"), limit=4_000)
            if target and replacement and _replace_in_input(user_input, target, replacement):
                pass
            elif modified:
                _append_text(user_input, applied)
            else:
                step.content["accepted_guidance"] = suggestion.content
        step.user_input = user_input
        if step.status == "pending":
            step.status = "in_progress"
            step.started_at = step.started_at or self._now()

    # -------------------------------------------------------------- validation

    def validate(self, session_id: str, step_number: int | None = None) -> dict[str, Any]:
        session = self._load(session_id)
        bundle = self._context(session)
        preferences = self.store.get_preferences(session.user_id)
        if step_number is not None:
            report = validate_step(
                self._step(session, step_number),
                evidence=bundle.evidence,
                preferences=preferences,
                required_evidence=bundle.required_evidence,
                checked_at=self._now(),
            )
        else:
            report = validate_session(
                session,
                evidence=bundle.evidence,
                preferences=preferences,
                required_evidence=bundle.required_evidence,
                require_all_steps=True,
                checked_at=self._now(),
            )
            self._update_status_after_validation(session, report)
            session.context["last_validation"] = {
                "checked_at": report.checked_at,
                "score": report.score,
                "can_export": report.can_export,
                "counts": {
                    "blocking": len(report.blocking),
                    "warning": len(report.warnings),
                    "info": len(report.infos),
                },
            }
            self._save(session)
        return report.to_dict()

    @staticmethod
    def _update_status_after_validation(session: CreationSession, report: ValidationReport) -> None:
        if session.status == "exported":
            return
        if report.blocking:
            if session.status in {"finalized", "validating"}:
                session.status = "reviewing"
            return
        if all(step.status in {"completed", "skipped"} for step in session.steps[:-1]):
            session.status = "finalized"
            session.completed_at = session.completed_at or report.checked_at

    # ------------------------------------------------------------------ export

    def export_session(self, session_id: str, export_format: str = "json") -> Path:
        session = self._load(session_id)
        chosen = choice(export_format, EXPORT_FORMATS, "Format d’export")
        bundle = self._context(session)
        preferences = self.store.get_preferences(session.user_id)
        report = validate_session(
            session,
            evidence=bundle.evidence,
            preferences=preferences,
            required_evidence=bundle.required_evidence,
            require_all_steps=True,
            checked_at=self._now(),
        )
        if report.blocking:
            raise UserFacingError(f"Export bloqué : {describe_blockers(report)}")
        markdown = render_session_markdown(session, preferences=preferences)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.export_dir, 0o700)
        except OSError:
            pass
        filename = f"creation_{session.creation_type}_{session.session_id[:8]}.{chosen}"
        target = self.export_dir / filename
        title = f"{CREATION_LABELS.get(session.creation_type, 'Création')} — {session.session_id[:8]}"
        if chosen == "json":
            payload = {
                "exported_at": self._now(),
                "session": session.to_dict(),
                "validation": report.to_dict(),
                "preferences": preferences.to_dict(),
            }
            _atomic_write_text(target, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        elif chosen == "docx":
            write_docx(markdown=markdown, title=title, language="fr", target=target)
        else:
            write_pdf(markdown=markdown, title=title, language="fr", target=target)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        session.status = "exported"
        session.completed_at = session.completed_at or self._now()
        session.context["export"] = {
            "format": chosen,
            "filename": filename,
            "exported_at": session.completed_at,
            "validation_score": report.score,
        }
        record_session_use(preferences, session.session_id, now=self._now())
        self.store.save_preferences(preferences)
        self._save(session)
        return target

    # ------------------------------------------------------------- preferences

    def get_preferences(self, user_id: str = "local-user") -> dict[str, Any]:
        return self.store.get_preferences(user_id).to_dict()

    def update_preferences(self, patch: dict[str, Any], *, user_id: str = "local-user") -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise UserFacingError("Les préférences doivent être un objet JSON.")
        preferences = self.store.get_preferences(user_id)
        allowed = {
            "preferred_verbs",
            "avoided_terms",
            "technical_terms",
            "section_order",
            "detail_level",
            "tone",
        }
        unknown = sorted(set(patch) - allowed)
        if unknown:
            raise UserFacingError(f"Préférence inconnue : {', '.join(unknown[:3])}.")
        if "preferred_verbs" in patch:
            values = patch["preferred_verbs"]
            if not isinstance(values, dict):
                raise UserFacingError("Les verbes préférés doivent être un objet clé/valeur.")
            for source, target in values.items():
                source_text = _bounded_text(source, limit=120)
                target_text = _bounded_text(target, limit=120)
                if not source_text or not target_text:
                    raise UserFacingError("Un verbe préféré ne peut pas être vide.")
                preferences.preferred_verbs[source_text] = target_text
        if "avoided_terms" in patch:
            values = patch["avoided_terms"]
            if not isinstance(values, dict):
                raise UserFacingError("Les termes évités doivent être un objet clé/valeur.")
            for source, target in values.items():
                source_text = _bounded_text(source, limit=120)
                target_text = _bounded_text(target, limit=120)
                if not source_text or not target_text:
                    raise UserFacingError("Un terme évité ne peut pas être vide.")
                preferences.avoided_terms[source_text] = target_text
        if "technical_terms" in patch:
            values = patch["technical_terms"]
            if not isinstance(values, dict):
                raise UserFacingError("Les termes techniques doivent être un objet clé/valeur.")
            for source, target in values.items():
                source_text = _bounded_text(source, limit=120)
                target_text = _bounded_text(target, limit=120)
                if not source_text or not target_text:
                    raise UserFacingError("Un terme technique ne peut pas être vide.")
                preferences.technical_terms[source_text] = target_text
        if "section_order" in patch:
            values = patch["section_order"]
            if not isinstance(values, (list, tuple)):
                raise UserFacingError("L’ordre des sections doit être une liste.")
            ordered: list[str] = []
            for value in values:
                text = _bounded_text(value, limit=160)
                if text and text not in ordered:
                    ordered.append(text)
            preferences.section_order = ordered[:50]
        if "detail_level" in patch:
            preferences.detail_level = choice(
                patch["detail_level"],
                ("synthetic", "balanced", "detailed"),
                "Niveau de détail",
            )  # type: ignore[assignment]
        if "tone" in patch:
            preferences.tone = choice(patch["tone"], ("formal", "neutral", "direct"), "Tonalité")  # type: ignore[assignment]
        preferences.explicit = True
        preferences.updated_at = self._now()
        return self.store.save_preferences(preferences)


def render_session_markdown(
    session: CreationSession,
    *,
    preferences: CreationPreferences | None = None,
) -> str:
    """Render a clean, inert Markdown export of the session."""
    lines: list[str] = [f"# {CREATION_LABELS.get(session.creation_type, 'Création')}"]
    if session.target_offer_id:
        lines.append(f"Offre cible : {session.target_offer_id}")
    lines.append("")
    for step in session.steps:
        lines.append(f"## {step.step_number}. {step.title}")
        if step.status == "skipped":
            lines.append("_Étape ignorée explicitement._")
            lines.append("")
            continue
        user_input = step.user_input if isinstance(step.user_input, dict) else {}
        text = clean_text(user_input.get("text"), limit=MAX_TEXT)
        if text:
            lines.append(apply_preferences(text, preferences) if preferences is not None else text)
        fields = user_input.get("fields")
        if isinstance(fields, dict):
            for key, value in fields.items():
                cleaned = clean_text(value, limit=4_000) if isinstance(value, str) else ""
                if cleaned:
                    lines.append(f"**{clean_text(key, limit=120)}** : {cleaned}")
        for key in ("blocks", "paragraphs", "answers"):
            values = user_input.get(key)
            if not isinstance(values, list):
                continue
            for value in values:
                if isinstance(value, str) and value.strip():
                    lines.append(f"- {clean_text(value, limit=2_000)}")
                elif isinstance(value, dict):
                    item = clean_text(value.get("text") or value.get("content"), limit=2_000)
                    if item:
                        lines.append(f"- {item}")
        references = user_input.get("evidence_refs")
        if isinstance(references, list) and references:
            labels = ", ".join(clean_text(item, limit=80) for item in references if clean_text(item, limit=80))
            if labels:
                lines.append(f"_Preuves attachées : {labels}._")
        if not text and not fields and not user_input.get("blocks") and not user_input.get("paragraphs"):
            lines.append("_Étape non renseignée._")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
