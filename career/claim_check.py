"""Claim-level audit for application documents (SPEC-042 / CVBOOST-77).

A *claim* is a single sentence of a produced document (adapted CV, cover
letter, form answer).  Every claim must be demonstrable by an *approved*
proof (profile fact, approved evidence item, ...).  When it is not, the
claim receives one of five deterministic labels:

    supported        -- backed by an approved proof
    inflated         -- overstates a real fact ("expert", "senior", ...)
    out_of_context   -- a true number/fact reused in a different context
    invented         -- asserts specifics absent from every approved proof
    unverifiable     -- generic / weak / undocumented statement

The module is 100 % local and deterministic: no model, no network, no clock.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .models import clean_text, normalized_text

try:  # optional dependency on the approved-profile vocabulary
    from .requirements_fit import ApprovedProfile, ProfileFact, APPROVED_STATUSES
except Exception:  # pragma: no cover - defensive
    ApprovedProfile = None  # type: ignore[assignment]
    ProfileFact = None  # type: ignore[assignment]
    APPROVED_STATUSES = frozenset({"approved", "modified"})


CLAIM_LABELS: tuple[str, ...] = (
    "supported",
    "inflated",
    "out_of_context",
    "invented",
    "unverifiable",
)

# ---------------------------------------------------------------------------
# Exaggeration lexicon (versioned, editable through a local rules file).
# ---------------------------------------------------------------------------

_DEFAULT_INFLATED_TERMS: tuple[str, ...] = (
    "expert", "experte", "experts",
    "senior", "lead", "leader", "principal", "staff",
    "guru", "ninja", "rockstar", "wizard",
    "world-class", "world class", "outstanding", "exceptional", "exceptionnelle",
    "outstanding", "incontournable", "incontournables",
    "maitre", "maitrise totale", "mastery",
    # anglicisms "gonfles"
    "impactful", "scalable", "disruptive", "game-changer", "game changer",
    "owner", "ownership", "stakeholder", "thought leader",
    "best-in-class", "best in class", "cutting-edge", "cutting edge",
)

_DEFAULT_ANGlicisms: tuple[str, ...] = (  # kept for spelling tolerance
    "impactful", "scalable", "disruptive", "ownership", "stakeholder",
)

_RULES_CANDIDATE_PATHS: tuple[Path, ...] = (
    Path("career/dossier_quality_rules.json"),
    Path("career/claim_rules.json"),
    Path("career/exaggeration_rules.json"),
    Path("data/dossier_quality_rules.json"),
    Path("dossier_quality_rules.json"),
)


def _load_rules() -> dict[str, Any]:
    path_env = os.environ.get("DOSSIER_QUALITY_RULES") or os.environ.get("CLAIM_CHECK_RULES")
    candidates: list[Path] = []
    if path_env:
        candidates.append(Path(path_env))
    candidates.extend(_RULES_CANDIDATE_PATHS)
    for candidate in candidates:
        try:
            if candidate.is_file():
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(payload, Mapping if False else dict):
                    return payload
        except Exception:
            continue
    return {}


_RULES: dict[str, Any] = _load_rules()


def _rule_list(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = _RULES.get(key)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    return default


INFLATED_TERMS: tuple[str, ...] = _rule_list("inflated_terms", _DEFAULT_INFLATED_TERMS)
ANGlicisms: tuple[str, ...] = _rule_list("anglicisms", _DEFAULT_ANGlicisms)
ATS_MAX_REPEAT: int = int(_RULES.get("ats_max_repeat", 3) or 3)
MIN_YEARS_FOR_EXPERT: int = int(_RULES.get("min_years_for_expert", 5) or 5)


def _fold(text: str) -> str:
    return normalized_text(text)


def _tokens(text: str) -> set[str]:
    return {token for token in _fold(text).split() if len(token) >= 3}


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", text or ""))


def _has_specifics(text: str) -> bool:
    if _numbers(text):
        return True
    folded = _fold(text)
    quantity_words = {"million", "millions", "milliard", "milliards", "thousand", "thousands", "mille", "milliers", "cent", "cents"}
    if quantity_words & set(folded.split()):
        return True
    # capitalized words beyond sentence start
    words = re.findall(r"\b[A-ZÀ-Ÿ][a-zà-ÿ]{2,}\b", text or "")
    if len(words) >= 2:
        return True
    # technical tokens (long words) indicate specificity
    long_tokens = [tok for tok in folded.split() if len(tok) >= 7]
    if len(long_tokens) >= 2:
        return True
    return False


def _approved_facts(profile: Any) -> list[dict[str, Any]]:
    """Coerce any supported proof source into a list of fact dicts.

    Each fact dict has at least ``text`` (the approved excerpt) and may carry
    ``value``, ``quote``, ``status``, ``source``, ``fact_id``, ``category``.
    """
    facts: list[dict[str, Any]] = []

    if profile is None:
        return facts

    # ApprovedProfile
    if ApprovedProfile is not None and isinstance(profile, ApprovedProfile):
        for fact in profile.approved_facts():
            facts.append(_fact_to_dict(fact))
        if profile.profile_text:
            # also treat the whole profile text as a (low-trust) approved source
            pass
        return facts

    if isinstance(profile, Mapping):
        raw_facts = profile.get("facts")
        if isinstance(raw_facts, Sequence) and not isinstance(raw_facts, (str, bytes)):
            for index, item in enumerate(raw_facts):
                facts.append(_coerce_fact(item, index))
        else:
            # category sections
            for key, value in profile.items():
                if key in {"facts", "profile_text", "text", "document"}:
                    continue
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    for item in value:
                        facts.append(_coerce_fact(item, len(facts)))
        # profile text as a single approved source (weak) only if no facts
        if not facts and isinstance(profile.get("profile_text"), str):
            facts.append({"text": clean_text(profile.get("profile_text"), limit=20_000), "status": "approved"})
        if not facts and isinstance(profile.get("text"), str):
            facts.append({"text": clean_text(profile.get("text"), limit=20_000), "status": "approved"})
        return facts

    if isinstance(profile, Sequence) and not isinstance(profile, (str, bytes)):
        for index, item in enumerate(profile):
            facts.append(_coerce_fact(item, index))
        return facts

    if isinstance(profile, str):
        # treat the whole text as approved facts split by sentences
        for index, sentence in enumerate(_split_sentences(profile)):
            if sentence.strip():
                facts.append({"text": sentence.strip(), "status": "approved", "fact_id": f"fact_{index}"})
        return facts

    # object with approved_facts()
    if hasattr(profile, "approved_facts") and callable(profile.approved_facts):
        try:
            for index, fact in enumerate(profile.approved_facts()):
                facts.append(_fact_to_dict(fact))
            return facts
        except Exception:
            pass

    # object with .facts
    if hasattr(profile, "facts"):
        try:
            for index, fact in enumerate(profile.facts):
                facts.append(_coerce_fact(fact, index))
            return facts
        except Exception:
            pass

    return facts


def _fact_to_dict(fact: Any) -> dict[str, Any]:
    if hasattr(fact, "to_dict") and callable(fact.to_dict):
        try:
            payload = fact.to_dict()
            if isinstance(payload, Mapping):
                return dict(payload)
        except Exception:
            pass
    if isinstance(fact, Mapping):
        return dict(fact)
    # ProfileFact-like
    data: dict[str, Any] = {}
    for attr in ("fact_id", "id", "category", "value", "quote", "status", "source", "topic", "detail", "offset"):
        if hasattr(fact, attr):
            value = getattr(fact, attr)
            if value is not None:
                data[attr if attr != "fact_id" else "fact_id"] = value
    if "text" not in data:
        data["text"] = str(getattr(fact, "evidence", None) or getattr(fact, "value", None) or getattr(fact, "quote", None) or fact)
    if "quote" in data and "text" not in data:
        data["text"] = data["quote"]
    if "value" in data and "text" not in data:
        data["text"] = data["value"]
    return data


def _coerce_fact(item: Any, index: int) -> dict[str, Any]:
    if isinstance(item, str):
        return {"text": item, "status": "approved", "fact_id": f"fact_{index}"}
    if isinstance(item, Mapping):
        data = dict(item)
        if "text" not in data:
            data["text"] = str(data.get("quote") or data.get("value") or data.get("claim") or "")
        data.setdefault("status", "approved")
        data.setdefault("fact_id", f"fact_{index}")
        return data
    return _fact_to_dict(item)


def _split_sentences(text: str) -> list[str]:
    text = clean_text(text, limit=100_000)
    if not text:
        return []
    sentences: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # keep bullet lines as their own claim even without terminal punctuation
        for part in re.split(r"(?<=[.!?])\s+", line):
            part = part.strip(" \t-•*–—")
            if part:
                sentences.append(part)
    # fallback: if everything is one block with no punctuation, split by lines
    if len(sentences) == 1 and "\n" in text:
        sentences = [s.strip(" \t-•*–—") for s in text.splitlines() if s.strip()]
    return sentences


def _fact_text(fact: Mapping[str, Any]) -> str:
    return clean_text(
        fact.get("text") or fact.get("quote") or fact.get("value") or fact.get("claim") or "",
        limit=2_000,
    )


def _fact_tokens(fact: Mapping[str, Any]) -> set[str]:
    return _tokens(_fact_text(fact))


def _is_approved(fact: Mapping[str, Any]) -> bool:
    status = str(fact.get("status") or "approved").strip().lower()
    return status in APPROVED_STATUSES or status == ""


def _match_fact(claim: str, facts: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    claim_tokens = _tokens(claim)
    claim_numbers = _numbers(claim)
    if not claim_tokens:
        return None, 0.0
    best: tuple[float, dict[str, Any]] | None = None
    for fact in facts:
        if not _is_approved(fact):
            continue
        fact_text = _fact_text(fact)
        fact_tokens = _tokens(fact_text)
        if not fact_tokens:
            continue
        overlap = claim_tokens & fact_tokens
        # boost exact substring
        ratio = len(overlap) / max(1, len(claim_tokens))
        if fact_text and fact_text.lower() in claim.lower():
            ratio = max(ratio, 0.9)
        if claim.lower() in fact_text.lower():
            ratio = max(ratio, 0.8)
        # number-aware boost
        if claim_numbers and claim_numbers & _numbers(fact_text):
            ratio = max(ratio, min(0.75, ratio + 0.15))
        if best is None or ratio > best[0]:
            best = (ratio, fact)
    if best is None or best[0] < 0.15:
        return None, 0.0
    return best[1], best[0]


def _contains_inflated_term(text: str) -> str | None:
    folded = _fold(text)
    for term in INFLATED_TERMS:
        if _fold(term) in folded:
            return term
    return None


def _missing_proof_text(claim: str, fact: dict[str, Any] | None) -> str:
    if fact is None:
        return "Aucune preuve approuvée ne couvre cette affirmation."
    return ""


@dataclass
class Claim:
    """One audited claim (sentence) of a document."""

    text: str
    label: str
    confidence: float = 0.5
    evidence: str | None = None
    proof: str | None = None
    missing_proof: str | None = None
    missing_evidence: str | None = None
    suggestion: str = ""
    reformulation_suggestion: str = ""
    source_offset: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    # aliases set in __post_init__
    def __post_init__(self) -> None:
        if self.proof is None:
            self.proof = self.evidence
        if self.evidence is None:
            self.evidence = self.proof
        if self.missing_evidence is None:
            self.missing_evidence = self.missing_proof
        if self.missing_proof is None:
            self.missing_proof = self.missing_evidence
        if not self.reformulation_suggestion:
            self.reformulation_suggestion = self.suggestion
        if not self.suggestion:
            self.suggestion = self.reformulation_suggestion
        # alias attributes
        self.status = self.label
        self.verdict = self.label
        self.classification = self.label
        self.result = self.label

    @property
    def supported(self) -> bool:
        return self.label == "supported"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "sentence": self.text,
            "claim": self.text,
            "label": self.label,
            "status": self.label,
            "verdict": self.label,
            "classification": self.label,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "proof": self.proof,
            "missing_proof": self.missing_proof,
            "missing_evidence": self.missing_evidence,
            "suggestion": self.suggestion,
            "reformulation_suggestion": self.reformulation_suggestion,
            "source_offset": self.source_offset,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class ClaimCheckResult:
    """Result of a claim-level audit."""

    claims: list[Claim] = field(default_factory=list)
    items: list[Claim] = field(default_factory=list)
    findings: list[Claim] = field(default_factory=list)
    results: list[Claim] = field(default_factory=list)
    document: str = ""
    approved_facts: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    supported_count: int = 0
    inflated_count: int = 0
    out_of_context_count: int = 0
    invented_count: int = 0
    unverifiable_count: int = 0
    total: int = 0
    report: str = ""
    readable_report: str = ""
    text_report: str = ""
    readable: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        # keep aliases in sync
        if not self.items:
            self.items = self.claims
        if not self.findings:
            self.findings = self.claims
        if not self.results:
            self.results = self.claims
        self.total = len(self.claims)
        self._recompute_counts()
        if not self.report:
            self.report = self._build_report()
        if not self.readable_report:
            self.readable_report = self.report
        if not self.text_report:
            self.text_report = self.report
        if not self.readable:
            self.readable = self.report
        if not self.summary:
            self.summary = (
                f"{self.total} claim(s) : "
                f"{self.supported_count} supported, {self.inflated_count} inflated, "
                f"{self.out_of_context_count} out_of_context, "
                f"{self.invented_count} invented, {self.unverifiable_count} unverifiable."
            )

    def _recompute_counts(self) -> None:
        self.counts = {label: 0 for label in CLAIM_LABELS}
        for claim in self.claims:
            if claim.label in self.counts:
                self.counts[claim.label] += 1
        self.supported_count = self.counts.get("supported", 0)
        self.inflated_count = self.counts.get("inflated", 0)
        self.out_of_context_count = self.counts.get("out_of_context", 0)
        self.invented_count = self.counts.get("invented", 0)
        self.unverifiable_count = self.counts.get("unverifiable", 0)
        self.total = len(self.claims)

    def _build_report(self) -> str:
        lines: list[str] = []
        lines.append("=== RAPPORT CLAIM CHECK ===")
        lines.append(self.summary)
        lines.append("")
        for index, claim in enumerate(self.claims, 1):
            lines.append(f"{index}. [{claim.label.upper()}] « {claim.text} »")
            if claim.evidence:
                lines.append(f"   Preuve : {claim.evidence}")
            if claim.missing_proof:
                lines.append(f"   Preuve manquante : {claim.missing_proof}")
            if claim.suggestion:
                lines.append(f"   Suggestion : {claim.suggestion}")
            lines.append("")
        return "\n".join(lines).strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": [claim.to_dict() for claim in self.claims],
            "items": [claim.to_dict() for claim in self.claims],
            "findings": [claim.to_dict() for claim in self.claims],
            "results": [claim.to_dict() for claim in self.claims],
            "document": self.document,
            "approved_facts": self.approved_facts,
            "counts": self.counts,
            "supported_count": self.supported_count,
            "inflated_count": self.inflated_count,
            "out_of_context_count": self.out_of_context_count,
            "invented_count": self.invented_count,
            "unverifiable_count": self.unverifiable_count,
            "total": self.total,
            "report": self.report,
            "readable_report": self.readable_report,
            "text_report": self.text_report,
            "summary": self.summary,
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def __str__(self) -> str:
        return self.report


# Backwards/alias names
ClaimResult = Claim
ClaimReport = ClaimCheckResult
ClaimCheck = ClaimCheckResult


def _normalize_document(document: Any) -> str:
    if document is None:
        return ""
    if isinstance(document, str):
        return document
    if isinstance(document, Mapping):
        for key in ("text", "document", "content", "cv", "letter", "markdown", "body"):
            value = document.get(key)
            if isinstance(value, str) and value.strip():
                # concatenate multiple text fields if present
                parts = [clean_text(document.get(k), limit=20_000) for k in ("text", "document", "content", "cv", "letter", "markdown", "body", "answers") if isinstance(document.get(k), str)]
                joined = "\n".join(p for p in parts if p)
                if joined:
                    return joined
                return clean_text(value, limit=100_000)
        # answers dict
        answers = document.get("answers")
        if isinstance(answers, Mapping):
            return "\n".join(f"{k}: {v}" for k, v in answers.items() if v)
        return ""
    if hasattr(document, "text"):
        try:
            return clean_text(getattr(document, "text"), limit=100_000)
        except Exception:
            pass
    if hasattr(document, "to_dict"):
        try:
            return _normalize_document(document.to_dict())
        except Exception:
            pass
    return clean_text(document, limit=100_000)


def _normalize_profile(profile: Any, *, facts: Any = None, proofs: Any = None) -> Any:
    if facts is not None:
        return facts
    if proofs is not None:
        return proofs
    return profile


def _label_claim(claim: str, facts: list[dict[str, Any]], approved_texts: set[str]) -> tuple[str, dict[str, Any] | None, float]:
    claim_tokens = _tokens(claim)
    claim_numbers = _numbers(claim)
    inflated_term = _contains_inflated_term(claim)

    matched_fact, ratio = _match_fact(claim, facts)

    # approved texts set for substring checks
    [_fact_text(f) for f in facts if _is_approved(f)]

    # out of context: shares a number with a fact but poor overall match
    shared_number_fact = None
    for fact in facts:
        if not _is_approved(fact):
            continue
        if claim_numbers & _numbers(_fact_text(fact)):
            shared_number_fact = fact
            break

    if matched_fact is not None and ratio >= 0.45:
        # supported unless inflated term absent from the proof
        fact_text = _fact_text(matched_fact)
        if inflated_term and _fold(inflated_term) not in _fold(fact_text):
            return "inflated", matched_fact, max(0.5, ratio)
        # out of context if the claim adds specifics not in fact
        claim_tokens - _tokens(fact_text)
        numbers_extra = claim_numbers - _numbers(fact_text)
        if numbers_extra and len(numbers_extra) >= 1 and len(claim_tokens & _tokens(fact_text)) < 3:
            return "out_of_context", matched_fact, max(0.4, ratio)
        return "supported", matched_fact, max(0.6, ratio)

    # no strong match
    if shared_number_fact is not None and claim_numbers:
        # a true number reused in a different context
        return "out_of_context", shared_number_fact, 0.45

    if inflated_term is not None:
        return "inflated", None, 0.4

    # invented: specifics not present in any approved fact
    all_fact_tokens: set[str] = set()
    all_fact_numbers: set[str] = set()
    for fact in facts:
        if _is_approved(fact):
            all_fact_tokens |= _tokens(_fact_text(fact))
            all_fact_numbers |= _numbers(_fact_text(fact))
    specific_tokens = claim_tokens - all_fact_tokens
    has_number_not_in_facts = bool(claim_numbers - all_fact_numbers)
    if facts and (has_number_not_in_facts or (specific_tokens and len(specific_tokens) >= 2)):
        # but avoid calling generic sentences invented
        if _has_specifics(claim) and len(claim_tokens) >= 3:
            return "invented", None, 0.35

    if not facts:
        if inflated_term is not None:
            return "inflated", None, 0.4
        if _has_specifics(claim):
            return "invented", None, 0.3
        return "unverifiable", None, 0.2

    # generic / weak
    if len(claim_tokens) <= 3:
        return "unverifiable", None, 0.25
    if not (claim_tokens & all_fact_tokens):
        # no overlap at all but not obviously specific -> unverifiable
        if _has_specifics(claim):
            return "invented", None, 0.3
        return "unverifiable", None, 0.25
    return "unverifiable", None, 0.3


def _suggestion_for(label: str, claim: str, fact: dict[str, Any] | None, facts: list[dict[str, Any]]) -> str:
    approved = [f for f in facts if _is_approved(f)]
    if label == "supported":
        return "Conserver tel quel (preuve approuvée trouvée)."
    if label in ("inflated", "out_of_context", "invented", "unverifiable"):
        if approved:
            sample = "; ".join(clean_text(_fact_text(f), limit=80) for f in approved[:3])
            return (
                "Reformuler en s'appuyant sur les faits déjà approuvés : "
                + sample
                + ". Ne pas ajouter d'information non documentée."
            )
        return "Aucune preuve approuvée disponible — reformuler uniquement avec les faits du profil."
    return ""


def check_claims(
    document: Any = None,
    approved_profile: Any = None,
    *,
    profile: Any = None,
    facts: Any = None,
    proofs: Any = None,
    text: str | None = None,
    rules: Any = None,
    language: str = "fr",
    **kwargs: Any,
) -> ClaimCheckResult:
    if text is not None:
        document = text
    if "doc" in kwargs:
        document = kwargs.pop("doc")
    if "document_text" in kwargs:
        document = kwargs.pop("document_text")
    if "content" in kwargs and document is None:
        document = kwargs.pop("content")

    profile_source = _normalize_profile(
        approved_profile if approved_profile is not None else profile,
        facts=facts,
        proofs=proofs,
    )
    if profile_source is None and "approved_facts" in kwargs:
        profile_source = kwargs.pop("approved_facts")
    if profile_source is None and "evidence" in kwargs:
        profile_source = kwargs.pop("evidence")

    doc_text = _normalize_document(document)
    facts_list = _approved_facts(profile_source)

    # ATS keyword stuffing detection (parasitage) at claim level: mark claims
    # containing a term repeated > ATS_MAX_REPEAT as inflated.
    sentences = _split_sentences(doc_text)
    claims: list[Claim] = []
    offset = 0
    for sentence in sentences:
        pos = doc_text.find(sentence, offset)
        if pos < 0:
            pos = offset
        offset = pos + len(sentence)

        label, fact, confidence = _label_claim(sentence, facts_list, set())
        # ATS stuffing check
        tokens = sentence.split()
        from collections import Counter

        counts = Counter(t.lower().strip(".,;:!?") for t in tokens)
        stuffed = [tok for tok, c in counts.items() if c > ATS_MAX_REPEAT and len(tok) >= 4]
        if stuffed and label == "supported":
            label = "inflated"
            confidence = max(0.4, confidence)

        fact_text = _fact_text(fact) if isinstance(fact, Mapping) else (str(fact) if fact is not None else None)
        if label == "supported" and fact_text:
            evidence = fact_text
            missing = None
        else:
            evidence = fact_text if fact is not None else None
            missing = _missing_proof_text(sentence, fact) if label != "supported" else None

        suggestion = _suggestion_for(label, sentence, fact if isinstance(fact, Mapping) else None, facts_list)

        claims.append(
            Claim(
                text=sentence,
                label=label,
                confidence=round(float(confidence), 3),
                evidence=evidence if label == "supported" else (evidence if fact is not None else None),
                proof=evidence if fact is not None else None,
                missing_proof=missing,
                missing_evidence=missing,
                suggestion=suggestion,
                reformulation_suggestion=suggestion,
                source_offset=pos,
                metadata={"matched_fact": _fact_text(fact) if isinstance(fact, Mapping) else (str(fact) if fact else None)},
            )
        )

    result = ClaimCheckResult(
        claims=claims,
        document=doc_text,
        approved_facts=[_fact_to_dict(f) if not isinstance(f, Mapping) else dict(f) for f in facts_list],
    )
    return result


# Aliases
analyze_claims = check_claims
run_claim_check = check_claims
claim_check = check_claims
audit_claims = check_claims
verify_claims = check_claims
check_claim = check_claims
run_claims_check = check_claims
analyze_claim = check_claims
check_document_claims = check_claims
audit_document = check_claims
analyze = check_claims
check = check_claims
run = check_claims
evaluate = check_claims


def split_claims(text: Any) -> list[str]:
    return _split_sentences(_normalize_document(text))


def check_claim_text(*args: Any, **kwargs: Any) -> ClaimCheckResult:
    return check_claims(*args, **kwargs)
