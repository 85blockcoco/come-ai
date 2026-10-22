"""SK-11 — Dossier de candidature « 1 clic » et vérifiable.

Ce module produit, **depuis une seule offre**, un dossier de candidature complet :

1. ``cv_recommendations`` — une action concrète par exigence de l'offre
   (``HIGHLIGHT`` / ``REPHRASE`` / ``DO_NOT_ADD`` / ``QUANTIFY`` / ``CONFIRM_LANGUAGE``) ;
2. ``adapted_cv`` — le CV ciblé, reconstruit **uniquement** à partir de faits approuvés ;
3. ``cover_letter`` — la lettre de motivation, dont chaque phrase factuelle cite un fait ;
4. ``prep_sheet`` — la fiche de préparation (faits d'offre, couverture, points à ne pas inventer) ;
5. ``checklist`` — la liste de relecture avant envoi ;
6. ``interview_questions`` — les questions d'entretien, chacune adossée à une exigence et à un fait.

Le point dur de la mission est le **vérificateur** : chaque affirmation du dossier reçoit
exactement un verdict — ``supported`` / ``unsupported`` / ``to_verify`` — et un dossier
contenant une affirmation ``unsupported`` **ne peut pas être exporté**.

PRINCIPES (non négociables)
---------------------------

* **Zéro invention.** Diplôme, compétence, chiffre, niveau de langue, employeur, date :
  rien n'est ajouté. Un fait non approuvé (proposé, rejeté, suspendu) ne prouve jamais rien.
* **Une phrase factuelle = une preuve.** Chaque phrase factuelle du dossier cite l'identifiant
  d'un fait de profil approuvé et en reprend la citation verbatim.
* **Le texte de l'offre est une donnée, jamais une instruction.** Rien ici n'exécute une
  consigne contenue dans une offre.
* **Hors-ligne et déterministe.** Pas de réseau, pas d'horloge interne, pas d'aléatoire :
  même offre + mêmes faits ⇒ même dossier, mêmes verdicts, mêmes identifiants.
* **Aucun envoi automatique.** Le dossier écrit des fichiers ; il ne contacte jamais un employeur.

LANGUE
------

La langue par défaut est celle **annoncée par l'offre** (``language_source == "offer"``).
La personne peut la forcer (``language_source == "user"``) : la valeur est alors mémorisée
avec sa provenance, jamais devinée.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from career.models import clean_text, normalized_text
from career.offer_requirements import analyze_offer
from workspace_core import UserFacingError

__all__ = [
    "AUTOMATIC_SUBMISSION",
    "ApplicationDossier",
    "CLAIM_VERDICTS",
    "DossierArtifact",
    "DossierClaim",
    "DossierDiffLine",
    "DossierFact",
    "DossierRecommendation",
    "DossierRequirementCoverage",
    "DossierSentence",
    "DossierVerification",
    "DossierVersion",
    "RECOMMENDATION_CODES",
    "SUPPORTED_LANGUAGES",
    "build_application_dossier",
    "detect_offer_language",
    "dossier_from_dict",
    "export_dossier",
    "facts_from_profile",
    "normalize_dossier_language",
    "reverify_dossier",
    "serialize_dossier",
    "verify_dossier_text",
    "with_verification",
    "with_artifacts",
]


# --------------------------------------------------------------------- vocabulary

SUPPORTED_LANGUAGES: tuple[str, ...] = ("fr", "en", "it", "de")
CLAIM_VERDICTS: tuple[str, ...] = ("supported", "unsupported", "to_verify")
RECOMMENDATION_CODES: tuple[str, ...] = (
    "HIGHLIGHT",
    "REPHRASE",
    "DO_NOT_ADD",
    "QUANTIFY",
    "CONFIRM_LANGUAGE",
)

#: A dossier never submits anything by itself. The flag is explicit so that a
#: reader of the exported manifest can confirm it without reading the code.
AUTOMATIC_SUBMISSION: bool = False

#: Fact statuses that count as proof. Everything else is unknown, not proof.
USABLE_FACT_STATUSES: frozenset[str] = frozenset({"approved", "modified"})
KNOWN_FACT_STATUSES: frozenset[str] = frozenset(
    {"approved", "modified", "proposed", "rejected", "suspended"}
)

_LANGUAGE_ALIASES: dict[str, str] = {
    "fr": "fr",
    "français": "fr",
    "francais": "fr",
    "french": "fr",
    "fr-fr": "fr",
    "en": "en",
    "anglais": "en",
    "english": "en",
    "en-gb": "en",
    "en-us": "en",
    "it": "it",
    "italiano": "it",
    "italian": "it",
    "de": "de",
    "deutsch": "de",
    "allemand": "de",
    "german": "de",
}

_LANGUAGE_MARKERS: dict[str, tuple[str, ...]] = {
    "fr": ("français", "francais", "french", "france", "paris", "francaise"),
    "en": ("english", "anglais", "united kingdom", "london", "dublin", "amsterdam"),
    "it": ("italiano", "italian", "italy", "milan", "milano", "roma"),
    "de": ("deutsch", "german", "allemand", "germany", "berlin", "münchen", "munich"),
}


# ------------------------------------------------------------------- data model


@dataclass(frozen=True, slots=True)
class DossierFact:
    """One fact of the candidate profile, with its review status.

    ``value`` is the canonical value, ``quote`` the verbatim excerpt shown to
    the person.  Only facts whose status is in :data:`USABLE_FACT_STATUSES`
    can prove an affirmation.
    """

    fact_id: str
    value: str
    quote: str = ""
    category: str = "other"
    status: str = "approved"
    source: str = "profile"
    topic: str = ""
    detail: str = ""
    negated: bool = False

    @property
    def evidence(self) -> str:
        """The exact excerpt shown to the person (quote, else value)."""
        return self.quote or self.value

    @property
    def usable(self) -> bool:
        """True when this fact is approved and may prove an affirmation."""
        return self.status in USABLE_FACT_STATUSES and not self.negated

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "value": self.value,
            "quote": self.quote,
            "category": self.category,
            "status": self.status,
            "source": self.source,
            "topic": self.topic,
            "detail": self.detail,
            "negated": self.negated,
            "usable": self.usable,
        }


@dataclass(frozen=True, slots=True)
class DossierSentence:
    """One emitted sentence and the facts it was built from.

    The registry is what makes the verifier independent: a sentence that is
    *not* in the registry was written by the person and is checked from
    scratch against the approved facts.
    """

    artifact: str
    text: str
    fact_ids: tuple[str, ...] = ()
    kind: str = "claim"  # "claim" | "offer" | "structural"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "text": self.text,
            "fact_ids": list(self.fact_ids),
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class DossierClaim:
    """One affirmation and the verdict of the verifier."""

    claim_id: str
    artifact: str
    text: str
    verdict: str
    fact_id: str = ""
    quote: str = ""
    reason: str = ""

    @property
    def blocking(self) -> bool:
        """True when the affirmation is not proved and blocks the export."""
        return self.verdict == "unsupported"

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "artifact": self.artifact,
            "text": self.text,
            "verdict": self.verdict,
            "fact_id": self.fact_id,
            "quote": self.quote,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class DossierVerification:
    """The aggregated verdict of the verifier for one dossier."""

    claims: tuple[DossierClaim, ...] = ()
    supported_count: int = 0
    unsupported_count: int = 0
    to_verify_count: int = 0

    @property
    def export_allowed(self) -> bool:
        """The final export is refused as long as one affirmation is unsupported."""
        return self.unsupported_count == 0

    @property
    def blocking_claims(self) -> tuple[DossierClaim, ...]:
        return tuple(claim for claim in self.claims if claim.blocking)

    @property
    def pending_claims(self) -> tuple[DossierClaim, ...]:
        return tuple(claim for claim in self.claims if claim.verdict == "to_verify")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": [claim.to_dict() for claim in self.claims],
            "supported_count": self.supported_count,
            "unsupported_count": self.unsupported_count,
            "to_verify_count": self.to_verify_count,
            "export_allowed": self.export_allowed,
        }


@dataclass(frozen=True, slots=True)
class DossierRecommendation:
    """One concrete CV action for one offer requirement."""

    code: str
    requirement_id: str
    requirement: str
    instruction: str
    fact_id: str = ""
    quote: str = ""
    modality: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "requirement_id": self.requirement_id,
            "requirement": self.requirement,
            "instruction": self.instruction,
            "fact_id": self.fact_id,
            "quote": self.quote,
            "modality": self.modality,
        }


@dataclass(frozen=True, slots=True)
class DossierRequirementCoverage:
    """The link between one offer requirement and one profile fact."""

    requirement_id: str
    text: str
    modality: str
    category: str
    verdict: str
    fact_id: str = ""
    quote: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "text": self.text,
            "modality": self.modality,
            "category": self.category,
            "verdict": self.verdict,
            "fact_id": self.fact_id,
            "quote": self.quote,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class DossierDiffLine:
    """One line of the before/after comparison."""

    section: str
    kind: str  # "kept" | "added" | "removed"
    text: str
    fact_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "kind": self.kind,
            "text": self.text,
            "fact_id": self.fact_id,
        }


@dataclass(frozen=True, slots=True)
class DossierVersion:
    """One entry of the version history."""

    version: int
    language: str
    language_source: str
    supported_count: int = 0
    unsupported_count: int = 0
    to_verify_count: int = 0
    generated_at: str = ""
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "language": self.language,
            "language_source": self.language_source,
            "supported_count": self.supported_count,
            "unsupported_count": self.unsupported_count,
            "to_verify_count": self.to_verify_count,
            "generated_at": self.generated_at,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class DossierArtifact:
    """One deliverable of the dossier (Markdown body)."""

    key: str
    title: str
    body: str
    language: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "body": self.body,
            "language": self.language,
        }


@dataclass(frozen=True, slots=True)
class ApplicationDossier:
    """The complete, verifiable application dossier for one offer."""

    offer_id: str
    company: str
    title: str
    language: str
    language_source: str
    version: int
    artifacts: tuple[DossierArtifact, ...]
    recommendations: tuple[DossierRecommendation, ...]
    coverage: tuple[DossierRequirementCoverage, ...]
    diff: tuple[DossierDiffLine, ...]
    verification: DossierVerification
    history: tuple[DossierVersion, ...] = ()
    sentences: tuple[DossierSentence, ...] = ()
    facts: tuple[DossierFact, ...] = ()
    automatic_submission: bool = AUTOMATIC_SUBMISSION

    @property
    def export_allowed(self) -> bool:
        return self.verification.export_allowed

    def artifact(self, key: str) -> DossierArtifact | None:
        for item in self.artifacts:
            if item.key == key:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "offer_id": self.offer_id,
            "company": self.company,
            "title": self.title,
            "language": self.language,
            "language_source": self.language_source,
            "version": self.version,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "recommendations": [item.to_dict() for item in self.recommendations],
            "coverage": [item.to_dict() for item in self.coverage],
            "diff": [item.to_dict() for item in self.diff],
            "verification": self.verification.to_dict(),
            "history": [item.to_dict() for item in self.history],
            "sentences": [item.to_dict() for item in self.sentences],
            "facts": [fact.to_dict() for fact in self.facts],
            "automatic_submission": self.automatic_submission,
            "export_allowed": self.export_allowed,
        }


def serialize_dossier(dossier: ApplicationDossier) -> dict[str, Any]:
    """JSON-safe representation of a dossier (used by the local store)."""
    return dossier.to_dict()


def dossier_from_dict(payload: Mapping[str, Any]) -> ApplicationDossier:
    """Rebuild a dossier from its serialized form.

    The facts and the sentence registry are part of the payload: without them
    the verifier could no longer tell a generated sentence from a hand-written
    one, and the local store would keep a dossier it cannot re-check.
    """
    data = payload if isinstance(payload, Mapping) else {}
    facts = tuple(
        DossierFact(
            fact_id=clean_text(item.get("fact_id"), limit=160),
            value=clean_text(item.get("value"), limit=4_000),
            quote=clean_text(item.get("quote"), limit=4_000),
            category=clean_text(item.get("category"), limit=80) or "other",
            status=clean_text(item.get("status"), limit=40) or "approved",
            source=clean_text(item.get("source"), limit=160) or "profile",
            topic=clean_text(item.get("topic"), limit=400),
            detail=clean_text(item.get("detail"), limit=400),
            negated=bool(item.get("negated")),
        )
        for item in data.get("facts", [])
        if isinstance(item, Mapping)
    )
    sentences = tuple(
        DossierSentence(
            artifact=clean_text(item.get("artifact"), limit=80),
            text=clean_text(item.get("text"), limit=4_000),
            fact_ids=tuple(
                clean_text(fact_id, limit=160)
                for fact_id in item.get("fact_ids", [])
                if isinstance(fact_id, str)
            ),
            kind=clean_text(item.get("kind"), limit=40) or "claim",
        )
        for item in data.get("sentences", [])
        if isinstance(item, Mapping)
    )
    artifacts = tuple(
        DossierArtifact(
            key=clean_text(item.get("key"), limit=80),
            title=clean_text(item.get("title"), limit=200),
            body=clean_text(item.get("body"), limit=400_000),
            language=clean_text(item.get("language"), limit=8) or "fr",
        )
        for item in data.get("artifacts", [])
        if isinstance(item, Mapping)
    )
    recommendations = tuple(
        DossierRecommendation(
            code=clean_text(item.get("code"), limit=40),
            requirement_id=clean_text(item.get("requirement_id"), limit=80),
            requirement=clean_text(item.get("requirement"), limit=400),
            instruction=clean_text(item.get("instruction"), limit=600),
            fact_id=clean_text(item.get("fact_id"), limit=160),
            quote=clean_text(item.get("quote"), limit=4_000),
            modality=clean_text(item.get("modality"), limit=40),
        )
        for item in data.get("recommendations", [])
        if isinstance(item, Mapping)
    )
    coverage = tuple(
        DossierRequirementCoverage(
            requirement_id=clean_text(item.get("requirement_id"), limit=80),
            text=clean_text(item.get("text"), limit=400),
            modality=clean_text(item.get("modality"), limit=40),
            category=clean_text(item.get("category"), limit=60),
            verdict=clean_text(item.get("verdict"), limit=40),
            fact_id=clean_text(item.get("fact_id"), limit=160),
            quote=clean_text(item.get("quote"), limit=4_000),
            reason=clean_text(item.get("reason"), limit=600),
        )
        for item in data.get("coverage", [])
        if isinstance(item, Mapping)
    )
    diff = tuple(
        DossierDiffLine(
            section=clean_text(item.get("section"), limit=120),
            kind=clean_text(item.get("kind"), limit=20),
            text=clean_text(item.get("text"), limit=4_000),
            fact_id=clean_text(item.get("fact_id"), limit=160),
        )
        for item in data.get("diff", [])
        if isinstance(item, Mapping)
    )
    history = tuple(
        DossierVersion(
            version=int(item.get("version", 0)),
            language=clean_text(item.get("language"), limit=8),
            language_source=clean_text(item.get("language_source"), limit=16),
            supported_count=int(item.get("supported_count", 0)),
            unsupported_count=int(item.get("unsupported_count", 0)),
            to_verify_count=int(item.get("to_verify_count", 0)),
            generated_at=clean_text(item.get("generated_at"), limit=64),
            summary=clean_text(item.get("summary"), limit=600),
        )
        for item in data.get("history", [])
        if isinstance(item, Mapping)
    )
    verification_payload = data.get("verification")
    verification_payload = (
        verification_payload if isinstance(verification_payload, Mapping) else {}
    )
    claims = tuple(
        DossierClaim(
            claim_id=clean_text(item.get("claim_id"), limit=160),
            artifact=clean_text(item.get("artifact"), limit=80),
            text=clean_text(item.get("text"), limit=4_000),
            verdict=clean_text(item.get("verdict"), limit=40),
            fact_id=clean_text(item.get("fact_id"), limit=160),
            quote=clean_text(item.get("quote"), limit=4_000),
            reason=clean_text(item.get("reason"), limit=600),
        )
        for item in verification_payload.get("claims", [])
        if isinstance(item, Mapping)
    )
    verification = DossierVerification(
        claims=claims,
        supported_count=int(verification_payload.get("supported_count", 0)),
        unsupported_count=int(verification_payload.get("unsupported_count", 0)),
        to_verify_count=int(verification_payload.get("to_verify_count", 0)),
    )
    return ApplicationDossier(
        offer_id=clean_text(data.get("offer_id"), limit=120),
        company=clean_text(data.get("company"), limit=200),
        title=clean_text(data.get("title"), limit=200),
        language=clean_text(data.get("language"), limit=8) or "fr",
        language_source=clean_text(data.get("language_source"), limit=16) or "offer",
        version=int(data.get("version", 1)),
        artifacts=artifacts,
        recommendations=recommendations,
        coverage=coverage,
        diff=diff,
        verification=verification,
        history=history,
        sentences=sentences,
        facts=facts,
        automatic_submission=bool(data.get("automatic_submission", False)),
    )


# ------------------------------------------------------------------ text helpers


def _fold(value: Any) -> str:
    """Lowercase, strip accents, collapse whitespace — for comparisons only."""
    text = clean_text(value, limit=200_000).lower()
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", stripped).strip()


_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
        "in", "is", "it", "its", "of", "on", "or", "our", "that", "the", "their", "them",
        "they", "this", "to", "with", "you", "your", "will", "must", "can", "me", "my",
        "i", "am", "im",
        "au", "aux", "avec", "ce", "ces", "dans", "de", "des", "du", "elle", "en", "et",
        "il", "je", "la", "le", "les", "leur", "ma", "mes", "mon", "moi", "nos", "notre",
        "nous", "on", "ou", "par", "pas", "pour", "que", "qui", "sa", "ses", "son", "sur",
        "ta", "tes", "ton", "tu", "un", "une", "vos", "votre", "vous", "y",
        "a", "alle", "als", "am", "an", "auch", "auf", "aus", "bei", "bin", "bis", "das",
        "dass", "dem", "den", "der", "des", "die", "ein", "eine", "einer", "es", "für",
        "hat", "ich", "ihre", "im", "in", "ist", "mein", "meine", "mit", "nach", "oder",
        "sie", "sich", "sie", "und", "von", "vor", "zu", "zum", "zur",
        "ad", "al", "alla", "che", "chi", "con", "da", "del", "della", "delle", "di",
        "dove", "e", "gli", "ha", "hanno", "ho", "i", "il", "in", "la", "le", "lei", "lo",
        "ma", "mi", "mia", "mio", "nei", "nel", "non", "o", "per", "piu", "qual", "quale",
        "quando", "se", "sono", "su", "sul", "ti", "tra", "tu", "un", "una", "uno",
    }
)


def _content_tokens(value: Any) -> set[str]:
    """Significant tokens of a text (numbers are kept: they are claims too)."""
    folded = _fold(value)
    tokens: set[str] = set()
    for raw in re.findall(r"[a-z0-9+#.]+", folded):
        token = raw.strip(".")
        if not token or token in _STOPWORDS:
            continue
        if len(token) < 2 and not token.isdigit():
            continue
        tokens.add(token)
    return tokens


def _overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left:
        return 0.0
    shared = left & right
    if not shared:
        return 0.0
    return len(shared) / len(left)


def _normalize_sentence(value: Any) -> str:
    """Normalize a sentence so the registry and the splitter agree.

    Markdown emphasis and list markers are decoration, not content: the
    verifier must recognize the same sentence whether it was emitted as a
    bold heading, a bullet or a plain paragraph.
    """
    text = clean_text(value, limit=4_000).strip()
    text = re.sub(r"^[-*+]\s+(?:\[[ xX]\]\s*)?", "", text)
    text = re.sub(r"^\d+[.)]\s+", "", text).strip()
    while text.startswith("**") and text.endswith("**") and len(text) > 4:
        text = text[2:-2].strip()
    text = text.strip("*").strip("`").strip()
    return re.sub(r"\s+", " ", text)


def _sentences(text: Any) -> list[str]:
    """Split a Markdown body into checkable sentences.

    Headings, table rows and empty lines are not affirmations: they are
    structure.  Everything else is split into sentences so that a single
    unsupported sentence is reported on its own.
    """
    body = clean_text(text, limit=400_000)
    results: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("|") or line.startswith(">"):
            continue
        line = _normalize_sentence(line)
        if not line:
            continue
        for chunk in re.split(r"(?<=[.!?…])\s+(?=[A-ZÀ-ÖØ-Þ«\"])", line):
            candidate = _normalize_sentence(chunk)
            if candidate:
                results.append(candidate)
    return results


# ----------------------------------------------------------------------- facts


_CATEGORY_TO_SECTION: dict[str, str] = {
    "skill": "skills",
    "skills": "skills",
    "competence": "skills",
    "competencies": "skills",
    "tech": "skills",
    "technique": "skills",
    "experience": "experience",
    "work": "experience",
    "professional_experience": "experience",
    "project": "projects",
    "projects": "projects",
    "education": "education",
    "etudes": "education",
    "etude": "education",
    "diplome": "education",
    "diploma": "education",
    "diplomation": "education",
    "degree": "education",
    "language": "languages",
    "languages": "languages",
    "langues": "languages",
    "certification": "certifications",
    "certifications": "certifications",
    "date": "dates",
    "contact": "contact",
    "availability": "dates",
    "dispo": "dates",
    "mobility": "dates",
    "mobilite": "dates",
    "auth_travail": "dates",
    "work_authorization": "dates",
    "other": "other",
}

_SECTION_ORDER: tuple[str, ...] = (
    "summary",
    "experience",
    "projects",
    "education",
    "skills",
    "languages",
    "certifications",
    "dates",
    "other",
)


def _section_for(category: Any) -> str:
    key = normalized_text(category).replace(" ", "_").replace("-", "_")
    return _CATEGORY_TO_SECTION.get(key, "other")


def _fact_from_mapping(payload: Mapping[str, Any], *, index: int) -> DossierFact:
    """Build a fact from a plain mapping (SK-03 or SK-10 shape, or local)."""
    lowered = {str(key).lower(): value for key, value in payload.items()}

    def pick(*names: str) -> Any:
        for name in names:
            if name in lowered and lowered[name] not in (None, ""):
                return lowered[name]
        return ""

    value = clean_text(pick("value", "label", "text", "name", "fact"), limit=4_000)
    quote = clean_text(pick("quote", "excerpt", "source_text", "passage"), limit=4_000)
    evidence = pick("evidence")
    if not quote and isinstance(evidence, str):
        quote = clean_text(evidence, limit=4_000)
    elif not quote and evidence is not None:
        quote = clean_text(getattr(evidence, "quote", ""), limit=4_000)
    if not value:
        value = quote
    status = normalized_text(pick("status", "state", "review_status")).replace(" ", "_")
    if status not in KNOWN_FACT_STATUSES:
        status = "approved" if status == "" else "proposed"
    category = clean_text(pick("category", "kind", "type", "section"), limit=80) or "other"
    fact_id = clean_text(pick("fact_id", "id", "uid"), limit=160)
    if not fact_id:
        fact_id = f"fact_{index:04d}"
    return DossierFact(
        fact_id=fact_id,
        value=value,
        quote=quote or value,
        category=category,
        status=status,
        source=clean_text(pick("source", "origin", "source_document"), limit=160) or "profile",
        topic=clean_text(pick("topic", "detail", "note"), limit=400),
        detail=clean_text(pick("detail", "note", "meta"), limit=400),
        negated=bool(lowered.get("negated")),
    )


def _fact_from_object(payload: Any, *, index: int) -> DossierFact:
    """Build a fact from a dataclass-like object (SK-10 ``Fact``, SK-03 ``ProfileFact``)."""
    evidence = getattr(payload, "evidence", None)
    quote = ""
    if isinstance(evidence, str):
        quote = clean_text(evidence, limit=4_000)
    elif evidence is not None:
        quote = clean_text(getattr(evidence, "quote", ""), limit=4_000)
    value = clean_text(
        getattr(payload, "value", "") or getattr(payload, "label", "") or getattr(payload, "text", ""),
        limit=4_000,
    )
    if not value:
        value = quote
    return DossierFact(
        fact_id=clean_text(getattr(payload, "fact_id", "") or getattr(payload, "id", ""), limit=160)
        or f"fact_{index:04d}",
        value=value,
        quote=quote or value,
        category=clean_text(
            getattr(payload, "category", "") or getattr(payload, "kind", "") or "other", limit=80
        ),
        status=normalized_text(getattr(payload, "status", "approved")).replace(" ", "_")
        or "approved",
        source=clean_text(getattr(payload, "source", "") or "profile", limit=160),
        topic=clean_text(getattr(payload, "topic", "") or getattr(payload, "note", ""), limit=400),
        detail=clean_text(getattr(payload, "detail", ""), limit=400),
        negated=bool(getattr(payload, "negated", False)),
    )


def facts_from_profile(payload: Any) -> tuple[DossierFact, ...]:
    """Normalize any profile shape into a tuple of :class:`DossierFact`.

    Accepted inputs (all optional, none required) :

    * a mapping with a ``facts`` list — SK-10 ``CandidateProfile`` payload;
    * a mapping with a ``usable_facts`` list — SK-10 approved subset;
    * a mapping of section → list of strings — the local Career profile;
    * a sequence of mappings or strings — raw facts;
    * SK-03 ``ApprovedProfile`` / ``ProfileFact`` objects.

    A fact whose status is not approved never proves anything, but it is kept
    so the dossier can show what still waits for a decision.
    """
    if payload is None:
        return ()
    if isinstance(payload, DossierFact):
        return (payload,)
    if isinstance(payload, Mapping):
        for key in ("facts", "usable_facts", "approved_facts"):
            raw = payload.get(key)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                return facts_from_profile(raw)
        facts: list[DossierFact] = []
        index = 0
        for key, value in payload.items():
            if key in {"profile_text", "readiness", "updated_at"}:
                continue
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                continue
            section = _section_for(key)
            if section == "other":
                continue
            for item in value:
                if isinstance(item, str):
                    text = clean_text(item, limit=4_000)
                    if not text:
                        continue
                    facts.append(
                        DossierFact(
                            fact_id=f"fact_{index:04d}",
                            value=text,
                            quote=text,
                            category=section,
                            status="approved",
                            source="profile",
                        )
                    )
                else:
                    facts.append(_fact_from_object(item, index=index))
                index += 1
        return tuple(facts)
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        facts = []
        for index, item in enumerate(payload):
            if isinstance(item, DossierFact):
                facts.append(item)
            elif isinstance(item, Mapping):
                facts.append(_fact_from_mapping(item, index=index))
            elif isinstance(item, str):
                text = clean_text(item, limit=4_000)
                if text:
                    facts.append(
                        DossierFact(
                            fact_id=f"fact_{index:04d}",
                            value=text,
                            quote=text,
                            category="other",
                            status="approved",
                            source="profile",
                        )
                    )
            else:
                facts.append(_fact_from_object(item, index=index))
        return tuple(facts)
    return ()


# --------------------------------------------------------------------- language


def normalize_dossier_language(value: Any) -> str:
    """Return one supported language code, or raise a user-facing error."""
    raw = clean_text(value, limit=80).strip().lower()
    if not raw:
        raise UserFacingError("Choisis la langue du dossier : français, anglais, italien ou allemand.")
    language = _LANGUAGE_ALIASES.get(raw)
    if language is None:
        language = _LANGUAGE_ALIASES.get(re.split(r"[-_ ]+", raw)[0])
    if language is None:
        language = _LANGUAGE_ALIASES.get(normalized_text(raw))
    if language is None:
        raise UserFacingError("Choisis la langue du dossier : français, anglais, italien ou allemand.")
    return language


def detect_offer_language(offer: Mapping[str, Any]) -> tuple[str, str]:
    """Return ``(language, "offer")`` — the language announced by the offer.

    The offer is untrusted data: its language is only ever *detected*, never
    executed.  When nothing can be detected the French default applies (the
    Career workspace is French-first), and the person can always override it.
    """
    if not isinstance(offer, Mapping):
        return "fr", "offer"

    explicit = clean_text(offer.get("language") or offer.get("language_code"), limit=40)
    if explicit:
        normalized = _LANGUAGE_ALIASES.get(explicit.lower())
        if normalized:
            return normalized, "offer"

    structured = clean_text(offer.get("languages_required"), limit=600)
    detected = _first_language_marker(structured)
    if detected:
        return detected, "offer"

    corpus = " ".join(
        clean_text(offer.get(key), limit=8_000)
        for key in ("description_original", "requirements", "title")
    )
    detected = _first_language_marker(corpus)
    if detected:
        return detected, "offer"
    return "fr", "offer"


def _first_language_marker(text: Any) -> str | None:
    """Return the language whose marker appears **first** in the text.

    Position, not frequency: "German, English" announces a German posting whose
    description mentions English, while "English (Fluent), German" announces an
    English posting that also asks for German.
    """
    folded = _fold(text)
    if not folded:
        return None
    best_position: int | None = None
    best_language: str | None = None
    for language, markers in _LANGUAGE_MARKERS.items():
        for marker in markers:
            position = folded.find(marker)
            if position < 0:
                continue
            if best_position is None or position < best_position:
                best_position = position
                best_language = language
    return best_language


def _resolve_language(offer: Mapping[str, Any], requested: Any) -> tuple[str, str]:
    if requested is None or normalized_text(requested) == "":
        return detect_offer_language(offer)
    return normalize_dossier_language(requested), "user"


# ------------------------------------------------------------------ copy tables

_COPY: dict[str, dict[str, str]] = {
    "fr": {
        "dossier": "Dossier de candidature",
        "recommendations": "Recommandations CV",
        "cv": "CV adapté",
        "letter": "Lettre de motivation",
        "prep": "Fiche de préparation",
        "checklist": "Checklist avant envoi",
        "questions": "Questions d'entretien",
        "summary": "Profil ciblé",
        "experience": "Expérience",
        "projects": "Projets",
        "education": "Formation",
        "skills": "Compétences",
        "languages": "Langues",
        "certifications": "Certifications",
        "dates": "Informations complémentaires",
        "other": "Autres éléments approuvés",
        "language_line": "Langue du dossier : {language} (source : {source})",
        "language_user": "forcée par la personne",
        "language_offer": "langue annoncée par l'offre",
        "version_line": "Version du dossier : {version}",
        "no_auto_send": "Aucun envoi automatique : tu relis, puis tu envoies toi-même.",
        "summary_line": "Candidature au poste de {title} chez {company}{location}.",
        "documented_line": "Éléments documentés dans mon profil approuvé :",
        "cover_intro": "Bonjour,",
        "cover_claim": "- {value}",
        "cover_close": "Ce dossier ne contient que des faits appuyés par mon profil approuvé ; je complète et relis chaque point avant envoi.",
        "cover_available": "Je reste disponible pour un échange.",
        "cover_sign": "Cordialement,",
        "cover_object": "Objet : Candidature au poste de {title}",
        "prep_offer_facts": "Faits de l'offre à vérifier sur la source officielle",
        "prep_coverage": "Couverture des exigences de l'offre",
        "prep_gaps": "À ne pas inventer",
        "prep_talking": "Points de discussion",
        "prep_before": "Avant d'envoyer",
        "offer_fact": "Élément",
        "offer_value": "Valeur enregistrée",
        "offer_source": "Source",
        "requirement": "Exigence",
        "type": "Type",
        "verdict": "Verdict",
        "proof": "Preuve",
        "action": "Action",
        "instruction": "Consigne",
        "no_proof": "Aucune preuve approuvée",
        "pending_proof": "Preuve en attente d'approbation",
        "check_read": "Relis chaque phrase du CV et de la lettre : uniquement des faits exacts.",
        "check_language": "Vérifie la langue du dossier ({language}) et l'adresse du destinataire.",
        "check_confirm": "Confirme avant envoi : {text}",
        "check_fix": "Corrige ou prouve avant envoi : {text}",
        "check_send": "Aucun envoi automatique : tu envoies toi-même après relecture.",
        "question_supported": "Ton profil documente « {value} » : décris ce que tu as fait concrètement et le résultat obtenu.",
        "question_gap": "L'offre demande « {requirement} » et tu n'as pas de preuve approuvée : explique comment tu y répondrais, sans rien inventer.",
        "question_offer": "L'entreprise attend « {requirement} » : explique ce que tu as déjà mis en place pour y répondre.",
        "diff_title": "Comparaison avant / après",
        "diff_kept": "Conservé",
        "diff_added": "Ajouté",
        "diff_removed": "Retiré",
        "coverage_supported": "prouvé par un fait approuvé",
        "coverage_pending": "aucune preuve approuvée",
        "coverage_pending_fact": "un fait existe mais n'est pas approuvé",
        "coverage_contradicted": "un fait approuvé contredit cette exigence",
    },
    "en": {
        "dossier": "Application dossier",
        "recommendations": "CV recommendations",
        "cv": "Adapted CV",
        "letter": "Cover letter",
        "prep": "Preparation sheet",
        "checklist": "Checklist before sending",
        "questions": "Interview questions",
        "summary": "Target profile",
        "experience": "Experience",
        "projects": "Projects",
        "education": "Education",
        "skills": "Skills",
        "languages": "Languages",
        "certifications": "Certifications",
        "dates": "Additional information",
        "other": "Other approved elements",
        "language_line": "Dossier language: {language} (source: {source})",
        "language_user": "set by the person",
        "language_offer": "language announced by the offer",
        "version_line": "Dossier version: {version}",
        "no_auto_send": "No automatic submission: you review, then you send it yourself.",
        "summary_line": "Application for the {title} role at {company}{location}.",
        "documented_line": "Elements documented in my approved profile:",
        "cover_intro": "Hello,",
        "cover_claim": "- {value}",
        "cover_close": "This dossier contains only facts backed by my approved profile; I complete and re-read every point before sending.",
        "cover_available": "I remain available for any discussion.",
        "cover_sign": "Kind regards,",
        "cover_object": "Subject: Application for the {title} role",
        "prep_offer_facts": "Offer facts to verify on the official source",
        "prep_coverage": "Coverage of the offer requirements",
        "prep_gaps": "Never to invent",
        "prep_talking": "Talking points",
        "prep_before": "Before sending",
        "offer_fact": "Element",
        "offer_value": "Recorded value",
        "offer_source": "Source",
        "requirement": "Requirement",
        "type": "Type",
        "verdict": "Verdict",
        "proof": "Proof",
        "action": "Action",
        "instruction": "Instruction",
        "no_proof": "No approved proof",
        "pending_proof": "Proof awaiting approval",
        "check_read": "Re-read every sentence of the CV and the letter: accurate facts only.",
        "check_language": "Check the dossier language ({language}) and the recipient address.",
        "check_confirm": "Confirm before sending: {text}",
        "check_fix": "Fix or prove before sending: {text}",
        "check_send": "No automatic submission: you send it yourself after the review.",
        "question_supported": "Your profile documents “{value}”: describe what you did concretely and the result you achieved.",
        "question_gap": "The role asks for “{requirement}” and you have no approved evidence: explain how you would cover it, without inventing anything.",
        "question_offer": "The company expects “{requirement}”: explain what you have already put in place to answer it.",
        "diff_title": "Before / after comparison",
        "diff_kept": "Kept",
        "diff_added": "Added",
        "diff_removed": "Removed",
        "coverage_supported": "proved by an approved fact",
        "coverage_pending": "no approved proof",
        "coverage_pending_fact": "a fact exists but is not approved",
        "coverage_contradicted": "an approved fact contradicts this requirement",
    },
    "it": {
        "dossier": "Dossier di candidatura",
        "recommendations": "Raccomandazioni CV",
        "cv": "CV adattato",
        "letter": "Lettera di motivazione",
        "prep": "Scheda di preparazione",
        "checklist": "Checklist prima dell'invio",
        "questions": "Domande per il colloquio",
        "summary": "Profilo mirato",
        "experience": "Esperienza",
        "projects": "Progetti",
        "education": "Formazione",
        "skills": "Competenze",
        "languages": "Lingue",
        "certifications": "Certificazioni",
        "dates": "Informazioni complementari",
        "other": "Altri elementi approvati",
        "language_line": "Lingua del dossier: {language} (origine: {source})",
        "language_user": "imposta dalla persona",
        "language_offer": "lingua annunciata dall'offerta",
        "version_line": "Versione del dossier: {version}",
        "no_auto_send": "Nessun invio automatico: rileggi, poi invii tu stesso.",
        "summary_line": "Candidatura per la posizione di {title} presso {company}{location}.",
        "documented_line": "Elementi documentati nel mio profilo approvato:",
        "cover_intro": "Buongiorno,",
        "cover_claim": "- {value}",
        "cover_close": "Questo dossier contiene solo fatti supportati dal mio profilo approvato; completo e rileggo ogni punto prima dell'invio.",
        "cover_available": "Resto a disposizione per qualsiasi scambio utile.",
        "cover_sign": "Cordiali saluti,",
        "cover_object": "Oggetto: Candidatura per la posizione di {title}",
        "prep_offer_facts": "Fatti dell'offerta da verificare sulla fonte ufficiale",
        "prep_coverage": "Copertura dei requisiti dell'offerta",
        "prep_gaps": "Da non inventare mai",
        "prep_talking": "Punti di discussione",
        "prep_before": "Prima di inviare",
        "offer_fact": "Elemento",
        "offer_value": "Valore registrato",
        "offer_source": "Fonte",
        "requirement": "Requisito",
        "type": "Tipo",
        "verdict": "Verdetto",
        "proof": "Prova",
        "action": "Azione",
        "instruction": "Istruzione",
        "no_proof": "Nessuna prova approvata",
        "pending_proof": "Prova in attesa di approvazione",
        "check_read": "Rileggi ogni frase del CV e della lettera: solo fatti esatti.",
        "check_language": "Verifica la lingua del dossier ({language}) e l'indirizzo del destinatario.",
        "check_confirm": "Conferma prima dell'invio: {text}",
        "check_fix": "Correggi o prova prima dell'invio: {text}",
        "check_send": "Nessun invio automatico: invii tu stesso dopo la rilettura.",
        "question_supported": "Il tuo profilo documenta « {value} »: descrivi cosa hai fatto concretamente e il risultato ottenuto.",
        "question_gap": "L'offerta richiede « {requirement} » e non hai prove approvate: spiega come risponderesti, senza inventare nulla.",
        "question_offer": "L'azienda si aspetta « {requirement} »: spiega cosa hai già messo in atto per rispondere.",
        "diff_title": "Confronto prima / dopo",
        "diff_kept": "Conservato",
        "diff_added": "Aggiunto",
        "diff_removed": "Rimosso",
        "coverage_supported": "provato da un fatto approvato",
        "coverage_pending": "nessuna prova approvata",
        "coverage_pending_fact": "un fatto esiste ma non è approvato",
        "coverage_contradicted": "un fatto approvato contraddice questo requisito",
    },
    "de": {
        "dossier": "Bewerbungsdossier",
        "recommendations": "CV-Empfehlungen",
        "cv": "Angepasster Lebenslauf",
        "letter": "Anschreiben",
        "prep": "Vorbereitungsblatt",
        "checklist": "Checkliste vor dem Versand",
        "questions": "Interviewfragen",
        "summary": "Zielprofil",
        "experience": "Erfahrung",
        "projects": "Projekte",
        "education": "Ausbildung",
        "skills": "Kenntnisse",
        "languages": "Sprachen",
        "certifications": "Zertifikate",
        "dates": "Zusatzinformationen",
        "other": "Weitere freigegebene Angaben",
        "language_line": "Dossiersprache: {language} (Quelle: {source})",
        "language_user": "von der Person gesetzt",
        "language_offer": "von der Ausschreibung angekündigte Sprache",
        "version_line": "Dossier-Version: {version}",
        "no_auto_send": "Kein automatischer Versand: du prüfst und versendest selbst.",
        "summary_line": "Bewerbung auf die Position {title} bei {company}{location}.",
        "documented_line": "In meinem freigegebenen Profil belegte Elemente:",
        "cover_intro": "Guten Tag,",
        "cover_claim": "- {value}",
        "cover_close": "Dieses Dossier enthält nur Fakten aus meinem freigegebenen Profil; ich vervollständige und prüfe jeden Punkt vor dem Versand.",
        "cover_available": "Ich stehe für ein konkretes Gespräch gerne zur Verfügung.",
        "cover_sign": "Mit freundlichen Grüßen",
        "cover_object": "Betreff: Bewerbung auf die Position {title}",
        "prep_offer_facts": "Angaben der Ausschreibung, die auf der offiziellen Quelle zu prüfen sind",
        "prep_coverage": "Abdeckung der Anforderungen der Ausschreibung",
        "prep_gaps": "Niemals erfinden",
        "prep_talking": "Gesprächspunkte",
        "prep_before": "Vor dem Versand",
        "offer_fact": "Element",
        "offer_value": "Erfasster Wert",
        "offer_source": "Quelle",
        "requirement": "Anforderung",
        "type": "Typ",
        "verdict": "Urteil",
        "proof": "Beleg",
        "action": "Aktion",
        "instruction": "Anweisung",
        "no_proof": "Kein freigegebener Beleg",
        "pending_proof": "Beleg wartet auf Freigabe",
        "check_read": "Prüfe jeden Satz im Lebenslauf und im Anschreiben: nur korrekte Fakten.",
        "check_language": "Prüfe die Dossiersprache ({language}) und die Anschrift des Empfängers.",
        "check_confirm": "Vor dem Versand bestätigen: {text}",
        "check_fix": "Vor dem Versand korrigieren oder belegen: {text}",
        "check_send": "Kein automatischer Versand: du versendest selbst nach der Prüfung.",
        "question_supported": "Dein Profil belegt „{value}“: beschreibe, was du konkret getan hast und welches Ergebnis du erzielt hast.",
        "question_gap": "Die Stelle verlangt „{requirement}“ und du hast keinen freigegebenen Beleg: erkläre, wie du darauf eingegst, ohne etwas zu erfinden.",
        "question_offer": "Das Unternehmen erwartet „{requirement}“: erkläre, was du bereits dafür umgesetzt hast.",
        "diff_title": "Vergleich vorher / nachher",
        "diff_kept": "Beibehalten",
        "diff_added": "Hinzugefügt",
        "diff_removed": "Entfernt",
        "coverage_supported": "durch einen freigegebenen Beleg nachgewiesen",
        "coverage_pending": "kein freigegebener Beleg",
        "coverage_pending_fact": "ein Beleg existiert, ist aber nicht freigegeben",
        "coverage_contradicted": "ein freigegebener Beleg widerspricht dieser Anforderung",
    },
}


_OFFER_ROW_LABELS: dict[str, tuple[str, str, str, str, str, str]] = {
    "fr": ("Entreprise", "Poste", "Lieu", "Date limite", "Langues demandées", "Éligibilité"),
    "en": ("Company", "Role", "Location", "Deadline", "Languages required", "Eligibility"),
    "it": ("Azienda", "Ruolo", "Sede", "Scadenza", "Lingue richieste", "Idoneità"),
    "de": ("Unternehmen", "Position", "Ort", "Frist", "Geforderte Sprachen", "Eignung"),
}


# ------------------------------------------------------- assertion classification
#: Markers of a *candidate* assertion: a sentence that claims something about
#: the person's own background.  A digit counts too: a number is a claim.
_CLAIM_MARKERS: tuple[str, ...] = (
    "j'ai", "j'ai", "j'", "je ", "je suis", "mon ", "ma ", "mes ", "moi",
    "i have", "i've", "i am", "i'm", "i ", "my ", "me ",
    "ho ", "che ho", "mia ", "mio ", "la mia", "le mie",
    "ich habe", "ich bin", "ich kenne", "meine ", "mein ",
    "degree", "diploma", "diplôme", "diplome", "laurea", "abschluss", "studium",
    "language level", "niveau", "livello", "sprachkenntnisse", "kenntnisse",
    "experience", "expérience", "esperienza", "erfahrung",
    "mastery", "maîtrise", "maitrise", "padronanza", "meisterung", "mastered",
    "fluent", "courant", "avanzato", "fortgeschritten",
    "certified", "expert", "specialist", "specialiste", "spreche", "parlo",
)

#: Markers of an *offer-side* statement: about the role, not about the person.
_OFFER_MARKERS: tuple[str, ...] = (
    "applying for", "i am applying", "candidate for",
    "candidature au poste", "candidature chez", "je candidate", "poste de", "poste chez",
    "candidatura per", "mi candido", "posizione di", "presso",
    "bewerbung auf", "ich bewerbe mich", "position bei", "stelle bei",
    "the role", "the company", "the offer", "your team", "votre entreprise", "l'offre",
    "l'offerta", "das unternehmen", "die stelle", "die ausschreibung",
)


def _is_offer_statement(sentence: str) -> bool:
    folded = _fold(sentence)
    return any(_fold(marker) in folded for marker in _OFFER_MARKERS)


def _is_candidate_assertion(sentence: str) -> bool:
    """True when the sentence asserts something about the person's background."""
    if _is_offer_statement(sentence):
        return False
    folded = _fold(sentence)
    if any(marker in folded for marker in _CLAIM_MARKERS):
        return True
    return bool(re.search(r"\d", sentence))


