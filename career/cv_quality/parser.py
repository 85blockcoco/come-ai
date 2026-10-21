"""Text extraction from PDF, DOCX, and TXT files.

Pure local extraction — no network, no LLM, no external APIs.
Reuses pypdf (PDF) and python-docx (DOCX) if available.

Also hosts the remuneration extractor (CVBOOST-16): ``extract_salary()``
reads salaries, packages and variable components from a free-text offer
description, with exact provenance. Pure, deterministic, offline.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import NamedTuple, cast

from .models import (
    Currency,
    DocumentInput,
    Finding,
    Periodicity,
    SalaryEvidence,
    SalaryType,
    STATUS_RISK,
)


# Optional dependencies — handled gracefully
try:
    import pypdf
    HAS_PYPDF = True
except ImportError:  # pragma: no cover
    HAS_PYPDF = False

try:
    import docx
    HAS_DOCX = True
except ImportError:  # pragma: no cover
    HAS_DOCX = False


def extract_text_from_bytes(data: bytes, filetype: str, filename: str | None = None) -> DocumentInput:
    """Extract text from raw bytes based on filetype.

    Args:
        data: Raw file bytes.
        filetype: One of "txt", "pdf", "docx".
        filename: Original filename for provenance.

    Returns:
        DocumentInput with extracted text and metadata.

    Raises:
        ValueError: If filetype is unsupported or extraction fails.
    """
    if filetype == "txt":
        text = _extract_txt(data)
        page_count = _estimate_pages_txt(text)
    elif filetype == "pdf":
        text, page_count = _extract_pdf(data)
    elif filetype == "docx":
        text, page_count = _extract_docx(data)
    else:
        raise ValueError(f"Unsupported filetype: {filetype}")

    return DocumentInput(
        text=text,
        filename=filename,
        filetype=filetype,
        page_count=page_count,
    )


def extract_text_from_file(path: Path | str) -> DocumentInput:
    """Extract text from a file path, inferring type from extension.

    Args:
        path: Path to the file.

    Returns:
        DocumentInput with extracted text and metadata.

    Raises:
        ValueError: If file extension is unsupported or file not found.
        FileNotFoundError: If the file doesn't exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".txt":
        filetype = "txt"
    elif suffix == ".pdf":
        filetype = "pdf"
    elif suffix in (".docx", ".doc"):
        filetype = "docx"
    else:
        raise ValueError(f"Unsupported file extension: {suffix}")

    data = path.read_bytes()
    return extract_text_from_bytes(data, filetype, filename=path.name)


def _extract_txt(data: bytes) -> str:
    """Extract text from plain text bytes (UTF-8, fallback to latin-1)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def _estimate_pages_txt(text: str) -> int | None:
    """Estimate page count for plain text (approx 3000 chars/page)."""
    if not text:
        return 1
    # Rough estimate: ~3000 characters per A4 page
    return max(1, (len(text) // 3000) + 1)


def _extract_pdf(data: bytes) -> tuple[str, int]:
    """Extract text from PDF bytes using pypdf.

    Returns:
        Tuple of (extracted_text, page_count).

    Raises:
        ValueError: If pypdf is not available or PDF is invalid.
    """
    if not HAS_PYPDF:
        raise ValueError("PDF extraction requires 'pypdf' package. Install with: pip install pypdf")

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        page_count = len(reader.pages)
        texts = []
        for page in reader.pages:
            try:
                page_text = page.extract_text()
                if page_text:
                    texts.append(page_text)
            except Exception:
                # Skip pages that fail to extract
                continue
        return "\n\n".join(texts), page_count
    except Exception as e:
        raise ValueError(f"Failed to parse PDF: {e}") from e


def _extract_docx(data: bytes) -> tuple[str, int]:
    """Extract text from DOCX bytes using python-docx.

    Returns:
        Tuple of (extracted_text, page_count_estimate).

    Raises:
        ValueError: If python-docx is not available or DOCX is invalid.
    """
    if not HAS_DOCX:
        raise ValueError("DOCX extraction requires 'python-docx' package. Install with: pip install python-docx")

    try:
        doc = docx.Document(io.BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        # Also extract text from tables
        table_texts = []
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text for cell in row.cells)
                if row_text.strip():
                    table_texts.append(row_text)

        all_text = "\n".join(paragraphs + table_texts)
        # Rough page estimate for DOCX: ~3000 chars per page
        page_count = max(1, (len(all_text) // 3000) + 1)
        return all_text, page_count
    except Exception as e:
        raise ValueError(f"Failed to parse DOCX: {e}") from e


def create_parse_error_finding(error: Exception, filetype: str, filename: str | None = None) -> Finding:
    """Create a Finding for a parsing error."""
    msg = str(error)
    excerpt = msg[:50] if msg else "Unknown parsing error"
    return Finding(
        code="PARSE_ERROR",
        status=STATUS_RISK,
        message=f"Failed to extract text from {filetype.upper()}: {msg}",
        source_offset=0,
        source_excerpt=excerpt,
        metadata={"filetype": filetype, "filename": filename, "error_type": type(error).__name__},
    )


# ═══════════════════════════════════════════════════════════════════════
# CVBOOST-16 — Extracteur de rémunération (offres)
#
# Fonction pure et déterministe : aucun réseau, aucun LLM, aucun disque.
# Règle de fond : rien n'est inventé. Une devise absente reste absente,
# un montant sans devise explicite n'est pas converti, une absence de
# résultat donne une liste vide.
# ═══════════════════════════════════════════════════════════════════════


HOURS_PER_YEAR = 1820
"""Heures travaillées par an retenues pour annualiser un taux horaire.

