"""Comparateur d'offres côte à côte (SPEC-026).

Le module aligne des attributs normalisés entre plusieurs offres, calcule un
score pondéré configurable et produit un verdict lisible (classement + tie
breaker fraîcheur puis adéquation).  Tout est local et déterministe : aucune
requête réseau, aucun LLM, aucune donnée personnelle.  Les offres sont fournies
en mémoire (fixtures synthétiques ou payload REST).

Règles clés :

* un attribut absent vaut explicitement ``None`` (jamais ``0`` par défaut) ;
* les valeurs manquantes ou non numériques sont ignorées dans le score, sans
  pénalité artificielle ;
* ``weights`` rend la pondération entièrement configurable ; les attributs non
  listés pèsent ``0``.  Sans ``weights``, tous les attributs pèsent ``1`` ;
* les attributs « coût-like » (``risk``, ``cost``, ``price``, ``delay``…)
  sont considérés comme « plus bas = mieux », surchargeable via
  ``higher_is_better``.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from functools import cmp_to_key
from typing import Any, Mapping, Sequence

__all__ = [
    "CompareVerdict",
    "DecisionMatrix",
    "OfferRow",
    "compare_offers",
    "normalize_attr",
    "verdict_to_dict",
]

_MISSING = object()

_MISSING_TOKENS = frozenset(
    {
        "",
        "-",
        "--",
        "—",
        "–",
        "n/a",
        "na",
        "n.a.",
        "nc",
        "none",
        "null",
        "inconnu",
        "inconnue",
        "unknown",
        "non communiqué",
        "non communiquée",
        "à préciser",
        "a preciser",
    }
)
_TRUE_TOKENS = frozenset({"true", "oui", "yes", "y", "vrai"})
_FALSE_TOKENS = frozenset({"false", "non", "no", "n", "faux"})

_LOWER_IS_BETTER_HINTS = (
    "risk",
    "risque",
    "cost",
    "coût",
    "cout",
    "price",
    "prix",
    "delay",
    "délai",
    "delai",
    "distance",
    "penalty",
    "pénalité",
    "penalite",
    "fee",
    "frais",
    "charge",
    "commute",
    "trajet",
)

_TIE_BREAKER_ALIASES: dict[str, tuple[str, ...]] = {
    "freshness": ("fresh", "date", "posted", "publication", "recent", "fraicheur", "fraîcheur"),
    "fit": ("match", "adequation", "adéquation", "fit", "score", "compatibilite", "compatibilité"),
}

_ATTR_KEYS = ("attrs", "attributes", "metrics", "values", "scores")
_ID_KEYS = ("offer_id", "id", "name", "title", "label")


@dataclass
class OfferRow:
    """Une offre réduite à ses attributs normalisés."""

    offer_id: str
    attrs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.offer_id = str(self.offer_id or "").strip() or "offer"
        self.attrs = {
            str(key).strip(): normalize_attr(str(key).strip(), value)
            for key, value in dict(self.attrs or {}).items()
        }


@dataclass
class CompareVerdict:
    """Verdict renvoyé par :func:`compare_offers`."""

    matrix: dict[str, dict[str, Any]]
    weighted_scores: dict[str, float]
    ranking: list[str]
    tie_breaker_used: bool


def compare_offers(
    offers: Any,
    weights: Mapping[str, Any] | None = None,
    tie_breakers: Sequence[str] | str | None = None,
    higher_is_better: Mapping[str, bool] | None = None,
) -> CompareVerdict:
    """Compare ``offers`` et renvoie un :class:`CompareVerdict`.

    ``offers`` accepte une séquence d':class:`OfferRow`, une séquence de
    mappings, ou un mapping unique.  Un mapping peut contenir un sous-dict
    ``attrs``/``attributes``/``metrics``/``values`` ou directement les
    attributs (``offer_id``/``id``/``name``/``title`` étant réservés à
    l'identifiant).
    """

    return DecisionMatrix(
        offers=offers,
        weights=weights,
        tie_breakers=tie_breakers,
        higher_is_better=higher_is_better,
    ).compare()


@dataclass
class DecisionMatrix:
    """Matrice de décision configurable pour un ensemble d'offres."""

    offers: Any = field(default_factory=list)
    weights: Mapping[str, Any] | None = None
    tie_breakers: Sequence[str] | str | None = None
    higher_is_better: Mapping[str, bool] | None = None
    matrix: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    weighted_scores: dict[str, float] = field(default_factory=dict, init=False)
    ranking: list[str] = field(default_factory=list, init=False)
    tie_breaker_used: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self._rows = _to_rows(self.offers)
        self._attrs = _all_attrs(self._rows)
        self._weights = _normalise_weights(self.weights, self._attrs)
        self._higher = {str(key): bool(value) for key, value in (self.higher_is_better or {}).items()}
        if self.tie_breakers is None:
            self._tie_breakers = ["freshness", "fit"]
        elif isinstance(self.tie_breakers, str):
            self._tie_breakers = [self.tie_breakers]
        else:
            self._tie_breakers = [str(item) for item in self.tie_breakers]
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

    # -- internals ---------------------------------------------------------
    def _compute(self) -> None:
        rows = self._rows
        self.matrix = {attr: {row.offer_id: row.attrs.get(attr) for row in rows} for attr in self._attrs}
        self.weighted_scores = _weighted_scores(rows, self._attrs, self._weights, self._higher)
        self.tie_breaker_used = _tie_breaker_used(rows, self.weighted_scores, self._attrs, self._tie_breakers)
        self.ranking = _rank(rows, self.weighted_scores, self._attrs, self._tie_breakers)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def normalize_attr(*args: Any, **kwargs: Any) -> Any:
    """Normalise une valeur d'attribut.

    Formes acceptées ::

        normalize_attr(value)
        normalize_attr(attr_name, value)
        normalize_attr(mapping, attr_name)
        normalize_attr(attr=..., value=...)
    """

    attr = kwargs.get("attr", kwargs.get("name", kwargs.get("key")))
    raw = kwargs.get("value", kwargs.get("raw", _MISSING))
    positional = list(args)

    if len(positional) > 2:
        raise TypeError("normalize_attr accepte au plus 2 arguments positionnels.")

    if len(positional) == 1:
        candidate = positional[0]
        if isinstance(candidate, Mapping) and attr is not None:
            raw = candidate.get(str(attr))
        else:
            raw = candidate
    elif len(positional) == 2:
        first, second = positional
        if isinstance(first, Mapping):
            attr = second
            raw = first.get(str(second))
        elif isinstance(first, str):
            attr = first if attr is None else attr
            raw = second
        else:
            raw = second
    elif raw is _MISSING:
        raw = None

    if raw is _MISSING:
        raw = None
    return _normalize_value("value" if attr is None else str(attr), raw)


def _normalize_value(attr: str, raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        if isinstance(raw, float) and (math.isnan(raw) or math.isinf(raw)):
            return None
        return raw
    if isinstance(raw, datetime):
        return raw.isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    if isinstance(raw, (list, tuple, set)):
        items = list(raw)
        if not items:
            return None
        if all(isinstance(item, (int, float, bool)) and not isinstance(item, bool) for item in items):
            return items
        if all(isinstance(item, bool) for item in items):
            return items
        joined = ", ".join(text for text in (str(item).strip() for item in items) if text)
        return joined or None
    if isinstance(raw, Mapping):
        return json.dumps(dict(raw), sort_keys=True, ensure_ascii=False, default=str)
    if not isinstance(raw, str):
        return str(raw)

    text = re.sub(r"\s+", " ", raw.strip())
    if text.casefold() in _MISSING_TOKENS:
        return None
    lowered = text.casefold()
    if lowered in _TRUE_TOKENS:
        return True
    if lowered in _FALSE_TOKENS:
        return False

    parsed_date = _parse_date(text)
    if parsed_date is not None:
        return parsed_date

    number = _parse_number(text)
    if number is not None:
        return number
    return text


def _parse_date(text: str) -> str | None:
    candidate = text.strip()
    iso_candidate = candidate[:10]
    try:
        return date.fromisoformat(iso_candidate).isoformat()
    except ValueError:
        pass
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", candidate)
    if match:
        day, month, year = (int(part) for part in match.groups())
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None
    return None


def _parse_number(text: str) -> int | float | None:
    working = text.strip()
    if not working:
        return None
    multiplier = 1.0
    lowered = working.casefold()
    if lowered.endswith("%"):
        working = working[:-1].strip()
    for suffix, factor in (("k", 1_000.0), ("m", 1_000_000.0)):
        if lowered.endswith(suffix) and re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?\s*[kKmM]", working):
            multiplier = factor
            working = working[:-1].strip()
            break

    cleaned = re.sub(r"[^0-9,.\-+]", "", working)
    if not re.search(r"\d", cleaned):
        return None

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")

    try:
        value = float(cleaned) * multiplier
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    if value.is_integer() and "." not in cleaned:
        return int(value)
    return value


# ---------------------------------------------------------------------------
# Construction des lignes / pondération
# ---------------------------------------------------------------------------
def _to_rows(offers: Any) -> list[OfferRow]:
    if offers is None:
        return []
    if isinstance(offers, OfferRow):
        rows = [OfferRow(offers.offer_id, dict(offers.attrs))]
    elif isinstance(offers, Mapping):
        rows = [_row_from_mapping(offers, 0)]
    elif isinstance(offers, (str, bytes)):
        raise TypeError("Les offres doivent être une séquence de mappings, pas une chaîne.")
    else:
        try:
            items = list(offers)
        except TypeError as error:
            raise TypeError("Les offres doivent être une séquence de mappings ou d'OfferRow.") from error
        rows = []
        for index, item in enumerate(items):
            if isinstance(item, OfferRow):
                rows.append(OfferRow(item.offer_id, dict(item.attrs)))
            elif isinstance(item, Mapping):
                rows.append(_row_from_mapping(item, index))
            else:
                raise TypeError("Chaque offre doit être un mapping ou un OfferRow.")

    seen: set[str] = set()
    for row in rows:
        if row.offer_id in seen:
            raise ValueError(f"Identifiant d'offre dupliqué : {row.offer_id!r}.")
        seen.add(row.offer_id)
    return rows


def _row_from_mapping(item: Mapping[str, Any], index: int) -> OfferRow:
    attrs: Mapping[str, Any] | None = None
    for key in _ATTR_KEYS:
        candidate = item.get(key)
        if isinstance(candidate, Mapping):
            attrs = candidate
            break

    offer_id: Any = None
    for key in _ID_KEYS:
        if key in item and item.get(key) not in (None, ""):
            offer_id = item.get(key)
            break

    if attrs is None:
        reserved = set(_ID_KEYS) | set(_ATTR_KEYS)
        attrs = {str(key): value for key, value in item.items() if str(key) not in reserved}
    if offer_id is None:
        offer_id = f"offer_{index + 1}"
    return OfferRow(str(offer_id), dict(attrs or {}))


def _all_attrs(rows: Sequence[OfferRow]) -> list[str]:
    seen: set[str] = set()
    attrs: list[str] = []
    for row in rows:
        for key in row.attrs:
            if key not in seen:
                seen.add(key)
                attrs.append(key)
    return attrs


def _normalise_weights(weights: Mapping[str, Any] | None, attrs: Sequence[str]) -> dict[str, float]:
    if weights is None:
        return {attr: 1.0 for attr in attrs}

    resolved: dict[str, float] = {}
    for key, value in dict(weights).items():
        try:
            weight = float(value)
        except (TypeError, ValueError):
            weight = 0.0
        if math.isnan(weight) or math.isinf(weight):
            weight = 0.0
        resolved[str(key)] = weight

    # Tolérance casse / accents / séparateurs sur les noms d'attributs.
    result: dict[str, float] = {}
    for attr in attrs:
        weight = resolved.get(attr)
        if weight is None:
            needle = _norm_key(attr)
            for key, candidate in resolved.items():
                if _norm_key(key) == needle:
                    weight = candidate
                    break
        result[attr] = 0.0 if weight is None else weight
    # Conserve les poids explicites portant sur un attribut absent, pour
    # transparence côté appelant (ils ne contribuent simplement pas).
    for key, weight in resolved.items():
        if key not in result:
            result[key] = weight
    return result


def _looks_lower_better(attr: str) -> bool:
    needle = attr.casefold()
    return any(hint in needle for hint in _LOWER_IS_BETTER_HINTS)


def _weighted_scores(
    rows: Sequence[OfferRow],
    attrs: Sequence[str],
    weights: Mapping[str, float],
    higher_is_better: Mapping[str, bool],
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for row in rows:
        numerator = 0.0
        denominator = 0.0
        for attr in attrs:
            weight = weights.get(attr, 0.0)
            if not weight:
                continue
            value = row.attrs.get(attr)
            if value is None:
                continue
            number = _to_number(value)
            if number is None:
                continue
            higher = higher_is_better.get(attr)
            if higher is None:
                higher = not _looks_lower_better(attr)
            numerator += weight * (number if higher else -number)
            denominator += abs(weight)
        # Arrondi pour que deux offres réellement à égalité ne divergent pas
        # à cause du bruit flottant.
        scores[row.offer_id] = round(numerator / denominator, 6) if denominator else 0.0
    return scores


# ---------------------------------------------------------------------------
# Tie breakers + classement
# ---------------------------------------------------------------------------
def _resolve_attr(attrs: Sequence[str], breaker: str) -> str | None:
    if breaker in attrs:
        return breaker

    needle = _norm_key(breaker)
    for attr in attrs:
        if _norm_key(attr) == needle:
            return attr
    for attr in attrs:
        normalized = _norm_key(attr)
        if needle and (needle in normalized or normalized in needle):
            return attr
    for alias in _TIE_BREAKER_ALIASES.get(needle, ()):
        normalized_alias = _norm_key(alias)
        for attr in attrs:
            if normalized_alias and normalized_alias in _norm_key(attr):
                return attr
    return None


def _norm_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        parsed = _parse_number(value)
        return float(parsed) if parsed is not None else None
    return None


def _tie_value(attr: str | None, value: Any) -> Any:
    if value is None:
        return None
    number = _to_number(value)
    if number is not None:
        return number
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return value
    return value


def _tie_key(row: OfferRow, attrs: Sequence[str], breakers: Sequence[str]) -> tuple[Any, ...]:
    parts: list[Any] = []
    for breaker in breakers:
        attr = _resolve_attr(attrs, breaker)
        value = row.attrs.get(attr) if attr is not None else None
        parts.append(_tie_value(attr, value))
    return tuple(parts)


def _tie_breaker_used(
    rows: Sequence[OfferRow],
    scores: Mapping[str, float],
    attrs: Sequence[str],
    breakers: Sequence[str],
) -> bool:
    if not breakers:
        return False
    groups: dict[float, list[OfferRow]] = defaultdict(list)
    for row in rows:
        groups[scores[row.offer_id]].append(row)
    for group in groups.values():
        if len(group) < 2:
            continue
        keys = {_tie_key(row, attrs, breakers) for row in group}
        if len(keys) > 1:
            return True
    return False


def _compare_values(left: Any, right: Any) -> int:
    """Compare deux valeurs « plus grand = mieux » (-1, 0, 1)."""

    if left is None and right is None:
        return 0
    if left is None:
        return -1
    if right is None:
        return 1
    try:
        if left < right:
            return -1
        if left > right:
            return 1
        return 0
    except TypeError:
        left_text, right_text = str(left), str(right)
        return (left_text > right_text) - (left_text < right_text)


def _rank(
    rows: Sequence[OfferRow],
    scores: Mapping[str, float],
    attrs: Sequence[str],
    breakers: Sequence[str],
) -> list[str]:
    if not rows:
        return []
    keys = {row.offer_id: _tie_key(row, attrs, breakers) for row in rows}
    indexes = {row.offer_id: index for index, row in enumerate(rows)}

    def compare(left: OfferRow, right: OfferRow) -> int:
        left_score = scores[left.offer_id]
        right_score = scores[right.offer_id]
        if left_score != right_score:
            return -1 if left_score > right_score else 1
        left_key, right_key = keys[left.offer_id], keys[right.offer_id]
        for left_value, right_value in zip(left_key, right_key):
            result = _compare_values(left_value, right_value)
            if result:
                # Plus grand = mieux -> ordre décroissant.
                return -result
        return indexes[left.offer_id] - indexes[right.offer_id]

    return [row.offer_id for row in sorted(rows, key=cmp_to_key(compare))]


def verdict_to_dict(verdict: CompareVerdict) -> dict[str, Any]:
    """Sérialise un verdict en structure JSON-compatible."""

    return {
        "matrix": verdict.matrix,
        "weighted_scores": verdict.weighted_scores,
        "ranking": list(verdict.ranking),
        "tie_breaker_used": verdict.tie_breaker_used,
    }