def _fact_covers_sentence(fact: DossierFact, sentence: str) -> bool:
    """True when the fact actually proves the sentence (not merely relates to it)."""
    haystack = _fold(sentence)
    for needle in (fact.value, fact.quote):
        folded = _fold(needle)
        if folded and folded in haystack:
            return True
    sentence_tokens = _content_tokens(sentence)
    if not sentence_tokens:
        return False
    fact_tokens = _content_tokens(fact.evidence) | _content_tokens(fact.value)
    shared = sentence_tokens & fact_tokens
    if not shared:
        return False
    return len(shared) >= max(1, math.ceil(0.5 * len(sentence_tokens)))


def _best_fact(sentence: str, facts: Iterable[DossierFact]) -> DossierFact | None:
    """The approved fact that proves the sentence best, if any."""
    sentence_tokens = _content_tokens(sentence)
    best: DossierFact | None = None
    best_score = 0.0
    for fact in facts:
        if not fact.usable:
            continue
        fact_tokens = _content_tokens(fact.evidence) | _content_tokens(fact.value)
        score = _overlap_ratio(sentence_tokens, fact_tokens)
        if score > best_score:
            best = fact
            best_score = score
    if best is None:
        return None
    return best if _fact_covers_sentence(best, sentence) else None


# ------------------------------------------------------------------- verifier


