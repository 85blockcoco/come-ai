"""Text extraction from PDF, DOCX, and TXT files + salary extraction.

Pure local extraction — no network, no LLM, no external APIs.
Reuses pypdf (PDF) and python-docx (DOCX) if available.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

from .models import DocumentInput, Finding, SalaryEvidence, STATUS_RISK


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

# ══════════════════════════════════════════════════════════════════════
# Salary extraction (Mission CVBOOST-16)
#
# Pure, deterministic, offline: no network, no LLM, no side effect.
# Every mention carries an exact provenance (source_offset + source_excerpt)
# and is never completed by a default value: what is not written in the
# text stays missing (None / "" / "unknown").
#
# Performance: the text is swept once for its digits, the amount pattern is
# only tried at those positions, and the context of an amount is read word
# by word inside the sentence fragment that surrounds it. A 50 000
# character offer is extracted in well under 5 ms.
# ══════════════════════════════════════════════════════════════════════

# ── Currencies ─────────────────────────────────────────────────────────
# Symbols are unambiguous; the alpha codes are matched on word boundaries.
_CURRENCY_SYMBOLS: dict[str, str] = {
    "€": "EUR",
    "$": "USD",
    "£": "GBP",
    "¥": "JPY",
}
_CURRENCY_CODES: dict[str, str] = {
    "EUR": "EUR", "USD": "USD", "GBP": "GBP", "JPY": "JPY", "CHF": "CHF",
    "CAD": "CAD", "AUD": "AUD", "NOK": "NOK", "SEK": "SEK", "DKK": "DKK",
    "PLN": "PLN", "INR": "INR", "BRL": "BRL", "ZAR": "ZAR", "SGD": "SGD",
    "CNY": "CNY", "RMB": "CNY",
}
# A currency token: a symbol, or a code / a written word.
_CURRENCY_TOKEN = (
    r"(?:[€$£¥]"
    r"|\b(?:EUR|euros?|USD|dollars?|GBP|pounds?|JPY|yens?|CHF|CAD|AUD|NOK|SEK|DKK"
    r"|PLN|INR|BRL|ZAR|SGD|CNY|RMB)\b)"
)

# ── Amounts ───────────────────────────────────────────────────────────
# A number with its thousands separators, its k/M scale suffix and the
# currency written after it. The currency written *before* the amount
# ("€45 000") is read separately, just before the match.
_NUMBER_PATTERN = r"""
    (?:
        \d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d{1,2})?
      | \d{1,3}(?:,\d{3})+(?:[.,]\d{1,2})?
      | \d{1,3}(?:\.\d{3})+(?:[.,]\d{1,2})?
      | \d+(?:[.,]\d{1,2})?
    )
