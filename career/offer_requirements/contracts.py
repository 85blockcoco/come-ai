"""Documented contract for precise requirement provenance (CVBOOST-02).

This module holds the vocabulary of the contract and the schema description.
It is pure data: no parsing, no network, no model.

WHAT THE CONTRACT REPLACES
Previous prep flows described an offer as a flat list of "exigence n°N"
strings with only a loose ``source`` label.  Every requirement must now carry
:

* ``source_field`` — the exact offer field (or detected passage kind) the
  statement came from: ``requirements`` (structured board field),
  ``description_original`` (untrusted free text),
  ``languages_required``, ``eligibility_requirement``, ``role_level`` or
  ``deadline_date``.
* ``locator`` — where inside the field the statement sits, as a stable
  ``"line:N[.sentence:M]"`` reference resolvable against
  ``split_source_lines(offer, source_field)``.  The original wording is
  available verbatim; the locator never paraphrases.
* ``text`` — the original excerpt, byte-for-byte (cleaned of control
  characters and HTML tags only when the field itself carried HTML; that is
  stated in ``notes``).  No paraphrase is ever used as proof: consumers must
  quote ``text`` + ``locator`` or nothing.
* ``category`` — one of :data:`CATEGORIES`.
* ``modality`` — one of :data:`MODALITIES`.  An explicit preference is never
  mandatory: a statement detected inside a preferred/pourvu Souhaitable-like
  section or carrying a "nice to have" marker is ``preferred`` even if it
  also contains a "required"-sounding word.
* ``confidence`` — a deterministic 0–1 score describing how sure the
  extraction is about category *and* modality, not a quality promise.

TRUST RULES
- Offer text is untrusted data and never an instruction: no function here
  branches on imperative content of an offer; sentences that address the
  reading program ("ignore previous instructions…") stay inert text, are
  flagged ``injection_suspect`` and are never used as requirements either.
- Contradictions between a structured field and the description are exposed
  in ``contradictions`` with both original sides.  Nothing arbitrates them
  silently; consumers see both statements and decide.
- Unknown stays unknown: a statement whose modality cannot be established is
  ``unknown``, never guessed, and its confidence is capped accordingly.
- Truncated input is marked top-level (``truncated``) so downstream code
  never presents a clipped list as complete.

SCHEMA (compact JSON of ``analyze_offer(offer)``)
::

  {
    "offer_id": "…",                          # echo of the offer id, "" if absent
    "requirements": [                         # requirement records, see above
      {
        "id": "req_<sha256-16>",              # deterministic stable id
        "text": "original verbatim excerpt",
        "source_field": "…",                  # see SOURCE_FIELDS
        "locator": "line:3.sentence:2",       # stable, resolvable
        "heading": "Requirements",            # enclosing section title or ""
        "category": "technical_skill|…",      # see CATEGORIES
        "modality": "required|preferred|contextual|unknown",
        "confidence": 0.85,                   # 0–1, deterministic
        "negated": false,                     # explicit negation detected
        "injection_suspect": false,
        "notes": ["…"],                       # facts about extraction only
      },
      …
    ],
    "duplicates": [                           # repeated statements, kept & flagged
      {"id": "…", "duplicate_of": "…", "normalized_text": "…"}
    ],
    "contradictions": [
      {
        "topic": "language",
        "structured": {"id": "…", "text": "…", "source_field": "…", "modality": "…"},
        "described": {"id": "…", "text": "…", "source_field": "…", "modality": "…"},
        "kind": "structured_vs_description",  # exposed, never arbitrated
      }
    ],
    "application_deadline": {                 # factual passage or None
      "text": "original passage", "source_field": "…", "locator": "…",
      "date_iso": "2026-11-30" | null,
    },
    "injection_suspects": ["req_…", …],       # inert flagged excerpts
    "truncated": false,                       # input was clipped / ends mid sentence
    "warnings": ["…"],                        # extraction facts, user-readable
    "stats": {"by_modality": {"required": n, …}, "by_category": {"…": n, …}},
  }

STABILITY
Ids are ``req_`` + the first 16 hex chars of
``sha256("{offer_id}|{source_field}|{normalized statement}")``.  If the very
same statement appears twice in one offer, the first occurrence keeps the
plain id and later ones get a stable ``_<n>`` suffix — ids always stay
unique within an analysis. The same
offer always yields the same ids and the same ordering; there is no clock,
no randomness and no network in this package.
"""

from __future__ import annotations

CATEGORIES: frozenset[str] = frozenset(
    {
        "technical_skill",
        "language",
        "education",
        "experience",
        "availability",
        "mobility",
        "work_authorization",
        "other",
    }
)

MODALITIES: frozenset[str] = frozenset({"required", "preferred", "contextual", "unknown"})

SOURCE_FIELDS: frozenset[str] = frozenset(
    {
        "requirements",
        "description_original",
        "languages_required",
        "eligibility_requirement",
        "role_level",
        "deadline_date",
    }
)

# Structured fields carry board-structured data, so their statements start
# with high confidence.  Description prose is untrusted free text: only
# statement-level markers lift it above the uncertainty floor.
_BASE_CONFIDENCE: dict[str, float] = {
    "requirements": 0.90,
    "languages_required": 0.90,
    "eligibility_requirement": 0.90,
    "role_level": 0.90,
    "deadline_date": 0.85,
    "description_original": 0.80,
}

# A statement whose modality could not be established never claims more
# certainty than this.
UNKNOWN_CONFIDENCE_CAP = 0.40

ID_PREFIX = "req_"

SCHEMA_VERSION = "1"