def verify_dossier_text(
    artifact_key: str,
    text: Any,
    facts: Sequence[DossierFact],
    sentences: Sequence[DossierSentence] = (),
) -> list[DossierClaim]:
    """Verify the affirmations of one artifact body.

    Registered sentences (emitted by the generator) are checked against the
    facts they cite.  A sentence the person added by hand is checked from
    scratch against the approved facts: an unsupported candidate assertion is
    reported as ``unsupported`` and blocks the final export.
    """
    registry = {
        _normalize_sentence(sentence.text): sentence
        for sentence in sentences
        if sentence.artifact == artifact_key
    }
    by_id = {fact.fact_id: fact for fact in facts}
    claims: list[DossierClaim] = []
    for index, sentence in enumerate(_sentences(text)):
        registered = registry.get(sentence)
        if registered is not None:
            verdict, fact_id, quote, reason = _classify_registered(sentence, registered, by_id)
            if verdict is None:
                continue
        else:
            verdict, fact_id, quote, reason = _classify_manual(sentence, facts)
            if verdict is None:
                continue
        claims.append(
            DossierClaim(
                claim_id=f"{artifact_key}:{index:03d}",
                artifact=artifact_key,
                text=sentence,
                verdict=verdict,
                fact_id=fact_id,
                quote=quote,
                reason=reason,
            )
        )
    return claims


