"""Precise requirement provenance for Career offers (CVBOOST-02).

Public API (pure Python, deterministic, no network, no model):

- ``analyze_offer(offer)`` — full documented contract for one offer dict:
  requirements with ``id``/``text``/``source_field``/``locator``/``category``
  /``modality``/``confidence``, plus duplicates, contradictions, application
  deadline, injection suspects, truncation flag, warnings and stats.
- ``resolve_locator(offer, source_field, locator)`` — verbatim source line a
  requirement's locator points to.
- ``split_source_lines(offer, source_field)`` — the lines locators refer to.
- ``load_fixtures()`` — the bundled multilingual synthetic offers used by the
  tests and the benchmark (``benchmark`` module).

The contract is documented in ``career/offer_requirements/contracts.py``.
`career/application_prep.py` can adopt this contract gradually: the
``requirements`` field of ``analyze_offer`` keeps ``text``/``source_field``
compatible with today's ``extract_requirements`` output while adding
provenance, so consumers can migrate record by record.
"""

from .contracts import (
    CATEGORIES,
    ID_PREFIX,
    MODALITIES,
    SCHEMA_VERSION,
    SOURCE_FIELDS,
    UNKNOWN_CONFIDENCE_CAP,
)
from .extract import analyze_offer, resolve_locator, split_source_lines
from .fixtures import load_fixtures

__all__ = [
    "analyze_offer",
    "CATEGORIES",
    "ID_PREFIX",
    "load_fixtures",
    "MODALITIES",
    "resolve_locator",
    "SCHEMA_VERSION",
    "split_source_lines",
    "SOURCE_FIELDS",
    "UNKNOWN_CONFIDENCE_CAP",
    "requirement_provenance",
]
__version__ = "1.0.0"


def requirement_provenance(
    analysis: dict, requirement_id: str, offer: dict
) -> dict:
    """Return the provenance block for one requirement id.

    Helpful for UIs that show "exigence n°N" today: the id resolves to the
    exact field, locator and verbatim passage.  Raises ``LookupError`` when
    the id is not part of the analysis — provenance is never guessed.
    """
    for record in analysis.get("requirements", []):
        if record.get("id") == requirement_id:
            passage = resolve_locator(offer, record["source_field"], record["locator"])
            return {
                "id": record["id"],
                "source_field": record["source_field"],
                "locator": record["locator"],
                "text": record["text"],
                "source_passage": passage,
                "heading": record["heading"],
                "category": record["category"],
                "modality": record["modality"],
                "confidence": record["confidence"],
                "negated": record["negated"],
            }
    raise LookupError(
        f"Provenance introuvable pour {requirement_id!r} : aucun passage n'est jamais deviné."
    )