Convention fixe et documentée : 35 h/semaine × 52 semaines. Elle ne sert
qu'aux montants horaires, dont la périodicité est explicitement écrite
dans le texte.
"""

_CURRENCY_SYMBOLS: dict[str, str] = {
    "€": "EUR",
    "$": "USD",
    "£": "GBP",
    "¥": "JPY",
}

_CURRENCY_CODES: dict[str, str] = {
    "EUR": "EUR",
    "USD": "USD",
    "GBP": "GBP",
    "JPY": "JPY",
    "CHF": "CHF",
    "CAD": "CAD",
    "AUD": "AUD",
    "SEK": "SEK",
    "NOK": "NOK",
    "DKK": "DKK",
    "PLN": "PLN",
    "INR": "INR",
    "CNY": "CNY",
    "RMB": "CNY",
}

_CURRENCY_TOKEN = (
    r"(?:[€$£¥]"
    r"|\b(?:EUR|euros?|USD|dollars?|GBP|pounds?|JPY|yens?|CHF|CAD|AUD|SEK|NOK|DKK|PLN|INR|CNY|RMB)\b)"
)

# Montants : séparateur de milliers (espace, virgule ou point) puis, ou
# non, partie décimale. « 45 000 », « 45,000 », « 45.000 », « 1.5 », « 45,50 ».
_NUMBER_PATTERN = r"""
    (?:
        \d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d{1,2})?
      | \d{1,3}(?:,\d{3})+(?:[.,]\d{1,2})?
      | \d{1,3}(?:\.\d{3})+(?:[.,]\d{1,2})?
      | \d+(?:[.,]\d{1,2})?
    )
"""

# Suffixes k / M (k = milliers, M = millions). La lettre qui suit ne doit
# pas être une lettre, sinon « 45 km » n'est pas un montant en milliers.
_UNIT_SUFFIX = r"(?P<unit>[kKmM])(?![^\W\d_])"

# Un montant : chiffres, suffixe k/M éventuel, devise éventuellement
# accolée. La devise *avant* le montant (« €45 000 ») est recherchée à
# part, juste après le match (voir _lead_currency).
_AMOUNT_RE = re.compile(
    rf"""
    (?P<num>{_NUMBER_PATTERN})
    (?:\s*{_UNIT_SUFFIX})?
    (?:\s*(?P<trail>{_CURRENCY_TOKEN}))?
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Balayage des positions candidates : un simple chiffre. Le motif complet
# n'est essayé qu'à ces positions, ce qui garde le coût linéaire et bas.
_DIGIT_RE = re.compile(r"\d")

# Frontières de phrase (fin de contexte regardé autour d'un montant).
# « + » sépare deux composantes de rémunération : « base 50k€ + bonus 10k€ ».
_BREAK_RE = re.compile(r"[\n;.!?,•|+]")