def _classify_registered(
    sentence: str,
    registered: DossierSentence,
    facts: Mapping[str, DossierFact],
) -> tuple[str | None, str, str, str]:
    if registered.kind != "claim":
        # Offer-side and structural sentences are not affirmations about the
        # person: they are not claims at all.
        return None, "", "", ""
    cited = [facts[fact_id] for fact_id in registered.fact_ids if fact_id in facts]
    if not cited:
        return "unsupported", "", "", (
            "Le fait cité n'existe plus dans le profil : l'affirmation n'est plus prouvée."
        )
    usable = [fact for fact in cited if fact.usable]
    if not usable:
        pending = ", ".join(sorted({fact.fact_id for fact in cited}))
        return "to_verify", cited[0].fact_id, cited[0].evidence, (
            f"Fait non approuvé ({pending}) : rien n'est prouvé tant qu'il n'est pas approuvé."
        )
    for fact in usable:
        if _fact_covers_sentence(fact, sentence):
            return "supported", fact.fact_id, fact.evidence, "Fait approuvé cité à l'identique."
    return "unsupported", usable[0].fact_id, usable[0].evidence, (
        "Le fait cité ne prouve pas cette phrase."
    )


def _classify_manual(
    sentence: str, facts: Sequence[DossierFact]
) -> tuple[str | None, str, str, str]:
    # A sentence the person wrote by hand is proved exactly like a generated
    # one: an approved fact that covers it is enough.
    fact = _best_fact(sentence, facts)
    if fact is not None:
        return "supported", fact.fact_id, fact.evidence, "Fait approuvé retrouvé dans la phrase."
    if not _is_candidate_assertion(sentence):
        return "to_verify", "", "", "Phrase ajoutée à la main : à relire."
    return "unsupported", "", "", (
        "Affirmation sans fait de profil approuvé : l'export final est bloqué."
    )


