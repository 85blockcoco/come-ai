"""Local, deterministic comparison of job offers side by side (SPEC-026).

The module aligns normalised attributes across offers, computes a configurable
weighted score, and returns a readable verdict with a freshness + fit
tie-breaker.  No network, no LLM, no personal data: offers are supplied as
synthetic fixtures or in-memory dicts.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Mapping, Sequence

_MISSING = object()


@dataclass
class OfferRow:
    """One offer reduced to its normalised attributes."""

    offer_id: str
    attrs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.offer_id = str(self.offer_id or "").strip() or "offer"
        self.attrs = {
            str(key): normalize_attr(key, value)
            for key, value in (self.attrs or {}).items()
        }


@dataclass
class CompareVerdict:
    """Result of :func:`compare_offers`."""

    matrix: dict[str, dict[str, Any]]
    weighted_scores: dict[str, float]
    ranking: list[str]
    tie_breaker_used: bool


@dataclass
class DecisionMatrix:
    """Configurable decision matrix for a set of offers.

    ``offers`` may be :class:`OfferRow` instances, mappings with an ``attrs``
    (or ``attributes``/``metrics``/``values``) entry, or mappings whose keys
    are themselves attributes.  ``weights`` maps an attribute name to its
    weight; when ``None`` every attribute weighs ``1.0``.  When an explicit
    mapping is given, attributes absent from it weigh ``0.0`` so the score is
    fully configurable.  ``higher_is_better`` overrides the small heuristic
    used for cost-like attributes.
    """

    offers: Sequence[Any] = field(default_factory=list)
    weights: Mapping[str, Any] | None = None
    tie_breakers: Sequence[str] | None = None
    higher_is_better: Mapping[str, bool] | None = None
    matrix: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    weighted_scores: dict[str, float] = field(default_factory=dict, init=False)
    ranking: list[str] = field(default_factory=list, init=False)
    tie_breaker_used: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self._rows = _to_rows(self.offers)
        self._weights = _normalise_weights(self.weights, [attr for attr in _all_attrs(self._rows)])
        self._higher = dict(self.higher_is_better or {})
        self._tie_breakers = list(self.tie_breakers) if self.tie_breakers is not None else ["freshness", "fit"]
        self._compute()

    def compare(self) -> CompareVerdict:
        return CompareVerdict(
            matrix=self.matrix,
            weighted_scores=self.weighted_scores,
            ranking=list(self.ranking),
            tie_breaker_used=self.tie_breaker_used,
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self.compare())

    def _compute(self) -> None:
        rows = self._rows
        attrs = _all_attrs(rows)
        self.matrix = {attr: {row.offer_id: row.attrs.get(attr) for row in rows} for attr in attrs}

        lower_better_hints = ("risk", "cost", "price", "delay", "distance", "penalty", "charge", "fee", "days")
        scores: dict[str, float] = {}
        for row in rows:
            numerator = 0.0
            denominator = 0.0
            for attr in attrs:
                weight = self._weights.get(attr, 0.0 if self.weights is not None else 1.0)
                if not weight:
                    continue
                value = row.attrs.get(attr)
                if value is None:
                    continue
                higher = self._higher.get(attr)
                if higher is None:
                    higher = not any(hint in attr.casefold() for hint in lower_better_hints)
                number = _to_number(value)
                if number is None:
                    continue
                contribution = number if higher else -number
                numerator += float(weight) * contribution
                denominator += abs(float(weight))
            if denominator > 0:
                scores[row.offer_id] = float(numerator / denominator)
            else:
                scores[row.offer_id] = 0.0
        self.weighted_scores = scores

        # Stable order by input, then score desc, then tie-breakers.
        indexed = list(enumerate(rows))
        tie_used = False
        # Detect ties first.
        score_groups: dict[float, list[int]] = {}
        for index, row in indexed:
            score_groups.setdefault(scores[row.offer_id], []).append(index)

        for score, indices in score_groups.items():
            if len(indices) < 2:
                continue
            # Compare breaker tuples across rows in this group.
            tuples = []
            for index in indices:
                row = rows[index]
                keyparts = []
                for breaker in self._tie_breakers:
                    attr = _resolve_attr(attrs, breaker)
                    value = row.attrs.get(attr) if attr is not None else None
                    keyparts.append(_tie_break_value(attr or "", value))
                tuples.append(tuple(keyparts))
            if len(set(_jsonable_key(t) for t in tuples)) > 1:
                tie_used = True

        def sort_key(item: tuple[int, OfferRow]) -> tuple[Any, ...]:
            index, row = item
            score = scores[row.offer_id]
            tieparts: list[Any] = []
            for breaker in self._tie_breakers:
                attr = _resolve_attr(attrs, breaker)
                value = row.attrs.get(attr) if attr is not None else None
                cmp_value = _tie_break_value(attr or "", value)
                # descending: store negated when possible
                if isinstance(cmp_value, (int, float)) and not isinstance(cmp_value, bool):
                    tieparts.append(-cmp_value)
                elif isinstance(cmp_value, date):
                    tieparts.append(cmp_value.toordinal() * -1)
                else:
                    tieparts.append(0)
            return (-score, *tieparts, index)

        ordered = sorted(indexed, key=sort_key)
        self.ranking = [row.offer_id for _, row in ordered]
        self.tie_breaker_used = tie_used


def compare_offers(
    offers: Any,
    weights: Any = None,
    *,
    tie_breakers: Sequence[str] | None = None,
    higher_is_better: Mapping[str, bool] | None = None,
    **kwargs: Any,
) -> CompareVerdict:
    """Compare ``offers`` and return a :class:`CompareVerdict`.

    ``weights`` may be passed positionally or as ``weights=``.  Additional
    keyword arguments are forwarded to :class:`DecisionMatrix`.
    """
    if weights is None and "weights" in kwargs:
        weights = kwargs.pop("weights")
    if tie_breakers is None and "tie_breakers" in kwargs:
        tie_breakers = kwargs.pop("tie_breakers")
    if higher_is_better is None and "higher_is_better" in kwargs:
        higher_is_better = kwargs.pop("higher_is_better")
    matrix = DecisionMatrix(
        offers=offers,
        weights=weights,
        tie_breakers=tie_breakers,
        higher_is_better=higher_is_better,
    )
    return matrix.compare()


def normalize_attr(*args: Any, **kwargs: Any) -> Any:
    """Normalise one attribute value.

    Accepted forms::

        normalize_attr(value)
        normalize_attr(attr_name, value)
        normalize_attr(mapping, attr_name)
        normalize_attr(attr=..., value=...)
    """
    attr = kwargs.get("attr", kwargs.get("name", kwargs.get("key")))
    value = kwargs.get("value", kwargs.get("raw", _MISSING))
    positional = list(args)

    if len(positional) == 1:
        if isinstance(positional[0], dict) and attr is not None:
            raw = positional[0].get(attr)
        else:
            raw = positional[0]
    elif len(positional) == 2:
        if isinstance(positional[0], dict) and isinstance(positional[1], str):
            attr = positional[1]
            raw = positional[0].get(positional[1])
        elif isinstance(positional[0], str):
            if attr is None:
                attr = positional[0]
            raw = positional[1]
        else:
            raw = positional[1]
            if attr is None and isinstance(positional[0], str):
                attr = positional[0]
    else:
        raw = None

    if value is not _MISSING:
        raw = value
    if attr is None:
        attr = "value"
    return _normalize_value(str(attr), raw)


def _normalize_value(attr: str, raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        if isinstance(raw, float) and (math.isnan(raw) or math.isinf(raw)):
            return None
        return raw
    if isinstance(raw, (date,)):
        return raw.isoformat()
    if isinstance(raw, (list, tuple, set)):
        items = list(raw)
        if not items:
            return None
        if all(isinstance(item, (int, float, bool)) for item in items):
            return [item for item in items]
        return ", ".join(str(item).strip() for item in items if str(item).strip())
    if isinstance(raw, dict):
        return str(raw)
    if not isinstance(raw, str):
        return str(raw)

    text = raw.strip()
    if not text:
        return None
    lowered = text.casefold()
    if lowered in {"none", "null", "n/a", "na", "n.a.", "-", "—", "inconnu", "unknown"}:
        return None
    if lowered in {"true", "oui", "yes"}:
        return True
    if lowered in {"false", "non", "no"}:
        return False

    # Dates.
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        pass

    number = _parse_number(text)
    if number is not None:
        # Keep integers integral when the source was integral.
        if float(number).is_integer() and not any(ch in text for ch in (".", ",")):
            # Preserve scale suffixes such as "50k" as numbers (already scaled).
            return int(number)
        return number
    return re.sub(r"\s+", " ", text)


def _parse_number(text: str) -> float | None:
    working = text.strip()
    multiplier = 1.0
    if working.lower().endswith("k"):
        multiplier = 1000.0
        working = working[:-1].strip()
    # Remove everything except digits, separators and sign.
    cleaned = re.sub(r"[^0-9,.\-]", "", working)
    if not cleaned or cleaned in {"-", ".", ","}:
        return None
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned) * multiplier
    except ValueError:
        return None


def _to_rows(offers: Any) -> list[OfferRow]:
    if offers is None:
        return []
    if isinstance(offers, (OfferRow,)):
        return [offers]
    if isinstance(offers, Mapping):
        # Single offer mapping.
        offers = [offers]
    rows: list[OfferRow] = []
    for index, item in enumerate(list(offers)):
        if isinstance(item, OfferRow):
            rows.append(OfferRow(item.offer_id, dict(item.attrs)))
            continue
        if not isinstance(item, Mapping):
            raise TypeError("Chaque offre doit être un mapping ou un OfferRow.")
        attrs: dict[str, Any] | None = None
        offer_id: Any = None
        for key in ("attrs", "attributes", "metrics", "values", "scores", "attributes_map"):
            if key in item and isinstance(item.get(key), Mapping):
                attrs = dict(item[key])
                break
        if "offer_id" in item:
            offer_id = item.get("offer_id")
        elif "id" in item:
            offer_id = item.get("id")
        elif "name" in item:
            offer_id = item.get("name")
        elif "title" in item:
            offer_id = item.get("title")
        if attrs is None:
            id_keys = {"offer_id", "id", "name", "title", "label"}
            attrs = {str(k): v for k, v in item.items() if str(k) not in id_keys}
        if offer_id is None:
            offer_id = f"offer_{index + 1}"
        rows.append(OfferRow(str(offer_id), attrs or {}))
    return rows


def _all_attrs(rows: Sequence[OfferRow]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for row in rows:
        for key in row.attrs:
            if key not in seen:
                seen.add(key)
                result.append(key)
    return result


def _normalise_weights(weights: Any, attrs: Sequence[str]) -> dict[str, float]:
    if weights is None:
        return {attr: 1.0 for attr in attrs}
    result: dict[str, float] = {}
    for key, value in dict(weights).items():
        try:
            result[str(key)] = float(value)
        except (TypeError, ValueError):
            result[str(key)] = 0.0
    for attr in attrs:
        result.setdefault(attr, 0.0)
    return result


def _resolve_attr(attrs: Sequence[str], breaker: str) -> str | None:
    if breaker in attrs:
        return breaker
    needle = _norm_key(breaker)
    for attr in attrs:
        if _norm_key(attr) == needle:
            return attr
    # Substring match.
    for attr in attrs:
        if needle and needle in _norm_key(attr):
            return attr
    for attr in attrs:
        if _norm_key(attr) and _norm_key(attr) in needle:
            return attr
    # Common aliases.
    aliases = {
        "freshness": ("fresh", "date", "posted", "deadline", "recent"),
        "fit": ("match", "adequation", "adéquation", "score"),
    }
    for alias in aliases.get(needle, ()):
        for attr in attrs:
            if alias in _norm_key(attr):
                return attr
    return None


def _norm_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    if isinstance(value, str):
        number = _parse_number(value)
        return number
    return None


def _tie_break_value(attr: str, value: Any) -> Any:
    if value is None:
        return None
    number = _to_number(value)
    if number is not None:
        return number
    if isinstance(value, str):
        # Try date.
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return value
    return value


def _jsonable_key(value: Any) -> str:
    if isinstance(value, tuple):
        return str(tuple(_jsonable_key(item) for item in value))
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return "None"
    return repr(value)


def as_dict(verdict: CompareVerdict) -> dict[str, Any]:
    return {
        "matrix": verdict.matrix,
        "weighted_scores": verdict.weighted_scores,
        "ranking": list(verdict.ranking),
        "tie_breaker_used": verdict.tie_breaker_used,
    }