# Devise accolée avant le montant (« €45 000 », « EUR 45 000 »).
_LEAD_CURRENCY_RE = re.compile(rf"(?P<cur>{_CURRENCY_TOKEN})\s*$", re.IGNORECASE)

# Séparateur de fourchette : « 45-55k€ », « 50k to 60k », « 40k à 50k ».
_RANGE_SEPARATOR_RE = re.compile(r"\s*(?:[-\u2013\u2014]|\bto\b|\bà\b)\s*", re.IGNORECASE)
# Séparateur alphabétique : « entre 40k et 50k », « between 50k and 60k ».
_WORD_SEPARATOR_RE = re.compile(r"\s*(?:\bet\b|\band\b)\s*", re.IGNORECASE)
# Mot obligatoire devant un séparateur alphabétique.
_RANGE_PREFIX_RE = re.compile(r"(?:entre|between)\s*$", re.IGNORECASE)

_PERCENT_SUFFIX_RE = re.compile(r"\s*%")
_COUNT_SUFFIX_RE = re.compile(
    r"\s*(?:units?|shares?|actions?|titres?|stock\s+options?|options?)\b",
    re.IGNORECASE,
)

# Contexte autour d'un montant : nature de la rémunération, périodicité,
# qualificatif brut/net et mot-clé de rémunération.
#
# Le contexte est lu mot par mot (un seul balayage rapide) puis traduit
# par table : c'est bien plus rapide qu'une longue alternative de motifs,
# et cela garde un coût linéaire et stable sur les grands textes.
#
# L'ordre des tables est l'ordre de priorité (tie-break).
_SINGLE_WORDS: dict[str, str] = {
    # Nature de la rémunération
    "rsu": "rsu",
    "rsus": "rsu",
    "stock": "stock",
    "equity": "equity",
    "bonus": "bonus",
    "prime": "bonus",
    "primes": "bonus",
    "variable": "variable",
    "commission": "variable",
    "commissions": "variable",
    "package": "package",
    "packages": "package",
    "base": "base",
    "fixe": "base",
    "total": "total",
    "ctc": "total",
    # Qualificatif brut / net
    "brut": "gross",
    "bruto": "gross",
    "net": "gross",
    "gross": "gross",
    # Périodicité
    "mensuel": "monthly",
    "mensuelle": "monthly",
    "monthly": "monthly",
    "annuel": "annual",
    "annuelle": "annual",
    "annually": "annual",
    "yearly": "annual",
    "horaire": "hourly",
    "hourly": "hourly",
    # Mot-clé de rémunération
    "salaire": "keyword",
    "salaires": "keyword",
    "salary": "keyword",
    "salaries": "keyword",
    "rémunération": "keyword",
    "rémunérations": "keyword",
    "remuneration": "keyword",
    "remunerations": "keyword",
    "compensation": "keyword",
    "pay": "keyword",
    "paid": "keyword",
}

# Expressions de deux mots : (mot précédent, mot suivant) -> nature.
_PAIR_WORDS: dict[tuple[str, str], str] = {
    ("total", "compensation"): "total",
    ("total", "remuneration"): "total",
    ("total", "package"): "total",
    ("compensation", "package"): "package",
    ("remuneration", "package"): "package",
    ("rémunération", "package"): "package",
    ("rémunération", "totale"): "total",
    ("restricted", "stock"): "rsu",
    ("stock", "options"): "stock",
    ("stock", "equity"): "equity",
    ("part", "variable"): "variable",
    ("base", "salary"): "base",
    ("base", "pay"): "base",
    ("par", "an"): "annual",
    ("par", "année"): "annual",
    ("par", "annum"): "annual",
    ("par", "mois"): "monthly",
    ("par", "heure"): "hourly",
    ("per", "year"): "annual",
    ("per", "annum"): "annual",
    ("per", "month"): "monthly",
    ("per", "hour"): "hourly",
}

# Périodicités écrites après une barre oblique (« / an », « / mois »).
_SLASH_WORDS: dict[str, str] = {
    "an": "annual",
    "année": "annual",
    "yr": "annual",
    "mois": "monthly",
    "month": "monthly",
    "heure": "hourly",
    "hour": "hourly",
    "h": "hourly",
}

# Un mot : suite de lettres latines (avec accents).
_WORD_RE = re.compile(r"[A-Za-z\u00C0-\u024F]+")