"""
# The k/M suffix: the character that follows must not be a letter, so that
# "45 km" is not read as forty-five thousand.
_UNIT_SUFFIX = r"(?P<unit>[kKmM])(?![^\W\d_])"
_AMOUNT_RE = re.compile(
    rf"(?P<num>{_NUMBER_PATTERN})(?:\s*{_UNIT_SUFFIX})?(?:\s*(?P<trail>{_CURRENCY_TOKEN}))?",
    re.VERBOSE | re.IGNORECASE,
)
# The text is swept once for its digits; the amount pattern is only tried
# at those positions, which keeps the cost linear and low.
_DIGIT_RE = re.compile(r"\d")
# A currency written just before an amount ("€45 000", "EUR 45 000").
_LEAD_CURRENCY_RE = re.compile(rf"(?P<cur>{_CURRENCY_TOKEN})\s*$", re.IGNORECASE)

# ── Context ───────────────────────────────────────────────────────────
# The context of an amount is read word by word inside the sentence
# fragment that surrounds it, then translated through these tables: far
# faster than a long alternation of patterns, and the cost stays linear
# whatever the length of the offer.
#
# The kinds are the priority order of the context words: the closest word
# wins and, on a tie, the word written before the amount wins.
_CONTEXT_WORDS: dict[str, str] = {
    # nature of the remuneration
    "rsu": "rsu",
    "stock": "stock",
    "equity": "equity",
    "bonus": "bonus",
    "prime": "bonus",
    "variable": "variable",
    "commission": "variable",
    "package": "package",
    "base": "base",
    "fixe": "base",
    "total": "total",
    "ctc": "total",
    "salaire": "base",
    "salary": "base",
    "rémunération": "base",
    "remuneration": "base",
    "compensation": "base",
    # gross / net qualifier
    "brut": "gross",
    "net": "gross",
    "gross": "gross",
    # periodicity
    "annuel": "annual",
    "annuelle": "annual",
    "annuellement": "annual",
    "annually": "annual",
    "yearly": "annual",
    "mensuel": "monthly",
    "mensuelle": "monthly",
    "monthly": "monthly",
    "horaire": "hourly",
    "hourly": "hourly",
}
# Two-word expressions: (previous word, next word) -> kind.
_CONTEXT_PAIRS: dict[tuple[str, str], str] = {
    ("total", "compensation"): "total",
    ("total", "remuneration"): "total",
    ("total", "package"): "total",
    ("compensation", "totale"): "total",
    ("rémunération", "totale"): "total",
    ("remuneration", "totale"): "total",
    ("compensation", "package"): "package",
    ("remuneration", "package"): "package",
    ("rémunération", "package"): "package",
    ("restricted", "stock"): "rsu",
    ("stock", "options"): "stock",
    ("part", "variable"): "variable",
    ("base", "salary"): "base",
    ("par", "an"): "annual",
    ("par", "année"): "annual",
    ("par", "mois"): "monthly",
    ("par", "heure"): "hourly",
    ("per", "year"): "annual",
    ("per", "annum"): "annual",
    ("per", "month"): "monthly",
    ("per", "hour"): "hourly",
}
# Periodicity written after a slash ("/ an", "/ mois", "/ year").
_SLASH_WORDS: dict[str, str] = {
    "an": "annual", "année": "annual", "yr": "annual",
    "mois": "monthly", "month": "monthly", "heure": "hourly", "hour": "hourly",
}
# A word: a run of latin letters (accents included).
_WORD_RE = re.compile(r"[A-Za-z\u00C0-\u024F]+")

# ── Boundaries ────────────────────────────────────────────────────────
# Sentence breaks: the context of an amount never crosses one.
_BREAK_RE = re.compile(r"[\n;.!?,•|+]")
# Range separators: "45-55k€", "50k to 60k", "40k à 50k".
_RANGE_SEPARATOR_RE = re.compile(r"\s*(?:[-\u2013\u2014]|\bto\b|\bà\b)\s*", re.IGNORECASE)
# Alphabetic range separator: "entre 40k et 50k", "between 50k and 60k".
_WORD_SEPARATOR_RE = re.compile(r"\s*(?:\bet\b|\band\b)\s*", re.IGNORECASE)
# A word mandatory before an alphabetic separator.
_RANGE_PREFIX_RE = re.compile(r"(?:entre|between)\s*$", re.IGNORECASE)

# ── Filters ───────────────────────────────────────────────────────────
# A percentage sign right after the amount: a rate, not a money amount.
_PERCENT_SUFFIX_RE = re.compile(r"\s*%")
# A counter of shares/units right after the amount: a quantity, not money.
_COUNT_SUFFIX_RE = re.compile(
    r"\s*(?:units?|shares?|actions?|titres?|stock\s+options?|options?)\b",
    re.IGNORECASE,
)
# Counters that disqualify a currency-less "50k": "50k downloads" is a
# traffic figure, not a salary.
_NON_SALARY_COUNTERS: frozenset[str] = frozenset({
    "utilisateurs", "utilisateur", "user", "users",
    "visiteurs", "visiteur", "visitor", "visitors",
    "downloads", "download", "téléchargements", "telechargements",
    "abonnés", "abonnes", "subscribers", "clients", "client",
    "vues", "views", "articles", "personnes", "employés", "employes", "employees",
    "requêtes", "requetes", "requests", "lectures", "visites", "hits", "collaborateurs",
})

# ── Tuning ────────────────────────────────────────────────────────────
# Characters read around an amount to find its context.
_CONTEXT_WINDOW = 40
# Maximum gap between a context word and the amount for the word to apply.
_PERIOD_MAX_GAP = 20
_TYPE_MAX_GAP = 2
# Confidence scale.
_MAX_CONFIDENCE = 0.98
# Annualisation factors.
_ANNUAL_MULTIPLIER: dict[str, float] = {"annual": 1.0, "monthly": 12.0}
# Hours worked per year, used to annualise an hourly rate (35 h x 52 weeks).
_HOURS_PER_YEAR = 1820


@dataclass(slots=True)
class _Amount:
    """One monetary candidate located in the source text."""

    start: int
    end: int
    num_start: int
    num_end: int
    num: str
    unit: str | None
    currency: str
    value: float


def extract_salary(text: str) -> list[SalaryEvidence]:
    """Extract salary / compensation mentions from a job offer text.

    Deterministic and fully offline: no network call, no LLM, no default
    value. Every returned evidence carries the exact provenance of the
    mention (`source_offset` + `source_excerpt`) and the normalized amounts
    (annualised, k/M expanded) expressed in the currency found in the text —
    no exchange rate is ever applied, so nothing is ever invented.

    Args:
        text: Raw text, typically an offer description.

    Returns:
        The mentions found, ordered by position in the text. Empty when the
        text carries no salary information (never a default amount).
    """
    if not text or not text.strip():
        return []

    amounts = _scan_amounts(text)
    if not amounts:
        return []

    evidences: list[SalaryEvidence] = []
    index = 0
    limit = 0
    while index < len(amounts):
        current = amounts[index]
        following = amounts[index + 1] if index + 1 < len(amounts) else None
        if following is not None and _is_range(text, current, following):
            after_index = index + 2
            after = amounts[after_index].start if after_index < len(amounts) else None
            evidence = _build_range_evidence(text, current, following, (limit, after))
            index += 2
        else:
            after = following.start if following is not None else None
            evidence = _build_single_evidence(text, current, (limit, after))
            index += 1
        if evidence is not None:
            evidences.append(evidence)
            # The qualifiers of a mention belong to it: the next mention
            # never reads them again.
            limit = max(limit, evidence.source_offset + len(evidence.raw_text))
        else:
            limit = max(limit, current.end)

    evidences.sort(key=lambda evidence: evidence.source_offset)
    return evidences


# ──────────────────────────────────────────────────────────────────────
# Internals — amounts
# ──────────────────────────────────────────────────────────────────────

def _scan_amounts(text: str) -> list[_Amount]:
    """Locate every monetary candidate of the text.

    The text is swept once for its digits (a cheap linear scan) and the
    amount pattern is only tried at those positions.
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
        trail = match.group("trail")
        lead, lead_start = _lead_currency(text, num_start)
        currency = _resolve_currency(trail, lead)
        amounts.append(
            _Amount(
                start=lead_start if lead is not None else num_start,
                end=match.end("trail") if trail else (match.end("unit") if unit else num_end),
                num_start=num_start,
                num_end=num_end,
                num=match.group("num"),
                unit=unit,
                currency=currency,
                value=_parse_number(match.group("num")),
            )
        )
    return amounts