# ------------------------------------------------------------------- coverage


def _cover_requirements(
    requirements: Sequence[Mapping[str, Any]],
    facts: Sequence[DossierFact],
) -> tuple[DossierRequirementCoverage, ...]:
    """Link every offer requirement to the profile facts that can prove it.

    A requirement with no approved proof is ``to_verify`` — never a reason to
    claim the candidate does not have it.  A negated approved fact that
    matches is ``contradicted``: the person must be told.
    """
    coverage: list[DossierRequirementCoverage] = []
    for record in requirements:
        text = clean_text(record.get("text"), limit=400)
        if not text:
            continue
        requirement_id = clean_text(record.get("id"), limit=80)
        modality = clean_text(record.get("modality"), limit=40) or "unknown"
        category = clean_text(record.get("category"), limit=60) or "other"
        tokens = _content_tokens(text)
        best_fact: DossierFact | None = None
        best_ratio = 0.0
        pending_fact: DossierFact | None = None
        for fact in facts:
            fact_tokens = _content_tokens(fact.evidence) | _content_tokens(fact.value)
            ratio = _overlap_ratio(tokens, fact_tokens)
            if ratio <= 0:
                continue
            if fact.usable:
                if ratio > best_ratio:
                    best_fact = fact
                    best_ratio = ratio
            elif pending_fact is None and fact.status == "proposed":
                pending_fact = fact
        if best_fact is not None and best_ratio >= 0.34:
            verdict = "supported"
            fact_id = best_fact.fact_id
            quote = best_fact.evidence
            reason = "prouvé par un fait approuvé"
        elif best_fact is not None and best_ratio > 0:
            verdict = "to_verify"
            fact_id = best_fact.fact_id
            quote = best_fact.evidence
            reason = "correspondance partielle : à relire"
        elif pending_fact is not None:
            verdict = "to_verify"
            fact_id = pending_fact.fact_id
            quote = pending_fact.evidence
            reason = "un fait existe mais n'est pas approuvé"
        else:
            verdict = "to_verify"
            fact_id = ""
            quote = ""
            reason = "aucune preuve approuvée"
        coverage.append(
            DossierRequirementCoverage(
                requirement_id=requirement_id,
                text=text,
                modality=modality,
                category=category,
                verdict=verdict,
                fact_id=fact_id,
                quote=quote,
                reason=reason,
            )
        )
    return tuple(coverage)