_TYPE_GROUPS = ("rsu", "stock", "equity", "bonus", "variable", "total", "package", "base")
_PERIOD_GROUPS = ("monthly", "hourly", "annual")

_SENTENCE_BREAKS = "\n;.!?,•|"
_CONTEXT_WINDOW = 40
_PERIOD_MAX_GAP = 20
_TYPE_MAX_GAP = 2
_EXCERPT_SIZE = 50
_MAX_CONFIDENCE = 0.98
_MAX_COMPONENT_CONFIDENCE = 0.49


class _Amount(NamedTuple):
    """A monetary candidate located in the source text."""

    core_start: int
    core_end: int
    num: str
    unit: str | None
    lead: str | None
    lead_start: int
    trail: str | None
    trail_start: int
    trail_end: int

    @property
    def start(self) -> int:
        """First character of the amount expression (lead currency included)."""
        return self.lead_start if self.lead is not None else self.core_start

    @property
    def end(self) -> int:
        """Last character of the amount expression (trail currency included)."""
        return self.trail_end if self.trail is not None else self.core_end


def extract_salary(text: str) -> list[SalaryEvidence]:
    """Extract every remuneration figure written in a free-text offer.

    Pure and deterministic: no network, no LLM, no disk access. Only what
    the text actually states is returned — an offer that says nothing about
    pay yields an empty list (never a default value).

    Args:
        text: Free text (typically an offer ``description_original``).

    Returns:
        The evidences found, ordered by their position in the text.
    """
    if not text or not text.strip():
        return []

    amounts = _scan_amounts(text)
    if not amounts:
        return []

    evidences: list[SalaryEvidence] = []
    index = 0
    while index < len(amounts):
        current = amounts[index]
        following = amounts[index + 1] if index + 1 < len(amounts) else None
        if following is not None and _is_range(text, current, following):
            evidence = _build_range_evidence(text, current, following)
            index += 2
        else:
            evidence = _build_single_evidence(text, current)
            index += 1
        if evidence is not None:
            evidences.append(evidence)

    evidences.sort(key=lambda evidence: evidence.source_offset)
    return evidences


# ──────────────────────────────────────────────────────────────────────
# Internals
# ──────────────────────────────────────────────────────────────────────


def _scan_amounts(text: str) -> list[_Amount]:
    """Locate every monetary candidate of the text.

    The text is first swept for digits (a cheap, linear scan) and the full
    amount pattern is only tried at those positions: a long description is
    therefore scanned once, not pattern by pattern.
    """
    amounts: list[_Amount] = []
    consumed_until = 0
    for digit in _DIGIT_RE.finditer(text):
        position = digit.start()
        if position < consumed_until:
            continue
        match = _AMOUNT_RE.match(text, position)
        if match is None:
            continue
        consumed_until = match.end()
        num_start, num_end = match.span("num")
        unit = match.group("unit")
        core_end = match.end("unit") if unit else num_end
        trail = match.group("trail")
        trail_start, trail_end = match.span("trail") if trail else (num_end, num_end)
        lead, lead_start = _lead_currency(text, num_start)
        amounts.append(
            _Amount(
                core_start=num_start,
                core_end=core_end,
                num=match.group("num"),
                unit=unit,
                lead=lead,
                lead_start=lead_start,
                trail=trail,
                trail_start=trail_start,
                trail_end=trail_end,
            )
        )
    return amounts


def _lead_currency(text: str, num_start: int) -> tuple[str | None, int]:
    """Return the currency written just before an amount (« €45 000 »)."""
    low = max(0, num_start - 8)
    chunk = text[low:num_start]
    match = _LEAD_CURRENCY_RE.search(chunk)
    if match is None:
        return None, num_start
    start = low + match.start("cur")
    if start > 0 and text[start - 1].isdigit():
        # Une devise collée à un nombre précédent n'est pas la nôtre.
        return None, num_start
    return match.group("cur"), start


def _is_range(text: str, first: _Amount, second: _Amount) -> bool:
    """Tell whether two neighbouring amounts form a single range."""
    between = text[first.end:second.start]
    if _RANGE_SEPARATOR_RE.fullmatch(between):
        return True
    if _WORD_SEPARATOR_RE.fullmatch(between):
        before = text[max(0, first.core_start - 12):first.core_start]
        return bool(_RANGE_PREFIX_RE.search(before))
    return False


