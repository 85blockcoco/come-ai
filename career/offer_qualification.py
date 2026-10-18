"""Conservative, source-attributed qualification of internship offers.

This module only classifies facts present in a source payload. It does not
search the web, infer missing dates, or turn a high relevance score into proof
that a role is an internship.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from .exploration import _SENIOR_TITLE, classify_internship
from .models import canonical_url, clean_text


@dataclass(frozen=True)
class FactEvidence:
    value: Any
    source: str
    quote: str = ""


@dataclass(frozen=True)
class QualifiedOffer:
    contract_type: str
    contract_status: str
    posted_date: str | None
    start_date: str | None
    end_date: str | None
    start_month: int | None
    duration_min_months: int | None
    duration_max_months: int | None
    language: str | None
    country: str | None
    city: str | None
    source_name: str
    source_id: str
    official_url: str
    verification_status: str
    target_status: str
    missing_fields: tuple[str, ...]
    provenance: dict[str, FactEvidence]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CONTRACT_PATTERNS = (
    ("apprenticeship", re.compile(r"\b(?:alternance|apprenticeship|apprentice|apprenti(?:e)?)\b", re.I)),
    ("graduate", re.compile(r"\bgraduate\b", re.I)),
    ("VIE", re.compile(r"\bVIE\b|volontariat international en entreprise", re.I)),
    ("permanent", re.compile(r"\b(?:CDI|permanent(?:\s+(?:role|position|contract))?|indefinite[- ]term)\b", re.I)),
    ("fixed_term", re.compile(r"\b(?:CDD|fixed[- ]term contract)\b", re.I)),
)
_MONTHS = {
    "january": 1, "janvier": 1, "januar": 1, "gennaio": 1, "enero": 1,
    "february": 2, "fevrier": 2, "februar": 2, "febbraio": 2, "febrero": 2,
    "march": 3, "mars": 3, "marz": 3, "marzo": 3, "abril": 4, "april": 4,
    "avril": 4, "aprile": 4, "may": 5, "mai": 5, "maggio": 5, "mayo": 5,
    "june": 6, "juin": 6, "juni": 6, "giugno": 6, "junio": 6,
    "july": 7, "juillet": 7, "juli": 7, "luglio": 7, "julio": 7,
    "august": 8, "aout": 8, "agosto": 8, "september": 9, "septembre": 9,
    "settembre": 9, "septiembre": 9, "october": 10, "octobre": 10,
    "oktober": 10, "ottobre": 10, "octubre": 10, "november": 11,
    "novembre": 11, "noviembre": 11, "december": 12, "decembre": 12,
    "dezember": 12, "dicembre": 12, "diciembre": 12,
}
_START_MONTH_PATTERN = re.compile(
    r"\b(?:start(?:s|ing)?(?:\s+date)?|begin(?:s|ning)?|d[eé]but(?:e|er|ant)?|[aà]\s+partir|"
    r"prise\s+de\s+fonction|ab|inizio|inicio)\s*(?:[:=-]\s*)?"
    r"(?:(?:in|from|on|en|de|du|le|the|dal|da|el)\s+)*(?:\d{1,2}\s+)?"
    r"(?P<month>" + "|".join(sorted((*_MONTHS, "février", "märz", "août"), key=len, reverse=True)) +
    r")\b(?:\s+(?P<year>20\d{2}))?", re.I)
_NUMBER_WORDS = {"one": 1, "un": 1, "une": 1, "einen": 1, "due": 2, "deux": 2,
                 "two": 2, "drei": 3, "trois": 3, "three": 3, "quattro": 4,
                 "quatre": 4, "four": 4, "cinque": 5, "cinq": 5, "five": 5,
                 "sechs": 6, "six": 6, "sei": 6, "seis": 6, "sieben": 7,
                 "sette": 7, "siete": 7, "acht": 8, "otto": 8, "ocho": 8,
                 "neun": 9, "nove": 9, "nueve": 9, "zehn": 10, "dix": 10,
                 "dieci": 10, "diez": 10, "elf": 11, "undici": 11, "once": 11,
                 "zwolf": 12, "douze": 12, "twelve": 12, "dodici": 12, "doce": 12}
_DURATION = re.compile(
    r"\b(?P<low>\d{1,2}|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) +
    r")\s*(?:[-–—]|to|à|a|bis|hasta|al)?\s*(?P<high>\d{1,2}|" +
    "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) +
    r")?\s*(?:months?|mois|monate|mesi|meses)\b", re.I)


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text.lower())
                   if not unicodedata.combining(ch))


def _number(value: str | None) -> int | None:
    if not value:
        return None
    if value.isdigit():
        number = int(value)
        return number if 1 <= number <= 24 else None
    number = _NUMBER_WORDS.get(_fold(value))
    return number if number and number <= 24 else None


def qualify_offer(offer: dict[str, Any], *, minimum_duration_months: int = 6,
                  required_start_month: int | None = None,
                  allowed_contract_types: list[str] | tuple[str, ...] | None = None,
                  allowed_start_months: list[int] | tuple[int, ...] | None = None,
                  minimum_stage_duration_months: int | None = None,
                  as_of: date | None = None) -> QualifiedOffer:
    """Qualify a normalized offer against explicit user-configurable criteria.

    ``source_verified`` must be set by a connector after a successful read of
    its official feed. Synthetic inputs can set it only to test this decision
    path; such tests are not evidence of live source coverage.
    """
    if not isinstance(offer, dict):
        raise TypeError("offer must be an object")
    if not 1 <= minimum_duration_months <= 24:
        raise ValueError("qualification limits are outside the supported range")
    if minimum_stage_duration_months is None:
        minimum_stage_duration_months = minimum_duration_months
    if not 1 <= minimum_stage_duration_months <= 24:
        raise ValueError("internship duration limit is outside the supported range")
    if allowed_start_months is None:
        allowed_start_months = [required_start_month] if required_start_month is not None else [1, 2, 3]
    if any(type(month) is not int or not 1 <= month <= 12 for month in allowed_start_months):
        raise ValueError("allowed start months must be integers from 1 to 12")
    if allowed_contract_types is None:
        allowed_contract_types = ["stage", "cdd", "cdi", "vie"]
    aliases = {"stage": "internship", "cdd": "fixed_term", "cdi": "permanent", "vie": "VIE"}
    allowed_contract_types = tuple(dict.fromkeys(aliases.get(str(item).strip().casefold(), str(item).strip())
                                                 for item in allowed_contract_types))
    today = as_of or date.today()
    description = clean_text(offer.get("description_original"), limit=30_000)
    title = clean_text(offer.get("title"), limit=300)
    employment = clean_text(offer.get("employment_type"), limit=120)
    evidence: dict[str, FactEvidence] = {}
    missing: list[str] = []

    def field(name: str, label: str | None = None) -> str | None:
        value = clean_text(offer.get(name), limit=240)
        if value:
            evidence[name] = FactEvidence(value, f"source_field:{name}")
            return value
        missing.append(label or name)
        return None

    posted_date = field("posted_date", "publication")
    start_date = field("start_date", "début")
    end_date = field("end_date", "fin")
    parsed_start: date | None = None
    parsed_end: date | None = None
    if start_date:
        try:
            parsed_start = date.fromisoformat(start_date)
        except ValueError:
            start_date = None
            missing.append("début")
    if end_date:
        try:
            parsed_end = date.fromisoformat(end_date)
        except ValueError:
            end_date = None
            missing.append("fin")
    start_month: int | None = None
    if parsed_start:
        start_month = parsed_start.month
        if parsed_start < today:
            start_month = -parsed_start.month  # a past start is explicitly non-conforming
    if start_month is None and description:
        month_match = _START_MONTH_PATTERN.search(description)
        if month_match:
            start_month = _MONTHS.get(_fold(month_match.group("month")))
            evidence["start_month"] = FactEvidence(start_month, "description_passage", month_match.group(0))
            year = month_match.group("year")
            if year:
                evidence["start_year"] = FactEvidence(int(year), "description_passage", month_match.group(0))
                if (int(year), start_month) < (today.year, today.month):
                    start_month = -start_month
                elif (int(year), start_month) == (today.year, today.month):
                    missing.append("jour de début vérifiable")
            else:
                missing.append("année de début")
    if start_month is None:
        missing.append("mois de début")
    elif "start_month" not in evidence:
        evidence["start_month"] = FactEvidence(start_month, "source_field:start_date", start_date or "")

    low = offer.get("duration_min_months")
    high = offer.get("duration_max_months")
    duration = offer.get("duration_months")
    if type(duration) is int and 1 <= duration <= 24:
        low = high = duration
        evidence["duration_min_months"] = FactEvidence(low, "source_field:duration_months")
        evidence["duration_max_months"] = FactEvidence(high, "source_field:duration_months")
    elif type(low) is int and 1 <= low <= 24 and type(high) is int and low <= high <= 24:
        evidence["duration_min_months"] = FactEvidence(low, "source_field:duration_min_months")
        evidence["duration_max_months"] = FactEvidence(high, "source_field:duration_max_months")
    elif description:
        duration_match = _DURATION.search(description)
        if duration_match:
            low = _number(duration_match.group("low"))
            high = _number(duration_match.group("high")) or low
            if low is not None and high is not None and low <= high:
                quote = duration_match.group(0)
                evidence["duration_min_months"] = FactEvidence(low, "description_passage", quote)
                evidence["duration_max_months"] = FactEvidence(high, "description_passage", quote)
                prefix = _fold(description[max(0, duration_match.start() - 30):duration_match.start()])
                if re.search(r"(?:up to|at most|jusqu['’]a|maximum|max\.?|bis zu)\s*$", prefix):
                    # A published ceiling never establishes a guaranteed minimum.
                    evidence.pop("duration_min_months", None)
                    evidence.pop("duration_max_months", None)
                    evidence["duration_ceiling_months"] = FactEvidence(high, "description_passage", quote)
                    low = high = None
    if low is None and high is None and parsed_start and parsed_end:
        month_span = (parsed_end.year - parsed_start.year) * 12 + parsed_end.month - parsed_start.month
        completed_months = month_span - int(parsed_end.day < parsed_start.day)
        if 1 <= completed_months <= month_span <= 24:
            low, high = completed_months, month_span
            quote = f"{start_date} → {end_date}"
            evidence["duration_min_months"] = FactEvidence(low, "source_date_range", quote)
            evidence["duration_max_months"] = FactEvidence(high, "source_date_range", quote)
    if not (type(low) is int and type(high) is int and 1 <= low <= high <= 24):
        low = high = None
        missing.append("durée")

    language = field("language", "langue")
    country = field("country", "pays")
    city = field("city", "ville")
    source_name = clean_text(offer.get("source_name"), limit=60)
    source_id = clean_text(offer.get("source_id"), limit=240)
    raw_url = clean_text(offer.get("official_url"), limit=2_000)
    try:
        official_url = canonical_url(raw_url) if raw_url else ""
    except Exception:
        official_url = ""
    verification = "verified" if bool(offer.get("source_verified")) and official_url and source_name and source_id else "unverified"
    if not official_url:
        missing.append("lien officiel valide")

    explicit_matches = [(kind, label, pattern.search(text))
                        for label, text in (("source_field:employment_type", employment), ("title_passage", title))
                        for kind, pattern in _CONTRACT_PATTERNS]
    explicit_matches = [(kind, label, match) for kind, label, match in explicit_matches if match]
    explicit_kinds = list(dict.fromkeys(kind for kind, _, _ in explicit_matches))
    contract_type = "unknown"
    if len(explicit_kinds) > 1:
        contract_type = "ambiguous"
    elif explicit_kinds:
        contract_type = explicit_kinds[0]
        _, label, matched = next(item for item in explicit_matches if item[0] == contract_type)
        evidence["contract_type"] = FactEvidence(contract_type, label, matched.group(0))
    else:
        description_matches = [(kind, pattern.search(description)) for kind, pattern in _CONTRACT_PATTERNS
                               if kind != "graduate"]
        description_matches = [(kind, match) for kind, match in description_matches if match]
        description_kinds = list(dict.fromkeys(kind for kind, _ in description_matches))
        if len(description_kinds) > 1:
            contract_type = "ambiguous"
        elif description_kinds:
            contract_type = description_kinds[0]
            matched = next(match for kind, match in description_matches if kind == contract_type)
            evidence["contract_type"] = FactEvidence(contract_type, "description_passage", matched.group(0))
    internship = classify_internship({**offer, "title": title, "employment_type": employment,
                                      "description_original": description})
    # A posting cannot be both an internship and a different explicit
    # contract. Keep the contradiction visible instead of letting the selected
    # contract checkbox turn a mislabeled role into a confirmed match.
    has_stage_marker = bool(re.search(r"\b(?:intern(?:ship)?s?|stagiaires?|stages?)\b", _fold(title + " " + employment)))
    if contract_type != "unknown" and contract_type != "internship" and has_stage_marker:
        contract_type = "ambiguous"
    if contract_type == "ambiguous":
        evidence["contract_type"] = FactEvidence(
            "ambiguous", "conflicting_contract_passages", clean_text(" ".join((employment, title)), limit=600)
        )
    if contract_type == "unknown" and internship["status"] == "confirmed":
        contract_type = "internship"
        item = internship["evidence"][0] if internship["evidence"] else {"field": "title", "quote": title}
        evidence["contract_type"] = FactEvidence("internship", f"{item['field']}_passage", item["quote"])
    elif contract_type == "unknown" and re.search(r"\bgraduate\b", _fold(title + " " + employment)):
        evidence["contract_type"] = FactEvidence("graduate role ambiguous", "title_or_contract_passage", title or employment)

    reasons: list[str] = []
    target_status = "to_verify"
    if clean_text(offer.get("source_status"), limit=40).casefold() == "closed" or \
            clean_text(offer.get("deadline_status"), limit=40).casefold() == "closed":
        target_status = "non_conforming"
        reasons.append("La source indique que l’offre est clôturée.")
    deadline = clean_text(offer.get("deadline_date"), limit=32)
    if deadline and target_status != "non_conforming":
        try:
            if date.fromisoformat(deadline[:10]) < today:
                target_status = "non_conforming"
                reasons.append("La date limite de candidature est passée.")
        except ValueError:
            missing.append("date limite vérifiable")
    if target_status != "non_conforming" and _SENIOR_TITLE.search(title):
        target_status = "non_conforming"
        reasons.append("Le niveau senior ou d’encadrement ne correspond pas à la recherche.")
    if (target_status != "non_conforming" and contract_type == "internship" and high is not None
            and high < minimum_stage_duration_months):
        target_status = "non_conforming"
        reasons.append(f"La durée maximale connue est inférieure à {minimum_stage_duration_months} mois.")
    if target_status != "non_conforming" and contract_type == "ambiguous":
        reasons.append("Plusieurs types de contrat sont indiqués ; vérification nécessaire.")
    elif target_status != "non_conforming" and contract_type == "unknown":
        reasons.append("Le type de contrat n’est pas suffisamment explicite.")
    elif target_status != "non_conforming" and contract_type not in allowed_contract_types:
        target_status = "non_conforming"
        reasons.append(f"Le type de contrat {contract_type} n’est pas sélectionné dans tes critères.")
    elif target_status != "non_conforming" and contract_type == "internship" and internship["status"] == "excluded":
        target_status = "non_conforming"
        reasons.append(internship["reason"])
    elif target_status != "non_conforming" and start_month is None:
        reasons.append("Le mois de début n’est pas connu ; vérification nécessaire.")
    elif target_status != "non_conforming" and start_month is not None and start_month < 0:
        target_status = "non_conforming"
        reasons.append("La date de début est déjà passée.")
    elif target_status != "non_conforming" and start_month not in allowed_start_months:
        target_status = "non_conforming"
        reasons.append(f"Le mois de début ({start_month}) n’est pas sélectionné dans tes critères.")
    elif target_status != "non_conforming" and ("année de début" in missing or "jour de début vérifiable" in missing):
        reasons.append("La date de début est trop imprécise pour confirmer la période.")
    elif target_status != "non_conforming" and contract_type == "internship" and low is not None and high is not None:
        if high < minimum_stage_duration_months:
            target_status = "non_conforming"
            reasons.append(f"La durée maximale connue est inférieure à {minimum_stage_duration_months} mois.")
        elif low < minimum_stage_duration_months:
            reasons.append(f"La durée varie autour du seuil de {minimum_stage_duration_months} mois ; à vérifier.")
        elif verification != "verified":
            reasons.append("La source officielle ou le lien ne sont pas vérifiés.")
        else:
            target_status = "conforming"
            reasons.append("Stage confirmé, mois sélectionné et durée minimale satisfaite sur la source vérifiée.")
    elif target_status != "non_conforming" and contract_type == "internship":
        reasons.append("La durée du stage reste inconnue ; vérification nécessaire.")
    elif target_status != "non_conforming" and start_month is not None and verification == "verified":
        target_status = "conforming"
        reasons.append("Type de contrat et mois sélectionnés satisfaits sur la source vérifiée.")
    elif target_status != "non_conforming":
        reasons.append("La source officielle ou le lien reste à vérifier.")

    return QualifiedOffer(
        contract_type=contract_type,
        contract_status=internship["status"],
        posted_date=posted_date,
        start_date=start_date,
        end_date=end_date,
        start_month=abs(start_month) if start_month is not None else None,
        duration_min_months=low,
        duration_max_months=high,
        language=language,
        country=country,
        city=city,
        source_name=source_name,
        source_id=source_id,
        official_url=official_url,
        verification_status=verification,
        target_status=target_status,
        missing_fields=tuple(dict.fromkeys(missing)),
        provenance=evidence,
        reasons=tuple(reasons),
    )
