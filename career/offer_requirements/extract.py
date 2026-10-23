"""Deterministic extraction of offer requirements with precise provenance.

Pure Python, local, no network, no model and no clock: analyzing the same
offer always returns byte-identical results.  Offer text is treated as
untrusted data — nothing here branches on an offer's imperative wording or
executes anything it describes.

- ``split_source_lines`` / ``resolve_locator`` let consumers show exactly the
  passage behind a requirement instead of a generic "exigence n°N".
- ``analyze_offer`` returns the documented contract (see ``contracts.py``):

Facette "exposition, pas arbitrage": structured fields and the description
are never reconciled silently — disagreements are listed in
``contradictions`` with both original statements.  A preference detected in
preferred sections or preferred markers is never turned into a mandatory
requirement, and explicit negations stay out of the required set.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from ..models import clean_text, normalized_text
from . import contracts

MAX_FIELD_CHARS = 30_000
MAX_REQUIREMENTS = 60
MAX_CONTRADICTIONS = 10
MAX_WARNINGS = 8
MIN_STATEMENT_CHARS = 4
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
BULLET_PREFIXES = "•-–*▪●➤·‣◦ "
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_TAG_BLOCK = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^<>\n]{1,200}>")
_BLOCK_CLOSERS = re.compile(r"</(p|h[1-6]|li|div|ul|ol|br|tr)>|<br[^>]*>", re.IGNORECASE)
_ENTITIES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&nbsp;": " "}

# ---------------------------------------------------------------- headings

_REQUIREMENT_HEADINGS = frozenset(
    {
        "requirements", "qualifications", "required qualifications",
        "minimum qualifications", "must have", "your profile", "what you bring",
        "what we are looking for", "who you are", "what you ll need",
        "skills and experience", "prerequisites",
        "profil", "profil recherche", "votre profil", "qui vous etes",
        "qualifications requises", "competences requises", "prerequis",
        "requis", "requis du poste", "ce que vous apportez",
        "ce que nous recherchons", "diplomes et competences",
        "voraussetzungen", "anforderungen", "ihre voraussetzungen",
        "was sie mitbringen", "dein profil", "ihre qualifikationen",
        "requisiti", "requisiti del candidato", "competenze richieste",
        "profilo richiesto", "il profilo che cerchiamo",
        "requisitos", "competencias requeridas", "perfil solicitado",
        "lo que buscamos", "requerimientos", "conocimientos necesarios",
    }
)
_PREFERRED_HEADINGS = frozenset(
    {
        "preferred qualifications", "nice to have", "nice to haves",
        "desirable qualifications", "bonus points", "desirable",
        "atouts", "atout apprecie", "afortemente apprecie",
        "fortement apprecie", "souhaite", "souhaitable", "un plus",
        "serait un plus",
        "wunschenswert", "von vorteil", "erwunscht", "bonus",
        "gradito", "gradite", "titoli preferenziali", "apprezzato",
        "apprezzati",
        "se valoriza", "valoraremos", "deseable", "sera un plus",
        "puntos extra",
    }
)
_BENEFIT_HEADINGS = frozenset(
    {
        "benefits", "what we offer", "perks", "perks and benefits",
        "avantages", "avantages sociaux", "notre offre",
        "was wir bieten", "leistungen", "vorteile",
        "cosa offriamo", "benefici",
        "que ofrecemos", "beneficios", "ventajas",
        "about us", "about the role", "a propos", "notre entreprise",
        "uber uns", "chi siamo", "sobre nosotros",
    }
)
_OTHER_HEADINGS = frozenset(
    {
        "responsibilities", "your responsibilities", "what you will do",
        "what you ll do", "missions", "vos missions", "responsabilites",
        "about the team", "the role", "your role", "context",
        "additional information", "further information", "more information",
        "informations complementaires", "weitere informationen",
        "informazioni aggiuntive", "informacion adicional",
        "aufgaben", "ihre aufgaben", "deine aufgaben", "aufgabenprofil",
        "attivita", "compiti", "il ruolo", "funzioni",
        "funciones", "responsabilidades", "que haras",
    }
)

# -------------------------------------------------- statement-level markers

_REQUIRED_MARKERS = (
    "required", "must have", "you must", "at least", "minimum of",
    "requires", "proficiency in", "fluent", "fluent in", "mandatory", "essential",
    "is expected",
    "requis", "requise", "requis", "exige", "exigee", "obligatoire",
    "indispensable", "vous devez", "il faut", "maitrise de", "maitrise d",
    "courant", "minimum de", "d au moins", "serait requise",
    "erforderlich", "voraussetzung", "muss", "mindestens", "benotigt",
    "richiesto", "richiesta", "richiesti", "indispensabile",
    "deve avere", "deve possedere", "minimo", "almeno",
    "requerido", "requerida", "requeridos", "exigido", "imprescindible",
    "debe tener", "es necesario", "al menos",
)
_PREFERRED_MARKERS = (
    "preferred", "nice to have", "a plus", "big plus", "major plus",
    "desirable", "would be a bonus", "appreciated", "welcome",
    "apprecie", "appreciee", "apprecies", "souhaite", "souhaitee",
    "souhaitable", "un atout", "un plus valorise",
    "wunschenswert", "von vorteil", "erwunscht", "ein plus",
    "gradito", "gradita", "graditi", "apprezzato", "apprezzata",
    "apprezzati", "titolo preferenziale", "un plus",
    "se valoriza", "valorado", "valorable", "deseable",
    "sera un plus", "buen punto", "se valorara",
)
_NEGATION_MARKERS = (
    "not required", "not mandatory", "no need", "we do not require",
    "none required", "no formal requirement",
    "pas requise", "pas requis", "pas obligatoire", "non obligatoire",
    "pas necessaire", "inutile de", "aucune experience exigee",
    "n est pas exigee", "n est pas requis",
    "nicht erforderlich", "keine voraussetzung", "nicht notwendig",
    "nicht gefordert",
    "non richiesto", "non richiesta", "non e richiesto",
    "non necessario", "non indispensable",
    "no es requisito", "no requerido", "no es necesario",
    "no imprescindible", "no exigido",
)
_DEADLINE_MARKERS = (
    "application deadline", "closing date", "deadline for applications",
    "applications close", "date limite de candidature",
    "date limite", "candidatures close",
    "bewerbungsfrist",
    "scadenza delle candidature", "scadenza",
    "plazo de solicitud", "fecha limite",
)
_INJECTION_MARKERS = (
    "ignore all previous", "ignore previous", "ignore the above",
    "disregard previous", "disregard the above",
    "system prompt", "you are now", "act as system",
    "reveal your instructions", "print your instructions",
    "output your instructions",
    "ignorez toutes", "ignorez les instructions precedentes",
    "releve ton prompt", "revele ton", "envoie tes donnees",
    "ignoriere alle", "ignoriere vorherige",
    "ignora tutte", "ignora le istruzioni",
    "ignora todas", "ignora las instrucciones",
    "ejecuta", "esegui il comando",
)

# ---------------------------------------------------------------- category

_CATEGORY_KEYWORDS: tuple[tuple[str, frozenset[str]], ...] = (
    (
        "language",
        frozenset(
            {
                "english", "french", "german", "spanish", "italian",
                "mandarin", "fluent", "bilingual", "native",
                "anglais", "francais", "allemand", "espagnol", "italien",
                "langue", "langues",
                "englisch", "franzosisch", "spanisch", "italienisch",
                "deutsch", "sprache", "sprachkenntnisse",
                "inglese", "francese", "spagnolo", "tedesco", "italiano",
                "ingles", "espanol", "aleman",
                "lingua", "idioma", "idiomas",
                "toeic", "ielts", "c1", "c2", "b2", "near native",
                "oral e scritta",
            }
        ),
    ),
    (
        "technical_skill",
        frozenset(
            {
                "excel", "vba", "python", "sql", "power bi", "powerbi",
                "sas", "sap", "aws", "api", "java", "javascript",
                "matlab", "tableau", "bloomberg", "factset", "capital iq",
                "macros", "outlook", "office",
                "kenntnisse", "competences en", "competenza",
                "conoscenze di", "conocimientos de",
            }
        ),
    ),
    (
        "education",
        frozenset(
            {
                "bachelor", "master", "phd", "msc", "mba", "bac",
                "baccalaureat", "m1", "m2", "degree", "diploma",
                "diploma di", "universite", "university", "universita",
                "universidad", "student", "etudiant", "studente",
                "ecole", "school", "studies", "studi", "cursus",
                "diplom", "laurea", "grado", "engineering school",
                "titulo",
            }
        ),
    ),
    (
        "experience",
        frozenset(
            {
                "experience", "erfahrung", "esperienza", "experiencia",
                "years of", "months of", "internship", "praktikum",
                "background", "ans d", "ans de",
            }
        ),
    ),
    (
        "availability",
        frozenset(
            {
                "available", "availability", "disponible", "disponibilite",
                "disponibilita", "disponibilidad", "verfugbarkeit",
                "asap", "sofort", "immediately",
                "date de debut", "starting period", "start period",
                "au plus tot",
            }
        ),
    ),
    (
        "mobility",
        frozenset(
            {
                "relocation", "mobility", "mobilite", "umzug",
                "trasferta", "traslado", "remote", "hybrid", "on site",
                "relocate",
                "onsite", "presentiel", "sur site", "vor ort",
                "based in", "permis b", "driving licence", "deplacements",
                "fuehrerschein", "patente di guida",
            }
        ),
    ),
    (
        "work_authorization",
        frozenset(
            {
                "visa", "work permit", "work authorization", "authorization to work",
                "right to work", "eligible to work", "sponsorship",
                "citizenship", "nationality", "eu citizen", "ue",
                "autorisation de travail",
                "autorizzazione al lavoro",
                "permis de travail", "droit de travailler",
                "aufenthaltstitel", "arbeitsbewilligung",
                "permesso di lavoro", "permiso de trabajo",
                "residence permit", "carte de sejour",
            }
        ),
    ),
)

_GENERIC_TOKENS = frozenset(
    {
        "the", "and", "for", "with", "you", "your", "our", "will", "have",
        "this", "that", "from", "are", "not", "plus", "minimum", "years",
        "months", "ans", "mois", "required", "experience",
        "competences", "skills", "kenntnisse", "stages",
    }
)


# ------------------------------------------------------------------ helpers

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def strip_html(value: str) -> tuple[str, bool]:
    """Remove HTML markup when the field carries any; text-only otherwise."""
    raw = clean_text(value, limit=MAX_FIELD_CHARS)
    if "<" not in raw or ">" not in raw:
        return raw, False
    text = _TAG_BLOCK.sub(" ", raw)
    text = _BLOCK_CLOSERS.sub("\n", text)
    text = _TAG.sub(" ", text)
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    text = re.sub(r"[ \t]{2,}", " ", text)
    lines = [line.strip(" \t") for line in text.splitlines()]
    collapsed = [line for index, line in enumerate(lines) if line or (index > 0 and lines[index - 1])]
    stripped = "\n".join(collapsed).strip()
    return stripped, True


def _field_lines(value: Any) -> tuple[list[str], bool, bool]:
    """Clean a field into lines; return (lines, html_stripped, truncated)."""
    raw = clean_text(value, limit=MAX_FIELD_CHARS + 1)
    truncated = len(raw) > MAX_FIELD_CHARS
    text, html_stripped = (
        strip_html(raw) if ("<" in raw and ">" in raw) else (raw, False)
    )
    lines = [cleaned.strip(" \t") for cleaned in text.splitlines()]
    return lines, html_stripped, truncated


def _bullets(line: str) -> str:
    stripped = line.strip(BULLET_PREFIXES)
    stripped = re.sub(r"^\d+[.)]\s+", "", stripped)
    stripped = re.sub(r"^[a-z][.)]\s+", "", stripped, flags=re.IGNORECASE)
    return stripped.strip(BULLET_PREFIXES)


def _statements(line: str, *, keep_bullets: bool) -> list[str]:
    item = _bullets(line) if keep_bullets else line
    if not item:
        return []
    out = [*SENTENCE_SPLIT.split(item)]
    return [part.strip(" ;,") for part in out if part.strip(" ;,")]


def _detect_category(text: str) -> str:
    padded = f" {normalized_text(text)} "
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in padded for keyword in keywords):
            return category
    return "other"


def _has_marker(normalized: str, markers: tuple[str, ...] | frozenset[str]) -> bool:
    padded = f" {normalized} "
    return any(marker in padded for marker in markers)


def _is_heading(line: str) -> tuple[str, str] | None:
    """Return (normalized heading, inline remainder) when ``line`` is a title."""
    if len(line) > 90:
        return None
    prefix, separator, remainder = line.partition(":")
    if separator and len(prefix) <= 80:
        normalized = normalized_text(prefix)
        remainder = remainder.strip()
    else:
        if SENTENCE_SPLIT.split(line) != [line]:
            return None
        normalized = normalized_text(line)
        if len(normalized.split()) > 8:
            return None
        remainder = ""
    if (
        normalized in _REQUIREMENT_HEADINGS
        or normalized in _PREFERRED_HEADINGS
        or normalized in _BENEFIT_HEADINGS
        or normalized in _OTHER_HEADINGS
    ):
        return normalized, remainder
    return None


class _Builder:
    """Collects requirement records with stable ids and duplicate flags."""

    def __init__(self, offer_id: str) -> None:
        self.offer_id = offer_id
        self.normalized_seen: dict[str, str] = {}
        self.records: list[dict[str, Any]] = []
        self.duplicates: list[dict[str, str]] = []
        self.injection_suspects: list[dict[str, str]] = []
        self.truncated = False
        self.warnings: list[str] = []

    def _id(self, source_field: str, normalized: str) -> str:
        base = contracts.ID_PREFIX + _sha(f"{self.offer_id}|{source_field}|{normalized}")
        occurrence = sum(
            1 for record in self.records if record["id"] == base or record["id"].startswith(base + "_")
        )
        return base if occurrence == 0 else f"{base}_{occurrence + 1}"

    def add(
        self,
        text: str,
        *,
        source_field: str,
        locator: str,
        heading: str,
        modality: str,
        base_confidence: float,
        negated: bool = False,
    ) -> None:
        statement = clean_text(text, limit=400)
        if len(statement) < MIN_STATEMENT_CHARS or len(self.records) >= MAX_REQUIREMENTS:
            return
        normalized = normalized_text(statement)
        if not normalized:
            return
        confidence = base_confidence
        if modality == "unknown":
            confidence = min(confidence, contracts.UNKNOWN_CONFIDENCE_CAP)
        injection = _has_marker(normalized, _INJECTION_MARKERS)
        if injection:
            # An offer text that addresses the reading program stays data: it
            # is flagged and can never carry a required preference.
            if modality != "unknown":
                modality = "unknown"
            confidence = min(confidence, 0.35)
        notes: list[str] = []
        if injection:
            notes.append("injection suspect: statement treated as inert flagged data")
        if negated:
            notes.append("explicit negation: statement kept but not treated as a requirement")
        if modality == "preferred":
            notes.append("preferred statement: never mandatory")
        record = {
            "id": self._id(source_field, normalized),
            "text": statement,
            "source_field": source_field,
            "locator": locator,
            "heading": heading,
            "category": _detect_category(statement),
            "modality": modality,
            "confidence": round(confidence, 2),
            "negated": negated,
            "injection_suspect": injection,
            "notes": notes,
        }
        if normalized in self.normalized_seen:
            self.duplicates.append(
                {
                    "id": record["id"],
                    "duplicate_of": self.normalized_seen[normalized],
                    "normalized_text": normalized,
                }
            )
        else:
            self.normalized_seen[normalized] = record["id"]
        self.records.append(record)
        if injection:
            self.injection_suspects.append(
                {
                    "id": record["id"],
                    "text": statement,
                    "source_field": source_field,
                    "locator": locator,
                }
            )
            if len(self.warnings) < MAX_WARNINGS:
                self.warnings.append(
                    "Un passage de l’offre tente de donner des instructions au programme de lecture ; "
                    "il reste affiché tel quel, traité comme donnée, jamais exécuté."
                )

    def add_line(
        self,
        line: str,
        *,
        source_field: str,
        line_number: int,
        heading: str,
        base_modality: str,
        base_confidence: float,
    ) -> None:
        for statement in _statements(line, keep_bullets=True):
            if len(statement) < MIN_STATEMENT_CHARS:
                continue
            normalized = normalized_text(statement)
            negated = _has_marker(normalized, _NEGATION_MARKERS)
            if negated:
                modality = "contextual"
            elif _has_marker(normalized, _PREFERRED_MARKERS) or base_modality == "preferred":
                modality = "preferred"
            elif base_modality == "required":
                modality = "required"
            else:
                modality = "unknown"
            locator = (
                f"line:{line_number}.sentence:{self._sentence_index(line, statement)}"
                if SENTENCE_SPLIT.split(line) != [line]
                else f"line:{line_number}"
            )
            self.add(
                statement,
                source_field=source_field,
                locator=locator,
                heading=heading,
                modality=modality,
                base_confidence=base_confidence,
                negated=negated,
            )

    @staticmethod
    def _sentence_index(line: str, statement: str) -> int:
        parts = [part.strip() for part in SENTENCE_SPLIT.split(line)]
        try:
            return parts.index(next(part for part in parts if part.strip(" ;,") == statement)) + 1
        except StopIteration:  # pragma: no cover - statement came from the parts
            return 0

    def stats(self) -> dict[str, dict[str, int]]:
        by_modality: dict[str, int] = {}
        by_category: dict[str, int] = {}
        for record in self.records:
            by_modality[record["modality"]] = by_modality.get(record["modality"], 0) + 1
            by_category[record["category"]] = by_category.get(record["category"], 0) + 1
        return {"by_modality": by_modality, "by_category": by_category}


# ------------------------------------------------------------- description

# Sections whose inline remainder keeps requirement semantics.
_INLINE_SECTION_OK = frozenset({"requirements", "preferred"})


def _description_requirements(description_lines: list[str], builder: _Builder) -> dict[str, int]:
    """Walk description sections; return counters of skipped content."""
    section = "prose"
    skipped = {"benefit_lines": 0, "prose_neutral": 0, "deadline_lines": 0}
    for line_number, line in enumerate(description_lines, start=1):
        if _has_marker(normalized_text(line), _DEADLINE_MARKERS):
            skipped["deadline_lines"] += 1
            continue
        heading = _is_heading(line)
        if heading is not None:
            normalized, remainder = heading
            if normalized in _REQUIREMENT_HEADINGS:
                section = "requirements"
            elif normalized in _PREFERRED_HEADINGS:
                section = "preferred"
            elif normalized in _BENEFIT_HEADINGS:
                section = "benefits"
            elif normalized in _OTHER_HEADINGS:
                section = "other"
            else:  # pragma: no cover - _is_heading only returns known sets
                section = "prose"
            if remainder:
                builder.add_line(
                    remainder,
                    source_field="description_original",
                    line_number=line_number,
                    heading=normalized,
                    base_modality=(
                        "required" if section == "requirements"
                        else "preferred" if section == "preferred"
                        else "unknown"
                    ),
                    base_confidence=0.85 if section in _INLINE_SECTION_OK else 0.60,
                )
            continue
        if not line.strip():
            continue
        if section == "benefits":
            skipped["benefit_lines"] += 1
            continue
        if section == "other":
            skipped["prose_neutral"] += 1
            continue
        if section == "requirements":
            builder.add_line(
                line,
                source_field="description_original",
                line_number=line_number,
                heading="",
                base_modality="required",
                base_confidence=0.85,
            )
            continue
        if section == "preferred":
            builder.add_line(
                line,
                source_field="description_original",
                line_number=line_number,
                heading="",
                base_modality="preferred",
                base_confidence=0.85,
            )
            continue
        # Free prose: only statable sentences become requirements.
        for sentence in _statements(line, keep_bullets=False):
            if len(sentence) < MIN_STATEMENT_CHARS:
                continue
            normalized = normalized_text(sentence)
            injection = _has_marker(normalized, _INJECTION_MARKERS)
            negated = _has_marker(normalized, _NEGATION_MARKERS)
            if injection:
                modality, confidence = "unknown", 0.35
            elif negated:
                modality, confidence = "contextual", 0.60
            elif _has_marker(normalized, _PREFERRED_MARKERS):
                modality, confidence = "preferred", 0.75
            elif _has_marker(normalized, _REQUIRED_MARKERS):
                modality, confidence = "required", 0.75
            else:
                skipped["prose_neutral"] += 1
                continue
            locator = f"line:{line_number}.sentence:{builder._sentence_index(line, sentence)}"
            builder.add(
                sentence,
                source_field="description_original",
                locator=locator,
                heading="",
                modality=modality,
                base_confidence=confidence,
                negated=negated,
            )
    return skipped


def _content_tokens(text: str) -> set[str]:
    return {
        token
        for token in normalized_text(text).split()
        if len(token) >= 3 and token not in _GENERIC_TOKENS and not token.isdigit()
    }


def _structured_requirements(job: dict[str, Any], builder: _Builder) -> None:
    specs = (
        ("requirements", "requirements"),
        ("languages_required", "languages_required"),
        ("eligibility_requirement", "eligibility_requirement"),
        ("role_level", "role_level"),
    )
    for field_name, source_field in specs:
        lines, _html, _trunc = _field_lines(job.get(field_name))
        for line_number, line in enumerate([l for l in lines if l.strip()], start=1):
            builder.add_line(
                line,
                source_field=source_field,
                line_number=line_number,
                heading="",
                base_modality="required",
                base_confidence=contracts._BASE_CONFIDENCE[source_field],
            )


def _structured_vs_description_contradictions(
    records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Expose disagreements between structured fields and the description.

    Every record keeps its original wording on both sides; nothing is merged
    or reworded, and no side is chosen.
    """
    structured = [
        record
        for record in records
        if record["source_field"] in ("languages_required", "eligibility_requirement", "role_level")
    ]
    described = [
        record
        for record in records
        if record["source_field"] == "description_original"
    ]
    out: list[dict[str, Any]] = []
    for s_record in structured:
        s_tokens = _content_tokens(s_record["text"])
        for d_record in described:
            if not s_tokens & _content_tokens(d_record["text"]):
                continue
            if s_record["modality"] == d_record["modality"]:
                continue
            out.append(
                {
                    "topic": s_record["category"],
                    "structured": {
                        "id": s_record["id"],
                        "text": s_record["text"],
                        "source_field": s_record["source_field"],
                        "modality": s_record["modality"],
                    },
                    "described": {
                        "id": d_record["id"],
                        "text": d_record["text"],
                        "source_field": d_record["source_field"],
                        "modality": d_record["modality"],
                    },
                    "kind": "structured_vs_description",
                }
            )
            if len(out) >= MAX_CONTRADICTIONS:
                return out
    return out