def _requirement_matches_language(text: str) -> bool:
    folded = _fold(text)
    return any(
        marker in folded
        for marker in ("language", "anglais", "français", "english", "italian", "italiano", "german", "deutsch", "sprache", "lingua")
    )


def _requirement_has_number(text: str) -> bool:
    return bool(re.search(r"\d", text))


def _recommendation_code(
    coverage: DossierRequirementCoverage,
    fact: DossierFact | None,
) -> str:
    if coverage.verdict != "supported" or fact is None:
        return "DO_NOT_ADD"
    text = coverage.text
    if _requirement_has_number(text) and not re.search(r"\d", fact.evidence):
        return "QUANTIFY"
    if _requirement_matches_language(text) and not re.search(
        r"\b(c1|c2|a2|b1|b2|advanced|intermediate|fluent|native|avancé|intermédiaire|courant|natif|fortgeschritten|fließend)\b",
        _fold(fact.evidence),
    ):
        return "CONFIRM_LANGUAGE"
    requirement_tokens = _content_tokens(text)
    fact_tokens = _content_tokens(fact.evidence) | _content_tokens(fact.value)
    if requirement_tokens and _overlap_ratio(requirement_tokens, fact_tokens) < 0.6:
        return "REPHRASE"
    return "HIGHLIGHT"


# ------------------------------------------------------------------ generators


class _Builder:
    """Collects the sentences of the dossier with their declared provenance."""

    def __init__(self) -> None:
        self.sentences: list[DossierSentence] = []
        self._by_artifact: dict[str, list[str]] = {}

    def claim(self, artifact: str, text: str, fact_ids: Sequence[str] = ()) -> str:
        self.sentences.append(
            DossierSentence(artifact=artifact, text=text, fact_ids=tuple(fact_ids), kind="claim")
        )
        return text

    def offer(self, artifact: str, text: str) -> str:
        self.sentences.append(DossierSentence(artifact=artifact, text=text, kind="offer"))
        return text

    def structural(self, artifact: str, text: str) -> str:
        self.sentences.append(DossierSentence(artifact=artifact, text=text, kind="structural"))
        return text

    def body(self, artifact: str) -> str:
        return "\n".join(self._by_artifact.get(artifact, []))


def _render(lines: Sequence[str]) -> str:
    return "\n".join(line for line in lines if line is not None).strip() + "\n"


def _section_title(section: str, copy: Mapping[str, str]) -> str:
    return copy.get(section, section)


def _build_recommendations(
    builder: _Builder,
    copy: Mapping[str, str],
    offer: Mapping[str, Any],
    coverage: Sequence[DossierRequirementCoverage],
    facts: Mapping[str, DossierFact],
    language: str,
) -> tuple[list[DossierRecommendation], list[str]]:
    """One concrete action per requirement, with its proof."""
    key = "cv_recommendations"
    title = f"{copy['recommendations']} — {clean_text(offer.get('title'), limit=200)} — {clean_text(offer.get('company'), limit=200)}"
    lines: list[str] = [f"# {title}", ""]
    recommendations: list[DossierRecommendation] = []
    instructions = {
        "fr": {
            "HIGHLIGHT": "Mets ce fait en avant dans le CV : il prouve cette exigence.",
            "REPHRASE": "Reprends le vocabulaire de l'offre en gardant la preuve du profil.",
            "DO_NOT_ADD": "N'ajoute rien : aucune preuve approuvée ne soutient cette exigence.",
            "QUANTIFY": "Ajoute un chiffre seulement si tu peux le prouver ; sinon n'écris aucun chiffre.",
            "CONFIRM_LANGUAGE": "Confirme ton niveau de langue avant de l'écrire.",
        },
        "en": {
            "HIGHLIGHT": "Put this fact forward in the CV: it proves this requirement.",
            "REPHRASE": "Use the wording of the offer while keeping the profile proof.",
            "DO_NOT_ADD": "Add nothing: no approved proof supports this requirement.",
            "QUANTIFY": "Add a figure only if you can prove it; otherwise write no figure.",
            "CONFIRM_LANGUAGE": "Confirm your language level before writing it.",
        },
        "it": {
            "HIGHLIGHT": "Metti in evidenza questo fatto nel CV: dimostra il requisito.",
            "REPHRASE": "Riprendi il lessico dell'offerta mantenendo la prova del profilo.",
            "DO_NOT_ADD": "Non aggiungere nulla: nessuna prova approvata sostiene questo requisito.",
            "QUANTIFY": "Aggiungi un numero solo se puoi dimostrarlo; altrimenti non scrivere numeri.",
            "CONFIRM_LANGUAGE": "Conferma il tuo livello di lingua prima di scriverlo.",
        },
        "de": {
            "HIGHLIGHT": "Bringe diesen Beleg im Lebenslauf vor: er belegt die Anforderung.",
            "REPHRASE": "Nutze die Formulierung der Ausschreibung und behalte den Profilbeleg.",
            "DO_NOT_ADD": "Füge nichts hinzu: kein freigegebener Beleg stützt diese Anforderung.",
            "QUANTIFY": "Nenne eine Zahl nur, wenn du sie belegen kannst; sonst keine Zahl.",
            "CONFIRM_LANGUAGE": "Bestätige dein Sprachniveau, bevor du es schreibst.",
        },
    }[language]
    lines.append(f"| {copy['requirement']} | {copy['action']} | {copy['instruction']} | {copy['proof']} |")
    lines.append("|---|---|---|---|")
    for item in coverage:
        fact = facts.get(item.fact_id)
        code = _recommendation_code(item, fact)
        instruction = instructions[code]
        proof = f"« {fact.evidence} »" if fact is not None and code != "DO_NOT_ADD" else copy["no_proof"]
        recommendations.append(
            DossierRecommendation(
                code=code,
                requirement_id=item.requirement_id,
                requirement=item.text,
                instruction=instruction,
                fact_id=item.fact_id if code != "DO_NOT_ADD" else "",
                quote=fact.evidence if fact is not None and code != "DO_NOT_ADD" else "",
                modality=item.modality,
            )
        )
        lines.append(f"| {item.text} | {code} | {instruction} | {proof} |")
    if not recommendations:
        lines.append(f"| — | — | {copy['no_proof']} | — |")
    lines.append("")
    lines.append(copy["no_auto_send"])
    body = _render(lines)
    for line in lines:
        builder.structural(key, line)
    return tuple(recommendations), body


def _select_cv_facts(
    coverage: Sequence[DossierRequirementCoverage],
    facts: Mapping[str, DossierFact],
) -> tuple[tuple[DossierFact, ...], tuple[str, ...]]:
    """Facts worth showing in the CV: first those proving a requirement."""
    ordered: list[DossierFact] = []
    covered: list[str] = []
    for item in coverage:
        if item.verdict != "supported" or not item.fact_id:
            continue
        fact = facts.get(item.fact_id)
        if fact is None or fact.fact_id in covered:
            continue
        covered.append(fact.fact_id)
        ordered.append(fact)
    for fact in facts.values():
        if fact.usable and fact.fact_id not in covered:
            covered.append(fact.fact_id)
            ordered.append(fact)
    return tuple(ordered), tuple(covered)