def _lead_currency(text: str, num_start: int) -> tuple[str | None, int]:
    """Return the currency written just before an amount ("€45 000")."""
    low = max(0, num_start - 8)
    chunk = text[low:num_start]
    match = _LEAD_CURRENCY_RE.search(chunk)
    if match is None:
        return None, num_start
    start = low + match.start("cur")
    if start > 0 and text[start - 1].isdigit():
        # A currency glued to a previous number is not ours.
        return None, num_start
    return match.group("cur"), start


def _resolve_currency(*tokens: str | None) -> str:
    """Return the ISO code of the first currency actually written."""
    for token in tokens:
        if not token:
            continue
        cleaned = token.strip()
        if cleaned in _CURRENCY_SYMBOLS:
            return _CURRENCY_SYMBOLS[cleaned]
        key = cleaned.upper().rstrip(".")
        if key in _CURRENCY_CODES:
            return _CURRENCY_CODES[key]
        if key.startswith("EURO"):
            return "EUR"
        if key.startswith("DOLLAR"):
            return "USD"
        if key.startswith("POUND"):
            return "GBP"
        if key.startswith("YEN"):
            return "JPY"
    return ""


def _parse_number(raw: str) -> float:
    """Parse a written amount into a float.

    The number of digits that follows the separator tells a thousands
    separator from a decimal mark: "45 000" and "45,000" are forty-five
    thousand, "1.5" is one point five, "45,50" is forty-five point five.
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


def _unit_multiplier(unit: str | None, currency: str) -> float:
    """Return the multiplier of a k / M suffix.

    A lowercase "m" only means "million" when a currency is written next
    to it, otherwise it is a unit of measure ("10 m").
    """
    if not unit:
        return 1.0
    if unit.lower() == "k":
        return 1_000.0
    if unit == "M" or currency:
        return 1_000_000.0
    return 1.0


def _is_range(text: str, first: _Amount, second: _Amount) -> bool:
    """Tell whether two neighbouring amounts form a single range."""
    between = text[first.end:second.start]
    if _RANGE_SEPARATOR_RE.fullmatch(between):
        return True
    if _WORD_SEPARATOR_RE.fullmatch(between):
        before = text[max(0, first.num_start - 12):first.num_start]
        return bool(_RANGE_PREFIX_RE.search(before))
    return False


# ──────────────────────────────────────────────────────────────────────
# Internals — context
# ──────────────────────────────────────────────────────────────────────

def _window_before(text: str, start: int, limit: int = 0) -> tuple[int, str]:
    """Return the sentence fragment that precedes ``start`` (offsets + text)."""
    low = max(0, max(start - _CONTEXT_WINDOW, limit))
    chunk = text[low:start]
    cut = -1
    for match in _BREAK_RE.finditer(chunk):
        cut = match.start()
    if cut >= 0:
        low += cut + 1
        chunk = chunk[cut + 1:]
    return low, chunk


def _window_after(text: str, end: int, limit: int | None = None) -> tuple[int, str]:
    """Return the sentence fragment that follows ``end`` (offsets + text)."""
    high = end + _CONTEXT_WINDOW
    if limit is not None:
        high = min(high, limit)
    high = min(high, len(text))
    chunk = text[end:high]
    match = _BREAK_RE.search(chunk)
    if match is not None:
        chunk = chunk[:match.start()]
    return end, chunk


def _word_kind(word: str) -> str | None:
    """Return the kind of a context word ("salaires" is a "salaire")."""
    kind = _CONTEXT_WORDS.get(word)
    if kind is not None:
        return kind
    if len(word) > 3 and word.endswith("s"):
        return _CONTEXT_WORDS.get(word[:-1])
    return None


def _scan_fragment(
    text: str,
    low: int,
    high: int,
    amount_start: int,
    amount_end: int,
    found: dict[str, tuple[int, int, int]],
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
            kind = _CONTEXT_PAIRS.get((word, words[index + 1][2]))
            if kind is not None:
                tokens.append((kind, start, words[index + 1][1]))
                index += 2
                continue
        if start > 0 and text[max(0, start - 2):start].rstrip().endswith("/"):
            # Periodicity written after a slash: "/ an", "/ mois".
            kind = _SLASH_WORDS.get(word)
        if kind is None:
            kind = _word_kind(word)
        if kind is not None:
            tokens.append((kind, start, end))
        index += 1

    for kind, start, end in tokens:
        if end <= amount_start:
            distance = (amount_start - end, 0)
        elif start >= amount_end:
            distance = (start - amount_end, 1)
        else:
            distance = (0, 0)
        previous = found.get(kind)
        if previous is None or distance < previous[2:]:
            found[kind] = (start, end, distance[0], distance[1])


def _scan_context(
    text: str,
    amount_start: int,
    amount_end: int,
    before_limit: int = 0,
    after_limit: int | None = None,
) -> dict[str, tuple[int, int, int, int]]:
    """Return, for each kind of context word, the closest one around an amount.

    Only the sentence fragments around the amount are read, and never beyond
    the neighbouring amounts.
    """
    found: dict[str, tuple[int, int, int, int]] = {}
    low, _before = _window_before(text, amount_start, before_limit)
    after_start, after = _window_after(text, amount_end, after_limit)
    _scan_fragment(text, low, amount_start, amount_start, amount_end, found)
    _scan_fragment(text, after_start, after_start + len(after), amount_start, amount_end, found)
    return found


def _gap(span: tuple[int, int, int, int], amount_start: int, amount_end: int) -> int:
    """Distance between a context word and an amount (0 when they touch)."""
    start, end = span[0], span[1]
    if end <= amount_start:
        return amount_start - end
    if start >= amount_end:
        return start - amount_end
    return 0


# ──────────────────────────────────────────────────────────────────────
# Internals — evidence
# ──────────────────────────────────────────────────────────────────────

def _build_range_evidence(
    text: str,
    first: _Amount,
    second: _Amount,
    limits: tuple[int, int | None] = (0, None),
) -> SalaryEvidence | None:
    """Build the evidence of a salary range ("45-55k€")."""
    amount_start = first.start
    amount_end = second.end
    raw_amount = text[amount_start:amount_end]

    currency = first.currency or second.currency
    # The k/M suffix of one bound covers the whole range ("45-55k€").
    unit = first.unit or second.unit
    multiplier = _unit_multiplier(unit, currency)
    low = min(first.value, second.value) * multiplier
    high = max(first.value, second.value) * multiplier

    return _finalize_evidence(
        text,
        raw_amount_text=raw_amount,
        amount_start=amount_start,
        amount_end=amount_end,
        values=(low, high),
        currency=currency,
        is_money=True,
        has_unit=unit is not None,
        is_range=True,
        limits=limits,
    )


def _build_single_evidence(
    text: str,
    amount: _Amount,
    limits: tuple[int, int | None] = (0, None),
) -> SalaryEvidence | None:
    """Build the evidence of a single amount ("45 000 € brut annuel")."""
    amount_start = amount.start
    amount_end = amount.end
    raw_amount = text[amount_start:amount_end]
    is_money = True

    percent = _PERCENT_SUFFIX_RE.match(text, amount.end)
    count = _COUNT_SUFFIX_RE.match(text, amount.end)
    if percent is not None and not amount.currency and not amount.unit:
        # A percentage is not a money amount ("variable 20 %").
        is_money = False
        amount_end = percent.end()
        raw_amount = text[amount_start:amount_end]
    elif count is not None and not amount.currency and not amount.unit:
        # A number of units is not a money amount ("1 000 stock options").
        is_money = False
        amount_end = count.end()
        raw_amount = text[amount_start:amount_end]
    elif not amount.currency and not amount.unit:
        # No currency, no scale suffix: the number says nothing about money.
        return None
    elif _followed_by_non_salary_counter(text, amount.end):
        # "50k downloads" is a traffic figure, not a salary.
        return None

    multiplier = _unit_multiplier(amount.unit, amount.currency)
    values = (amount.value * multiplier, amount.value * multiplier) if is_money else None
    return _finalize_evidence(
        text,
        raw_amount_text=raw_amount,
        amount_start=amount_start,
        amount_end=amount_end,
        values=values,
        currency=amount.currency,
        is_money=is_money,
        has_unit=amount.unit is not None,
        is_range=False,
        limits=limits,
    )


def _followed_by_non_salary_counter(text: str, offset: int) -> bool:
    """True when the amount is followed by a non-salary counter ("50k downloads")."""
    tail = text[offset:offset + 30]
    match = re.match(r"\s*([A-Za-zÀ-ÿ'’-]+)", tail)
    if not match:
        return False
    return match.group(1).lower() in _NON_SALARY_COUNTERS


def _finalize_evidence(
    text: str,
    *,
    raw_amount_text: str,
    amount_start: int,
    amount_end: int,
    values: tuple[float, float] | None,
    currency: str,
    is_money: bool,
    has_unit: bool,
    is_range: bool,
    limits: tuple[int, int | None] = (0, None),
) -> SalaryEvidence | None:
    """Complete a candidate with its provenance, its type and its confidence."""
    context = _scan_context(text, amount_start, amount_end, limits[0], limits[1])

    type_kind, type_span = _closest(context, _TYPE_GROUPS, before_only=True)
    qualifier = context.get("gross")
    period_kind, period_span = _closest(context, _PERIOD_GROUPS)

    if not is_money and type_span is None:
        # A percentage or a number of units only makes sense attached to a
        # named component ("variable 20 %", "RSU 5000 units").
        return None

    # --- Periodicity and the exact periodicity text -------------------------
    periodicity = "unknown"
    if period_span is not None and _gap(period_span, amount_start, amount_end) <= _PERIOD_MAX_GAP:
        periodicity = period_kind or "unknown"
    spans: list[tuple[int, int]] = []
    if periodicity != "unknown" and period_span is not None:
        spans.append((period_span[0], period_span[1]))
    if qualifier is not None and _gap(qualifier, amount_start, amount_end) <= _PERIOD_MAX_GAP:
        spans.append((qualifier[0], qualifier[1]))
    spans.sort()

    raw_period_text = ""
    if len(spans) == 2 and spans[1][0] - spans[0][1] <= 3:
        raw_period_text = text[spans[0][0]:spans[1][1]]
    elif spans:
        raw_period_text = text[spans[0][0]:spans[0][1]]

    # --- The exact text of the expression -----------------------------------
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

    # --- Normalized amounts --------------------------------------------------
    min_annual: float | None = None
    max_annual: float | None = None
    if values is not None:
        multiplier = float(_HOURS_PER_YEAR) if periodicity == "hourly" else _ANNUAL_MULTIPLIER.get(periodicity, 1.0)
        min_annual = round(values[0] * multiplier, 2)
        max_annual = round(values[1] * multiplier, 2)

    # --- Nature of the remuneration -------------------------------------------
    salary_type = "unknown"
    if type_kind is not None:
        salary_type = _KIND_TO_SALARY_TYPE[type_kind]
    elif qualifier is not None:
        # "brut annuel" / "net mensuel" without another qualifier describes the
        # base remuneration: "base" is the only literal that fits.
        salary_type = "base"

    # --- Confidence ------------------------------------------------------------
    confidence = 0.15
    if currency:
        confidence += 0.35
    if salary_type != "unknown":
        confidence += 0.25
    if periodicity != "unknown":
        confidence += 0.15
    if type_span is not None and _gap(type_span, amount_start, amount_end) <= _TYPE_MAX_GAP:
        confidence += 0.10
    if is_range:
        confidence += 0.10
    if has_unit:
        confidence += 0.05
    if not is_money:
        confidence -= 0.15
    confidence = min(confidence, _MAX_CONFIDENCE)

    return SalaryEvidence(
        raw_text=raw_text,
        source_offset=raw_start,
        source_excerpt=_excerpt(text, raw_start),
        min_annual_eur=min_annual,
        max_annual_eur=max_annual,
        currency=currency,
        salary_type=salary_type,  # type: ignore[arg-type]
        periodicity=periodicity,  # type: ignore[arg-type]
        raw_amount_text=raw_amount_text,
        raw_period_text=raw_period_text,
        confidence=round(confidence, 2),
    )


_KIND_TO_SALARY_TYPE: dict[str, str] = {
    "base": "base",
    "total": "total",
    "package": "package",
    "variable": "variable",
    "bonus": "bonus",
    "stock": "stock",
    "equity": "equity",
    "rsu": "rsu",
}
# The context kinds, from the most specific to the most generic.
_TYPE_GROUPS = ("total", "rsu", "equity", "stock", "package", "variable", "bonus", "base")
_PERIOD_GROUPS = ("annual", "monthly", "hourly")


def _closest(
    context: dict[str, tuple[int, int, int, int]],
    kinds: tuple[str, ...],
    before_only: bool = False,
) -> tuple[str | None, tuple[int, int, int, int] | None]:
    """Return the closest context word among the given kinds.

    The closest wins; on a tie the order of the kinds breaks it.
    """
    best_distance: tuple[int, int] | None = None
    best_kind: str | None = None
    best_span: tuple[int, int, int, int] | None = None
    for kind in kinds:
        entry = context.get(kind)
        if entry is None:
            continue
        if before_only and entry[3] != 0:
            # The nature of a remuneration is written *before* the amount
            # ("Package 70k€", "variable 20 %").
            continue
        distance = (entry[2], entry[3])
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_kind = kind
            best_span = entry
    return best_kind, best_span


def _excerpt(text: str, offset: int) -> str:
    """~50 characters of context around an offset (same convention as structure.py)."""
    excerpt_start = max(0, offset - 25)
    excerpt_end = min(len(text), offset + 25)
    return text[excerpt_start:excerpt_end].replace("\n", "⏎")