def _ends_mid_sentence(lines: list[str]) -> bool:
    """Deterministic heuristic: the field was cut before the thought ended.

    Only long prose-like closings raise the flag; short bullets without a
    terminal punctuation mark are normal on public boards and never trigger
    a false trunctation warning.
    """
    if not lines:
        return False
    last = lines[-1].strip()
    if last.endswith("...") or last.endswith("…"):
        return True
    stripped = _bullets(last)
    words = normalized_text(stripped).split()
    if len(words) >= 10:
        if "…" not in stripped and (not stripped or stripped[-1] not in ".!?:;»\""):
            return True
    return False


def _application_deadline(job: dict[str, Any]) -> dict[str, Any] | None:
    structured = clean_text(job.get("deadline_date"), limit=32)
    if structured:
        match = _ISO_DATE.search(structured)
        return {
            "text": structured,
            "source_field": "deadline_date",
            "locator": "line:1",
            "date_iso": match.group(1) if match else None,
        }
    description_lines, _html, _trunc = _field_lines(job.get("description_original"))
    for line_number, line in enumerate([l for l in description_lines if l.strip()], start=1):
        normalized = normalized_text(line)
        if not _has_marker(normalized, _DEADLINE_MARKERS):
            continue
        for statement in _statements(line, keep_bullets=True):
            match = _ISO_DATE.search(statement)
            if match:
                return {
                    "text": clean_text(statement, limit=200),
                    "source_field": "description_original",
                    "locator": f"line:{line_number}",
                    "date_iso": match.group(1),
                }
        return {
            "text": clean_text(line, limit=200),
            "source_field": "description_original",
            "locator": f"line:{line_number}",
            "date_iso": None,
        }
    return None