def _build_range_evidence(text: str, first: _Amount, second: _Amount) -> SalaryEvidence | None:
    """Build the evidence of a salary range (« 45-55k€ »)."""
    amount_start = first.start
    amount_end = second.end
    raw_amount = text[amount_start:amount_end]

    unit = first.unit or second.unit
    multiplier = _unit_multiplier(unit)
    value1 = _parse_number(first.num) * multiplier
    value2 = _parse_number(second.num) * multiplier
    low = min(value1, value2)
    high = max(value1, value2)

    currency = _resolve_currency(second.trail, first.trail, second.lead, first.lead)

    kind = "money"
    values: tuple[float, float] | None = (low, high)
    percent = _PERCENT_SUFFIX_RE.match(text, amount_end)
    if percent is not None and not currency and not unit:
        kind = "percent"
        values = None
        amount_end = percent.end()
        raw_amount = text[amount_start:amount_end]

    return _finalize_evidence(
        text,
        raw_amount_text=raw_amount,
        amount_start=amount_start,
        amount_end=amount_end,
        values=values,
        currency=currency,
        kind=kind,
        has_unit=unit is not None,
        is_range=True,
    )


def _build_single_evidence(text: str, amount: _Amount) -> SalaryEvidence | None:
    """Build the evidence of a single amount (« 45 000 € brut annuel »)."""
    amount_start = amount.start
    amount_end = amount.end
    raw_amount = text[amount_start:amount_end]

    values: tuple[float, float] | None = None
    kind = "money"

    percent = _PERCENT_SUFFIX_RE.match(text, amount.core_end)
    count = _COUNT_SUFFIX_RE.match(text, amount.core_end)
    if percent is not None and not amount.trail:
        # Composant en pourcentage (« variable 20 % ») : pas un montant EUR.
        kind = "percent"
        amount_end = percent.end()
        raw_amount = text[amount_start:amount_end]
    elif count is not None and not amount.trail:
        # Composant en nombre d'unités (« 1 000 stock options »).
        kind = "count"
        amount_end = count.end()
        raw_amount = text[amount_start:amount_end]
    elif amount.trail or amount.lead or amount.unit:
        value = _parse_number(amount.num) * _unit_multiplier(amount.unit)
        values = (value, value)
    else:
        # Aucun montant, aucune devise, aucun suffixe : rien à dire.
        return None

    return _finalize_evidence(
        text,
        raw_amount_text=raw_amount,
        amount_start=amount_start,
        amount_end=amount_end,
        values=values,
        currency=_resolve_currency(amount.trail, amount.lead),
        kind=kind,
        has_unit=amount.unit is not None,
        is_range=False,
    )