def _build_adapted_cv(
    builder: _Builder,
    copy: Mapping[str, str],
    offer: Mapping[str, Any],
    selected: Sequence[DossierFact],
    language: str,
    version: int,
    language_source: str,
) -> tuple[str, list[tuple[str, list[str]]]]:
    key = "adapted_cv"
    title = clean_text(offer.get("title"), limit=200) or "[poste à compléter]"
    company = clean_text(offer.get("company"), limit=200) or "[entreprise à compléter]"
    location_parts = [
        part
        for part in (clean_text(offer.get("city"), limit=80), clean_text(offer.get("country"), limit=80))
        if part
    ]
    location = f" — {', '.join(location_parts)}" if location_parts else ""
    lines: list[str] = [f"# {copy['cv']} — {title} — {company}", ""]
    builder.offer(key, f"# {copy['cv']} — {title} — {company}")
    source_label = copy["language_user"] if language_source == "user" else copy["language_offer"]
    language_line = f"**{copy['language_line'].format(language=language.upper(), source=source_label)}**"
    version_line = f"**{copy['version_line'].format(version=version)}**"
    lines.append(language_line)
    lines.append("")
    lines.append(version_line)
    lines.append("")
    builder.structural(key, language_line)
    builder.structural(key, version_line)

    sections: list[tuple[str, list[str]]] = []
    grouped: dict[str, list[DossierFact]] = {}
    for fact in selected:
        grouped.setdefault(_section_for(fact.category), []).append(fact)

    summary = builder.offer(
        key,
        copy["summary_line"].format(title=title, company=company, location=location),
    )
    lines.append(f"## {_section_title('summary', copy)}")
    lines.append("")
    lines.append(summary)
    lines.append("")
    sections.append(("summary", [summary]))

    for section in _SECTION_ORDER:
        if section == "summary":
            continue
        facts_in_section = grouped.get(section, [])
        if not facts_in_section:
            continue
        heading = f"## {_section_title(section, copy)}"
        lines.append(heading)
        lines.append("")
        builder.structural(key, heading)
        section_lines: list[str] = []
        for fact in facts_in_section:
            text = builder.claim(key, fact.value, (fact.fact_id,))
            lines.append(f"- {text}")
            section_lines.append(text)
        lines.append("")
        sections.append((section, section_lines))

    lines.append(copy["no_auto_send"])
    builder.structural(key, copy["no_auto_send"])
    return _render(lines), sections


def _build_cover_letter(
    builder: _Builder,
    copy: Mapping[str, str],
    offer: Mapping[str, Any],
    selected: Sequence[DossierFact],
    language: str,
) -> str:
    key = "cover_letter"
    title = clean_text(offer.get("title"), limit=200) or "[poste à compléter]"
    company = clean_text(offer.get("company"), limit=200) or "[entreprise à compléter]"
    location_parts = [
        part
        for part in (clean_text(offer.get("city"), limit=80), clean_text(offer.get("country"), limit=80))
        if part
    ]
    location = f", {', '.join(location_parts)}" if location_parts else ""
    lines: list[str] = [f"# {copy['letter']} — {title} — {company}", ""]
    builder.offer(key, f"# {copy['letter']} — {title} — {company}")
    lines.append(f"**{copy['cover_object'].format(title=title)}**")
    lines.append("")
    builder.structural(key, lines[-2])
    lines.append(copy["cover_intro"])
    lines.append("")
    builder.structural(key, copy["cover_intro"])
    lines.append(
        builder.offer(
            key,
            copy["summary_line"].format(title=title, company=company, location=location),
        )
    )
    lines.append("")
    lines.append(copy["documented_line"])
    lines.append("")
    builder.structural(key, copy["documented_line"])
    for fact in selected[:8]:
        text = builder.claim(key, fact.value, (fact.fact_id,))
        lines.append(copy["cover_claim"].format(value=text))
    lines.append("")
    lines.append(copy["cover_close"])
    lines.append("")
    builder.structural(key, copy["cover_close"])
    lines.append(copy["cover_available"])
    lines.append("")
    builder.structural(key, copy["cover_available"])
    lines.append(copy["cover_sign"])
    lines.append("")
    builder.structural(key, copy["cover_sign"])
    lines.append(copy["no_auto_send"])
    builder.structural(key, copy["no_auto_send"])
    return _render(lines)


def _build_prep_sheet(
    builder: _Builder,
    copy: Mapping[str, str],
    offer: Mapping[str, Any],
    coverage: Sequence[DossierRequirementCoverage],
    facts: Mapping[str, DossierFact],
    selected: Sequence[DossierFact],
    language: str,
    version: int,
    language_source: str,
) -> str:
    key = "prep_sheet"
    title = clean_text(offer.get("title"), limit=200) or "[poste à compléter]"
    company = clean_text(offer.get("company"), limit=200) or "[entreprise à compléter]"
    location_parts = [
        part
        for part in (clean_text(offer.get("city"), limit=80), clean_text(offer.get("country"), limit=80))
        if part
    ]
    lines: list[str] = [f"# {copy['prep']} — {title} — {company}", ""]
    builder.structural(key, lines[0])
    source_label = copy["language_user"] if language_source == "user" else copy["language_offer"]
    language_line = f"**{copy['language_line'].format(language=language.upper(), source=source_label)}**"
    version_line = f"**{copy['version_line'].format(version=version)}**"
    lines.append(language_line)
    lines.append("")
    lines.append(version_line)
    lines.append("")
    builder.structural(key, language_line)
    builder.structural(key, version_line)

    heading_offer = f"## {copy['prep_offer_facts']}"
    lines.append(heading_offer)
    lines.append("")
    builder.structural(key, heading_offer)
    lines.append(f"| {copy['offer_fact']} | {copy['offer_value']} | {copy['offer_source']} |")
    lines.append("|---|---|---|")
    labels = _OFFER_ROW_LABELS[language]
    offer_rows = (
        (labels[0], company, "jobs.company"),
        (labels[1], title, "jobs.title"),
        (labels[2], ", ".join(location_parts) if location_parts else "", "jobs.city / jobs.country"),
        (labels[3], clean_text(offer.get("deadline_date"), limit=40), "jobs.deadline_date"),
        (labels[4], clean_text(offer.get("languages_required"), limit=200), "jobs.languages_required"),
        (labels[5], clean_text(offer.get("eligibility_requirement"), limit=200), "jobs.eligibility_requirement"),
    )
    for label, value, source in offer_rows:
        lines.append(f"| {label} | {value or '—'} | {source} |")
    lines.append("")

    heading_coverage = f"## {copy['prep_coverage']}"
    lines.append(heading_coverage)
    lines.append("")
    builder.structural(key, heading_coverage)
    lines.append(f"| {copy['requirement']} | {copy['type']} | {copy['verdict']} | {copy['proof']} |")
    lines.append("|---|---|---|---|")
    for item in coverage:
        proof = f"« {item.quote} »" if item.quote else copy["no_proof"]
        lines.append(f"| {item.text} | {item.modality} | {item.verdict} | {proof} |")
    if not coverage:
        lines.append(f"| — | — | — | {copy['no_proof']} |")
    lines.append("")

    heading_gaps = f"## {copy['prep_gaps']}"
    lines.append(heading_gaps)
    lines.append("")
    builder.structural(key, heading_gaps)
    gaps = [item for item in coverage if item.verdict != "supported"]
    if gaps:
        for item in gaps:
            lines.append(f"- {item.text}")
            builder.structural(key, f"- {item.text}")
    else:
        lines.append(f"- {copy['no_proof']}")
        builder.structural(key, f"- {copy['no_proof']}")
    lines.append("")

    heading_talking = f"## {copy['prep_talking']}"
    lines.append(heading_talking)
    lines.append("")
    builder.structural(key, heading_talking)
    for fact in selected[:8]:
        lines.append(f"- {fact.evidence}")
        builder.claim(key, fact.evidence, (fact.fact_id,))
    if not selected:
        lines.append(f"- {copy['no_proof']}")
        builder.structural(key, f"- {copy['no_proof']}")
    lines.append("")

    heading_before = f"## {copy['prep_before']}"
    lines.append(heading_before)
    lines.append("")
    builder.structural(key, heading_before)
    for item in (
        f"- [ ] {copy['check_read']}",
        f"- [ ] {copy['check_language'].format(language=language.upper())}",
        f"- [ ] {copy['check_send']}",
    ):
        lines.append(item)
        builder.structural(key, item)
    return _render(lines)


def _build_checklist(
    builder: _Builder,
    copy: Mapping[str, str],
    claims: Sequence[DossierClaim],
    language: str,
) -> str:
    key = "checklist"
    lines: list[str] = [f"# {copy['checklist']}", ""]
    builder.structural(key, lines[0])
    lines.append(f"- [ ] {copy['check_read']}")
    lines.append(f"- [ ] {copy['check_language'].format(language=language.upper())}")
    for line in lines[-2:]:
        builder.structural(key, line)
    for claim in claims:
        if claim.verdict == "unsupported":
            text = copy["check_fix"].format(text=claim.text)
        elif claim.verdict == "to_verify":
            text = copy["check_confirm"].format(text=claim.text)
        else:
            continue
        lines.append(f"- [ ] {text}")
        builder.structural(key, text)
    lines.append(f"- [ ] {copy['check_send']}")
    builder.structural(key, lines[-1])
    return _render(lines)


def _build_interview_questions(
    builder: _Builder,
    copy: Mapping[str, str],
    coverage: Sequence[DossierRequirementCoverage],
    facts: Mapping[str, DossierFact],
) -> str:
    key = "interview_questions"
    lines: list[str] = [f"# {copy['questions']}", ""]
    builder.structural(key, lines[0])
    for item in coverage:
        if item.verdict == "supported":
            fact = facts.get(item.fact_id)
            if fact is None:
                continue
            text = copy["question_supported"].format(value=fact.evidence)
        elif item.modality == "required":
            text = copy["question_gap"].format(requirement=item.text)
        else:
            text = copy["question_offer"].format(requirement=item.text)
        lines.append(f"- {text}")
        builder.structural(key, text)
    if len(lines) == 2:
        lines.append(f"- {copy['no_proof']}")
        builder.structural(key, lines[-1])
    return _render(lines)


# --------------------------------------------------------------------- diffing