# ------------------------------------------------------------------ API

def split_source_lines(offer: dict[str, Any], source_field: str) -> list[str]:
    """Lines a ``line:N`` locator may be resolved against, source field clean."""
    if source_field not in contracts.SOURCE_FIELDS:
        return []
    lines, _html, _trunc = _field_lines(offer.get(source_field) or "")
    return [line for line in lines if line.strip()]


def resolve_locator(offer: dict[str, Any], source_field: str, locator: str) -> str:
    """Return the verbatim source line a locator refers to ('' if unknown)."""
    match = re.fullmatch(r"line:(\d+)(?:\.sentence:\d+)?", clean_text(locator, limit=40))
    if not match:
        return ""
    index = int(match.group(1))
    lines = split_source_lines(offer, source_field)
    return clean_text(lines[index - 1], limit=400) if 0 < index <= len(lines) else ""


def analyze_offer(offer: dict[str, Any]) -> dict[str, Any]:
    """Build the documented provenance contract for one offer.

    Deterministic: same input dict, same output dict, forever.
    """
    offer = offer or {}
    offer_id = clean_text(offer.get("id"), limit=80)
    builder = _Builder(offer_id)

    _structured_requirements(offer, builder)

    description_lines, html_stripped, description_truncated = _field_lines(
        offer.get("description_original")
    )
    builder.truncated = description_truncated or _ends_mid_sentence(
        [line for line in description_lines if line.strip()]
    )
    if html_stripped and len(builder.warnings) < MAX_WARNINGS:
        builder.warnings.append(
            "La description contenait du HTML : les balises ont été retirées, le texte reste cité tel quel."
        )
    skipped = _description_requirements([l for l in description_lines if l.strip()], builder)

    if builder.truncated and len(builder.warnings) < MAX_WARNINGS:
        builder.warnings.append(
            "Le texte de l’offre a été tronqué : la liste des exigences peut être incomplète."
        )

    records = builder.records
    return {
        "offer_id": offer_id,
        "requirements": records,
        "duplicates": builder.duplicates,
        "contradictions": _structured_vs_description_contradictions(records),
        "application_deadline": _application_deadline(offer),
        "injection_suspects": builder.injection_suspects,
        "truncated": builder.truncated,
        "warnings": builder.warnings[:MAX_WARNINGS],
        "skipped": skipped,
        "stats": builder.stats(),
        "contract_version": contracts.SCHEMA_VERSION,
    }