def _finalize_evidence(
    text: str,
    *,
    raw_amount_text: str,
    amount_start: int,
    amount_end: int,
    values: tuple[float, float] | None,
    currency: Currency,
    kind: str,
    has_unit: bool,
    is_range: bool,
) -> SalaryEvidence | None:
    """Complete a candidate with its provenance, its type and its confidence."""
    context = _scan_context(text, amount_start, amount_end)

    type_name, type_span = _closest(context, _TYPE_GROUPS)
    period_name, period_span = _closest(context, _PERIOD_GROUPS)
    qualifier_entry = context.get("gross")
    qualifier_span = (qualifier_entry[1], qualifier_entry[2]) if qualifier_entry else None
    has_salary_keyword = "keyword" in context

    if kind == "money":
        if not currency and not has_unit:
            # Un nombre sans devise ni suffixe k/M n'est pas un salaire.
            return None
    elif type_name is None:
        # Un pourcentage ou un nombre d'unités n'a de sens que rattaché à
        # une composante nommée (variable, bonus, stock, equity, rsu).
        return None

    # --- Périodicité et texte exact de la périodicité ---------------------
    periodicity: Periodicity = period_name if period_name else "unknown"
    spans: list[tuple[int, int]] = []
    if period_span is not None and _gap(period_span, amount_start, amount_end) <= _PERIOD_MAX_GAP:
        spans.append(period_span)
    if qualifier_span is not None and _gap(qualifier_span, amount_start, amount_end) <= _PERIOD_MAX_GAP:
        spans.append(qualifier_span)

    raw_period_text = ""
    if len(spans) == 2 and _gap(spans[0], spans[1][0], spans[1][1]) <= 3:
        low = min(spans[0][0], spans[1][0])
        high = max(spans[0][1], spans[1][1])
        raw_period_text = text[low:high]
    elif spans:
        raw_period_text = text[spans[0][0]:spans[0][1]]

    # --- Texte brut de l'expression ---------------------------------------
    raw_start = amount_start
    raw_end = amount_end
    if type_span is not None and _gap(type_span, amount_start, amount_end) <= _TYPE_MAX_GAP:
        if type_span[1] <= amount_start:
            raw_start = min(raw_start, type_span[0])
        else:
            raw_end = max(raw_end, type_span[1])
    for span in spans:
        if span[1] <= amount_start:
            raw_start = min(raw_start, span[0])
        else:
            raw_end = max(raw_end, span[1])

    raw_text = text[raw_start:raw_end]

    # --- Montants normalisés ---------------------------------------------
    min_annual: float | None = None
    max_annual: float | None = None
    if values is not None:
        if periodicity == "monthly":
            factor = 12.0
        elif periodicity == "hourly":
            factor = float(HOURS_PER_YEAR)
        else:
            factor = 1.0
        min_annual = round(values[0] * factor, 2)
        max_annual = round(values[1] * factor, 2)

    # --- Nature de la rémunération ----------------------------------------
    salary_type: SalaryType = type_name if type_name else "unknown"
    if salary_type == "unknown" and qualifier_span is not None:
        # « brut annuel » / « net mensuel » sans autre qualificatif décrit la
        # rémunération de base ; le littéral "base" est le seul qui convienne.
        salary_type = "base"

    # --- Confiance ---------------------------------------------------------
    confidence = 0.15
    if currency:
        confidence += 0.45
    if has_salary_keyword or type_name or qualifier_span is not None:
        confidence += 0.20
    if period_name:
        confidence += 0.25
    if type_name or qualifier_span is not None:
        confidence += 0.15
    if has_unit:
        confidence += 0.05
    if is_range:
        confidence += 0.05
    confidence = min(confidence, _MAX_CONFIDENCE)
    if kind != "money":
        # Un pourcentage ou un nombre d'unités n'est pas convertible en EUR.
        confidence = min(confidence, _MAX_COMPONENT_CONFIDENCE)

    return SalaryEvidence(
        raw_text=raw_text,
        source_offset=amount_start,
        source_excerpt=_excerpt(text, raw_start, raw_end),
        min_annual_eur=min_annual,
        max_annual_eur=max_annual,
        currency=currency,
        salary_type=salary_type,
        periodicity=periodicity,
        raw_amount_text=raw_amount_text,
        raw_period_text=raw_period_text,
        confidence=round(confidence, 2),
    )


def _parse_number(raw: str) -> float:
    """Parse a written amount into a float.

    Thousands separators (space, comma, dot) are told apart from decimal
    marks by the number of digits that follow: "45 000" and "45,000" are
    forty-five thousand, "1.5" is one point five, "45,50" is forty-five
    point five.
    """
    cleaned = raw.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned or "." in cleaned:
        separator = "," if "," in cleaned else "."
        parts = cleaned.split(separator)
        if len(parts) == 2 and len(parts[1]) == 3:
            cleaned = parts[0] + parts[1]
        elif len(parts) == 2:
            cleaned = parts[0] + "." + parts[1]
        else:
            cleaned = "".join(parts)
    return float(cleaned)


def _unit_multiplier(unit: str | None) -> float:
    """Return the multiplier of a k / M suffix."""
    if not unit:
        return 1.0
    if unit.lower() == "k":
        return 1_000.0
    if unit.lower() == "m":
        return 1_000_000.0
    return 1.0


def _resolve_currency(*tokens: str | None) -> Currency:
    """Return the ISO code of the first currency actually written."""
    for token in tokens:
        if not token:
            continue
        cleaned = token.strip()
        if cleaned in _CURRENCY_SYMBOLS:
            return cast(Currency, _CURRENCY_SYMBOLS[cleaned])
        key = cleaned.upper().rstrip(".")
        if key in _CURRENCY_CODES:
            return cast(Currency, _CURRENCY_CODES[key])
        if key.startswith("EURO"):
            return "EUR"
        if key.startswith("DOLLAR"):
            return "USD"
        if key.startswith("POUND"):
            return "GBP"
        if key.startswith("YEN"):
            return "JPY"
    return ""