def _base_sections(text: Any) -> list[tuple[str, list[str]]]:
    """Split the person's current CV into (section, lines) pairs."""
    sections: list[tuple[str, list[str]]] = []
    current_title = "general"
    current_lines: list[str] = []
    for raw_line in clean_text(text, limit=200_000).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if current_lines:
                sections.append((current_title, current_lines))
                current_lines = []
            current_title = line.lstrip("#").strip() or "general"
            continue
        line = re.sub(r"^[-*+]\s+(?:\[[ xX]\]\s*)?", "", line).strip()
        if line:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, current_lines))
    return sections


def _diff_lines(
    base_text: Any,
    adapted_sections: Sequence[tuple[str, list[str]]],
    fact_by_line: Mapping[str, str],
) -> tuple[DossierDiffLine, ...]:
    """Compare the CV before and after, line by line."""
    base = _base_sections(base_text)
    base_normalized: dict[str, list[tuple[str, str]]] = {}
    for section, lines in base:
        for line in lines:
            base_normalized.setdefault(_fold(line), []).append((section, line))
    adapted_normalized: dict[str, list[tuple[str, str]]] = {}
    for section, lines in adapted_sections:
        for line in lines:
            adapted_normalized.setdefault(_fold(line), []).append((section, line))
    diff: list[DossierDiffLine] = []
    for folded, entries in adapted_normalized.items():
        section, line = entries[0]
        if folded in base_normalized:
            diff.append(DossierDiffLine(section=section, kind="kept", text=line))
        else:
            diff.append(
                DossierDiffLine(
                    section=section,
                    kind="added",
                    text=line,
                    fact_id=fact_by_line.get(line, ""),
                )
            )
    for folded, entries in base_normalized.items():
        if folded in adapted_normalized:
            continue
        section, line = entries[0]
        diff.append(DossierDiffLine(section=section, kind="removed", text=line))
    return tuple(diff)


# ------------------------------------------------------------------- builder


def build_application_dossier(
    offer: Mapping[str, Any],
    profile_facts: Any = None,
    *,
    language: Any = None,
    base_cv: Any = "",
    version: int = 1,
    generated_at: Any = "",
    history: Sequence[DossierVersion] = (),
) -> ApplicationDossier:
    """Build the complete, verifiable application dossier for one offer.

    The function is pure: it never writes a file, never opens a socket and
    never reads a clock.  ``generated_at`` is supplied by the caller so that
    two identical calls produce two identical dossiers.
    """
    if not isinstance(offer, Mapping):
        raise UserFacingError("Cette offre n’existe pas.")

    facts = facts_from_profile(profile_facts)
    facts_by_id = {fact.fact_id: fact for fact in facts}
    language_code, language_source = _resolve_language(offer, language)
    copy = _COPY[language_code]

    analysis = analyze_offer(dict(offer))
    requirements = [
        record
        for record in analysis.get("requirements", [])
        if isinstance(record, Mapping) and not record.get("injection_suspect")
    ]
    coverage = _cover_requirements(requirements, facts)
    selected, _ = _select_cv_facts(coverage, facts_by_id)

    builder = _Builder()
    recommendations, recommendations_body = _build_recommendations(
        builder, copy, offer, coverage, facts_by_id, language_code
    )
    cv_body, adapted_sections = _build_adapted_cv(
        builder, copy, offer, selected, language_code, version, language_source
    )
    letter_body = _build_cover_letter(builder, copy, offer, selected, language_code)
    prep_body = _build_prep_sheet(
        builder,
        copy,
        offer,
        coverage,
        facts_by_id,
        selected,
        language_code,
        version,
        language_source,
    )
    questions_body = _build_interview_questions(builder, copy, coverage, facts_by_id)

    artifacts = (
        DossierArtifact("cv_recommendations", copy["recommendations"], recommendations_body, language_code),
        DossierArtifact("adapted_cv", copy["cv"], cv_body, language_code),
        DossierArtifact("cover_letter", copy["letter"], letter_body, language_code),
        DossierArtifact("prep_sheet", copy["prep"], prep_body, language_code),
        DossierArtifact("interview_questions", copy["questions"], questions_body, language_code),
    )

    claims: list[DossierClaim] = []
    for artifact in artifacts:
        claims.extend(
            verify_dossier_text(artifact.key, artifact.body, facts, builder.sentences)
        )

    verification = DossierVerification(
        claims=tuple(claims),
        supported_count=sum(1 for claim in claims if claim.verdict == "supported"),
        unsupported_count=sum(1 for claim in claims if claim.verdict == "unsupported"),
        to_verify_count=sum(1 for claim in claims if claim.verdict == "to_verify"),
    )
    checklist_body = _build_checklist(builder, copy, claims, language_code)
    artifacts = artifacts + (
        DossierArtifact("checklist", copy["checklist"], checklist_body, language_code),
    )
    claims.extend(
        verify_dossier_text("checklist", checklist_body, facts, builder.sentences)
    )
    verification = DossierVerification(
        claims=tuple(claims),
        supported_count=sum(1 for claim in claims if claim.verdict == "supported"),
        unsupported_count=sum(1 for claim in claims if claim.verdict == "unsupported"),
        to_verify_count=sum(1 for claim in claims if claim.verdict == "to_verify"),
    )

    fact_by_line = {fact.value: fact.fact_id for fact in selected}
    diff = _diff_lines(base_cv, adapted_sections, fact_by_line)

    version_entry = DossierVersion(
        version=version,
        language=language_code,
        language_source=language_source,
        supported_count=verification.supported_count,
        unsupported_count=verification.unsupported_count,
        to_verify_count=verification.to_verify_count,
        generated_at=clean_text(generated_at, limit=64),
        summary=(
            f"{len(artifacts)} livrables · {verification.supported_count} affirmations prouvées · "
            f"{verification.unsupported_count} non prouvées · {verification.to_verify_count} à vérifier"
        ),
    )
    full_history = tuple(history) + (version_entry,)

    return ApplicationDossier(
        offer_id=clean_text(offer.get("id"), limit=120),
        company=clean_text(offer.get("company"), limit=200),
        title=clean_text(offer.get("title"), limit=200),
        language=language_code,
        language_source=language_source,
        version=version,
        artifacts=artifacts,
        recommendations=recommendations,
        coverage=coverage,
        diff=diff,
        verification=verification,
        history=full_history,
        sentences=tuple(builder.sentences),
        facts=facts,
        automatic_submission=AUTOMATIC_SUBMISSION,
    )


# ------------------------------------------------------------------- export


def reverify_dossier(
    dossier: ApplicationDossier,
    artifacts: Mapping[str, Any] | None = None,
    facts: Sequence[DossierFact] | None = None,
) -> DossierVerification:
    """Re-run the verifier over edited artifact bodies.

    ``artifacts`` maps an artifact key to its (possibly hand-edited) body.
    Artifacts that are not listed keep the generated body.  ``facts`` replaces
    the dossier's own facts: the caller passes the **current** approved facts
    so that a fact which is no longer approved stops proving anything.

    The returned verification replaces the previous one: an affirmation the
    person wrote by hand and cannot prove blocks the export exactly like a
    generated one.
    """
    used = tuple(facts) if facts is not None else dossier.facts
    claims: list[DossierClaim] = []
    for artifact in dossier.artifacts:
        body = artifact.body
        if artifacts and artifact.key in artifacts:
            body = clean_text(artifacts.get(artifact.key), limit=400_000)
        claims.extend(
            verify_dossier_text(artifact.key, body, used, dossier.sentences)
        )
    return DossierVerification(
        claims=tuple(claims),
        supported_count=sum(1 for claim in claims if claim.verdict == "supported"),
        unsupported_count=sum(1 for claim in claims if claim.verdict == "unsupported"),
        to_verify_count=sum(1 for claim in claims if claim.verdict == "to_verify"),
    )


def with_verification(
    dossier: ApplicationDossier, verification: DossierVerification
) -> ApplicationDossier:
    """Return the same dossier with a fresh verification result."""
    return replace(dossier, verification=verification)


def with_artifacts(
    dossier: ApplicationDossier,
    artifacts: Mapping[str, Any],
    facts: Sequence[DossierFact] | None = None,
) -> ApplicationDossier:
    """Return the dossier with edited artifact bodies and a fresh verification.

    This is the "the person reworked the letter" path: the bodies are replaced
    by what the person actually wrote, and the verifier runs again on them.
    ``facts`` lets the caller verify against the current approved facts.
    """
    updated: list[DossierArtifact] = []
    for artifact in dossier.artifacts:
        body = artifact.body
        if artifacts and artifact.key in artifacts:
            body = clean_text(artifacts.get(artifact.key), limit=400_000)
        updated.append(replace(artifact, body=body))
    refreshed = replace(dossier, artifacts=tuple(updated))
    return with_verification(refreshed, reverify_dossier(refreshed, facts=facts))


def export_dossier(dossier: ApplicationDossier, target_dir: Any) -> dict[str, str]:
    """Write the dossier to disk — refused while an affirmation is unsupported.

    The verifier runs again on the very bodies that are about to be written:
    an export can never carry an affirmation that is not proved, whatever the
    verification stored in the dossier says.  The export is a local write:
    no network, no upload, no submission.
    """
    verification = reverify_dossier(dossier)
    if not verification.export_allowed:
        blocking = verification.blocking_claims
        details = "; ".join(f"[{claim.artifact}] {claim.text}" for claim in blocking[:5])
        raise UserFacingError(
            "Export final bloqué : une affirmation n'est pas prouvée par un fait de profil approuvé. "
            f"Corrige ou prouve d'abord : {details}"
        )
    destination = Path(target_dir)
    destination.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for artifact in dossier.artifacts:
        path = destination / f"{artifact.key}.md"
        path.write_text(artifact.body, encoding="utf-8")
        written[artifact.key] = str(path)
    verification_path = destination / "verification.json"
    verification_path.write_text(
        json.dumps(dossier.verification.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    written["verification"] = str(verification_path)
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "offer_id": dossier.offer_id,
                "company": dossier.company,
                "title": dossier.title,
                "language": dossier.language,
                "language_source": dossier.language_source,
                "version": dossier.version,
                "artifacts": sorted(written),
                "automatic_submission": dossier.automatic_submission,
                "export_allowed": dossier.export_allowed,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    written["manifest"] = str(manifest_path)
    return written