def _window_before(text: str, start: int) -> tuple[int, str]:
    """Return the sentence fragment that precedes ``start`` (offsets + text)."""
    low = max(0, start - _CONTEXT_WINDOW)
    chunk = text[low:start]
    cut = -1
    for match in _BREAK_RE.finditer(chunk):
        cut = match.start()
    if cut >= 0:
        low += cut + 1
        chunk = chunk[cut + 1:]
    return low, chunk


def _window_after(text: str, end: int) -> tuple[int, str]:
    """Return the sentence fragment that follows ``end`` (offsets + text)."""
    chunk = text[end:end + _CONTEXT_WINDOW]
    match = _BREAK_RE.search(chunk)
    if match is not None:
        chunk = chunk[:match.start()]
    return end, chunk


def _scan_context(text: str, amount_start: int, amount_end: int) -> dict[str, tuple[tuple[int, int], int, int]]:
    """Return, for each kind of context word, the closest one around an amount.

    "Closest" wins; on a tie the word written before the amount wins.
    Only the sentence fragments around the amount are read.
    """
    found: dict[str, tuple[tuple[int, int], int, int]] = {}
    low, before = _window_before(text, amount_start)
    after_start, after = _window_after(text, amount_end)
    _scan_fragment(text, low, amount_start, amount_start, amount_end, found)
    _scan_fragment(text, after_start, after_start + len(after), amount_start, amount_end, found)
    return found


def _scan_fragment(
    text: str,
    low: int,
    high: int,
    amount_start: int,
    amount_end: int,
    found: dict[str, tuple[tuple[int, int], int, int]],
) -> None:
    """Read the context words of a fragment and keep the closest of each kind."""
    words = [
        (match.start(), match.end(), match.group(0).lower())
        for match in _WORD_RE.finditer(text, low, high)
    ]
    tokens: list[tuple[str, int, int]] = []
    index = 0
    while index < len(words):
        start, end, word = words[index]
        kind: str | None = None
        if index + 1 < len(words):
            kind = _PAIR_WORDS.get((word, words[index + 1][2]))
            if kind is not None:
                tokens.append((kind, start, words[index + 1][1]))
                index += 2
                continue
        if start > 0 and text[max(0, start - 2):start].rstrip().endswith("/"):
            # Périodicité écrite après une barre oblique : « / an », « / mois ».
            kind = _SLASH_WORDS.get(word)
        if kind is None:
            kind = _SINGLE_WORDS.get(word)
        if kind is not None:
            tokens.append((kind, start, end))
        index += 1

    for kind, start, end in tokens:
        if end <= amount_start:
            distance = (amount_start - end, 0)
        elif start >= amount_end:
            distance = (start - amount_end, 1)
        else:
            continue
        current = found.get(kind)
        if current is None or distance < current[0]:
            found[kind] = (distance, start, end)


def _closest(context: dict[str, tuple[tuple[int, int], int, int]], groups: tuple[str, ...]) -> tuple[str | None, tuple[int, int] | None]:
    """Return the closest context word among ``groups``.

    The distance decides; the order of ``groups`` breaks the ties.
    """
    best: tuple[tuple[int, int], int, str] | None = None
    for index, group in enumerate(groups):
        if group not in context:
            continue
        distance = context[group][0]
        if best is None or (distance, index) < (best[0], best[1]):
            best = (distance, index, group)
    if best is None:
        return None, None
    group = best[2]
    return group, (context[group][1], context[group][2])


def _gap(span: tuple[int, int], amount_start: int, amount_end: int) -> int:
    """Return the number of characters between a span and the amount."""
    start, end = span
    if end <= amount_start:
        return amount_start - end
    if start >= amount_end:
        return start - amount_end
    return 0


def _excerpt(text: str, start: int, end: int) -> str:
    """Return at most 50 characters of context containing the expression."""
    low = max(0, start - _EXCERPT_SIZE // 2)
    high = min(len(text), low + _EXCERPT_SIZE)
    if high < end:
        high = min(len(text), end)
        low = max(0, high - _EXCERPT_SIZE)
    return text[low:high]
