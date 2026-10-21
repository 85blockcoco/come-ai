"""Text extraction from PDF, DOCX, and TXT files + salary extraction.

Pure local extraction — no network, no LLM, no external APIs.
Reuses pypdf (PDF) and python-docx (DOCX) if available.
"""

from __future__ import annotations

import io
import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path

from .models import DocumentInput, Finding, SalaryEvidence, SalaryPeriodicity, SalaryType, STATUS_RISK


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
# The text is scanned with C-level substring searches (str.find) plus a
# single regular expression, so a 50 000 character offer stays in the low
# milliseconds (the mission requires ≤ 5 ms).
# ══════════════════════════════════════════════════════════════════════

# ── Currencies ─────────────────────────────────────────────────────────
# Symbols are unambiguous; alpha codes are matched on word boundaries only.
_CURRENCY_SYMBOLS: dict[str, str] = {
    "€": "EUR",
    "$": "USD",
    "£": "GBP",
    "¥": "JPY",
}
_CURRENCY_CODES: tuple[str, ...] = (
    "EUR", "USD", "GBP", "JPY", "CHF", "CAD", "AUD",
    "NOK", "SEK", "DKK", "PLN", "INR", "BRL", "ZAR", "SGD",
)
# Currency tokens searched in the text (lowercase needles → ISO code).
_CURRENCY_NEEDLES: tuple[tuple[str, str, int], ...] = (
    ("euros", "EUR", 0),
    ("euro", "EUR", 0),
) + tuple((code.lower(), code, 0) for code in _CURRENCY_CODES)

# ── Keyword needles ────────────────────────────────────────────────────
# (needle in lowercase, kind, priority). The kind is "t:<type>" for a salary
# nature, "p:<periodicity>" for a periodicity, "q" for a qualifier that is
# neither. The priority orders the needles from the most specific to the most
# generic: when two needles overlap, the most specific one wins.
# A trailing "s" is accepted on every needle, so the plural forms do not need
# their own entry.
_KEYWORD_NEEDLES: tuple[tuple[str, str, int], ...] = (
    # -- total compensation --------------------------------------------------
    ("total compensation", "t:total", 0),
    ("compensation totale", "t:total", 0),
    ("rémunération totale", "t:total", 0),
    ("remuneration totale", "t:total", 0),
    ("total comp", "t:total", 0),
    ("ctc", "t:total", 0),
    # -- equity instruments ---------------------------------------------------
    ("rsu", "t:rsu", 1),
    ("stock", "t:stock", 2),
    ("equity", "t:equity", 3),
    # -- package --------------------------------------------------------------
    ("package", "t:package", 5),
    # -- variable / bonus -----------------------------------------------------
    ("variable", "t:variable", 6),
    ("indexation", "t:variable", 6),
    ("bonus", "t:bonus", 7),
    ("prime", "t:bonus", 7),
    ("commission", "t:bonus", 7),
    # -- base -----------------------------------------------------------------
    ("base", "t:base", 9),
    ("fixe", "t:base", 9),
    # "brut" / "net" / "gross" qualify the amount (gross or net pay): they do
    # not tell the nature of the compensation on their own, so they are not
    # type keywords.
    ("brut", "g:gross", 9),
    ("net", "g:net", 9),
    ("gross", "g:gross", 9),
    # -- generic salary words -------------------------------------------------
    ("salaire", "t:base", 10),
    ("rémunération", "t:base", 10),
    ("remuneration", "t:base", 10),
    ("salary", "t:base", 10),
    ("compensation", "t:base", 10),
    # -- periodicity ----------------------------------------------------------
    ("annuellement", "p:annual", 11),
    ("annuelle", "p:annual", 11),
    ("annuel", "p:annual", 11),
    ("yearly", "p:annual", 11),
    ("annually", "p:annual", 11),
    ("mensuelle", "p:monthly", 11),
    ("mensuel", "p:monthly", 11),
    ("monthly", "p:monthly", 11),
    ("hourly", "p:hourly", 11),
    # -- qualifier only (neither a nature nor a supported periodicity) ---------
    ("before tax", "q", 12),
    ("after tax", "q", 12),
    ("hebdomadaire", "q", 12),
    ("weekly", "q", 12),
)

# Periodicity written with a prefix: "/ mois", "par an", "per annum".
_PREFIX_PERIODS: tuple[tuple[str, dict[str, str]], ...] = (
    (
        "/",
        {
            "an": "p:annual", "année": "p:annual", "annee": "p:annual", "ans": "p:annual",
            "mois": "p:monthly", "heure": "p:hourly", "semaine": "q",
            "year": "p:annual", "yr": "p:annual", "month": "p:monthly",
            "hour": "p:hourly", "week": "q",
        },
    ),
    (
        "par ",
        {
            "an": "p:annual", "année": "p:annual", "annee": "p:annual", "ans": "p:annual",
            "mois": "p:monthly", "heure": "p:hourly", "semaine": "q",
        },
    ),
    (
        "per ",
        {
            "annum": "p:annual", "year": "p:annual", "month": "p:monthly",
            "hour": "p:hourly", "week": "q",
        },
    ),
)

# Horizontal whitespace only: a number split across two lines is NOT a number.
_INNER_SPACE = r"[ \t\u00a0\u202f]"

# An amount: 45 000 / 60,000 / 6,000,000 / 1.5 / 45000, with an optional
# k/M scale suffix and an optional currency symbol. The left boundary is
# checked in Python (it is cheaper than a lookbehind on long texts).
_AMOUNT_RE = re.compile(
    rf"(?P<num>\d+(?:[ .,\u00a0\u202f]\d+)*){_INNER_SPACE}*(?P<unit>[kKmM])?{_INNER_SPACE}*(?P<sym>[€$£¥])?"
)

# Counters that turn an amount into a quantity of shares/units.
_UNIT_COUNTERS: frozenset[str] = frozenset({
    "unit", "units", "unite", "unites", "unité", "unités", "share", "shares", "action", "actions",
})

# Range connectors accepted between two amounts ("45-55k€", "entre 40k et 50k").
_RANGE_GAP_RE = re.compile(
    rf"^{_INNER_SPACE}*(?:-|–|—|~|bis|et|and|à|to|until|jusqu['’]?à){_INNER_SPACE}*$",
    re.IGNORECASE,
)

# First characters of a range connector — cheap pre-filter before the regex.
_RANGE_CONNECTOR_HEADS = "-–—~eabtujà"

# Counters that disqualify a currency-less "50k" (50k downloads is not a salary).
_NON_SALARY_COUNTERS: frozenset[str] = frozenset({
    "utilisateurs", "utilisateur", "user", "users",
    "visiteurs", "visiteur", "visitor", "visitors",
    "downloads", "download", "téléchargements", "telechargements",
    "abonnés", "abonnes", "subscribers", "clients", "client",
    "vues", "views", "articles", "personnes", "employés", "employes", "employees",
    "requêtes", "requetes", "requests", "lectures", "visites", "hits", "collaborateurs",
})

# Contexts that turn an amount into something else than a compensation
# ("500 000 € de budget de formation"). They are only applied to a mention
# that carries no salary keyword of its own.
_NON_SALARY_CONTEXTS: tuple[str, ...] = (
    "budget",
    "chiffre d'affaires",
    "chiffre d’affaires",
    "chiffre daffaires",
    "turnover",
    "revenue",
    "market cap",
    "valorisation",
    "capitaux",
    "levée de fonds",
    "levee de fonds",
    "funding",
    "financement externe",
    "de formation",
    "de recrutement",
    "d'équipement",
    "d’équipement",
    "equipement",
    "de marketing",
    "de voyage",
    "de voyages",
)

# Context window (characters) searched before/after an amount.
_CONTEXT_WINDOW = 40
# Maximum gap between a keyword and the amount for the keyword to qualify it.
_MAX_KEYWORD_GAP = 12
# Maximum gap between a currency token and the amount for them to be glued.
_MAX_CURRENCY_GAP = 4
# Sentence terminators that break the link between a keyword and an amount.
_TERMINATORS = ".!?;\n\r"

# Annualisation factors.
_ANNUAL_MULTIPLIER: dict[str, float] = {"annual": 1.0, "monthly": 12.0, "hourly": 2080.0}


@dataclass(slots=True)
class _AmountHit:
    """One numeric amount found in the text."""

    start: int
    end: int
    value: float
    currency: str
    scale: float
    is_percent: bool
    is_unit_count: bool
    raw: str

    @property
    def has_scale(self) -> bool:
        """True when a k/M scale suffix was applied to the amount."""
        return self.scale != 1.0


def _lowercase_aligned(text: str) -> str:
    """Lowercase copy of the text that keeps the same length (offsets stay valid)."""
    low = text.lower()
    if len(low) != len(text):
        # U+0130 lowercases to two characters: neutralise it beforehand.
        low = text.replace("\u0130", "I").lower()
    return low


def _find_needles(low: str, needles: tuple[tuple[str, str, int], ...]) -> list[tuple[int, int, str]]:
    """Find every needle occurrence on word boundaries.

    Args:
        low: Lowercased text.
        needles: (needle, payload, priority) triples, the needle being lowercase.

    Returns:
        List of (start, end, payload) sorted by position. Overlapping needles
        are resolved in favour of the longest one, then the most specific one.
    """
    hits: list[tuple[int, int, int, str]] = []
    length = len(low)
    for needle, payload, priority in needles:
        width = len(needle)
        index = low.find(needle)
        while index >= 0:
            end = index + width
            if index > 0 and low[index - 1].isalnum():
                index = low.find(needle, index + 1)
                continue
            if end < length and low[end].isalnum():
                # A trailing "s" is accepted: the plural forms share the entry.
                if low[end] != "s" or (end + 1 < length and low[end + 1].isalnum()):
                    index = low.find(needle, index + 1)
                    continue
                end += 1
            hits.append((index, -end, priority, payload))
            index = low.find(needle, index + 1)
    hits.sort()
    kept: list[tuple[int, int, str]] = []
    last_end = -1
    for start, neg_end, _priority, payload in hits:
        end = -neg_end
        if start >= last_end:
            kept.append((start, end, payload))
            last_end = end
    return kept


def _scan_prefix_periods(low: str) -> list[tuple[int, int, int, str]]:
    """Find the periodicity tokens written with a prefix ("/ mois", "par an")."""
    hits: list[tuple[int, int, int, str]] = []
    length = len(low)
    for prefix, words in _PREFIX_PERIODS:
        index = low.find(prefix)
        while index >= 0:
            cursor = index + len(prefix)
            while cursor < length and low[cursor] in " \t":
                cursor += 1
            end = cursor
            while end < length and low[end].isalpha():
                end += 1
            kind = words.get(low[cursor:end])
            if kind is not None and (end >= length or not low[end].isalnum()):
                hits.append((index, -end, 11, kind))
            index = low.find(prefix, index + 1)
    return hits


def _scan_keywords(low: str) -> list[tuple[int, int, str]]:
    """Locate every salary keyword in the lowercased text."""
    hits = _find_needles(low, _KEYWORD_NEEDLES)
    prefix_hits = _scan_prefix_periods(low)
    if not prefix_hits:
        return hits
    merged = [(start, -end, 11, payload) for start, end, payload in hits]
    merged.extend(prefix_hits)
    merged.sort()
    kept: list[tuple[int, int, str]] = []
    last_end = -1
    for start, neg_end, _priority, payload in merged:
        end = -neg_end
        if start >= last_end:
            kept.append((start, end, payload))
            last_end = end
    return kept


def _parse_number(raw: str) -> float:
    """Parse a numeric token written with FR or EN separators.

    "45 000" / "60,000" / "6,000,000" / "45.000" → thousands.
    "1.5" / "45,50" → decimals.
    """
    if raw.isdigit():
        return float(raw)
    s = raw.replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
    if "," in s and "." in s:
        # The right-most separator is the decimal one.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        parts = s.split(sep)
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            s = parts[0] + "." + parts[1]  # decimal separator
        else:
            s = "".join(parts)  # thousands separator
    return float(s)


def _split_number_groups(token: str) -> list[tuple[int, str]]:
    """Split a raw number token into sub-numbers.

    "45 000" is one number, "2020 2021" is two. A space only groups digits
    when exactly three of them follow (thousands separator).
    """
    if " " not in token and "\u00a0" not in token and "\u202f" not in token:
        return [(0, token)]
    pieces = token.replace("\u00a0", " ").replace("\u202f", " ").split(" ")
    parts: list[tuple[int, str]] = []
    offset = 0
    current = pieces[0]
    for piece in pieces[1:]:
        if len(piece) == 3 or "," in piece or "." in piece:
            current = current + " " + piece
        else:
            parts.append((offset, current))
            offset += len(current) + 1
            current = piece
    parts.append((offset, current))
    return parts


def _percent_end(text: str, end: int) -> int:
    """End offset of the amount when a percentage sign follows it.

    The "%" belongs to the amount ("10% variable"): keeping it inside the
    mention lets the keyword that follows it be attached to the right amount.
    """
    if text[end:end + 1] == "%":
        return end + 1
    if text[end:end + 2] == " %":
        return end + 2
    return end


def _unit_count_end(text: str, end: int) -> int:
    """End offset of the amount when a share/unit counter follows it.

    "5000 units" is a quantity of instruments, not a compensation amount: the
    counter stays inside the mention so the provenance remains exact.
    """
    tail = text[end:end + 24]
    cursor = 0
    while cursor < len(tail) and tail[cursor] in " \t":
        cursor += 1
    if cursor >= len(tail) or tail[cursor] not in "uUaAsS":
        return end
    stop = cursor
    while stop < len(tail) and tail[stop].isalpha():
        stop += 1
    if tail[cursor:stop].lower() in _UNIT_COUNTERS:
        return end + stop
    return end


def _adjacent_currency(
    currency_hits: list[tuple[int, int, str]],
    currency_starts: list[int],
    text: str,
    start: int,
    end: int,
) -> tuple[str, int, int]:
    """Find the currency token glued to an amount.

    Returns:
        (iso_code, start, end) of the currency, or ("", -1, -1) when there is none.
    """
    if not currency_hits:
        return "", -1, -1
    index = bisect_left(currency_starts, end)
    if index < len(currency_hits):
        hit = currency_hits[index]
        if hit[0] - end <= _MAX_CURRENCY_GAP and not text[end:hit[0]].strip():
            return hit[2], hit[0], hit[1]
    index = bisect_left(currency_starts, start) - 1
    if index >= 0:
        hit = currency_hits[index]
        if start - hit[1] <= _MAX_CURRENCY_GAP and not text[hit[1]:start].strip():
            return hit[2], hit[0], hit[1]
    return "", -1, -1


def _closest_before(
    hits: list[tuple[int, int, str]],
    starts: list[int],
    low: int,
    high: int,
) -> tuple[int, int, str] | None:
    """Closest keyword ending at or before `high` and starting at or after `low`."""
    index = bisect_right(starts, high) - 1
    while index >= 0 and starts[index] >= low:
        hit = hits[index]
        if hit[1] <= high:
            return hit
        index -= 1
    return None


def _closest_after(
    hits: list[tuple[int, int, str]],
    starts: list[int],
    low: int,
    high: int,
) -> tuple[int, int, str] | None:
    """Closest keyword starting at or after `low` and starting before `high`."""
    index = bisect_left(starts, low)
    if index < len(hits) and hits[index][0] < high:
        return hits[index]
    return None


def _belongs_to_current(keyword_end: int, amount_start: int, previous_end: int | None) -> bool:
    """True when a keyword written before an amount qualifies that amount.

    A keyword that sits closer to the previous amount belongs to it: "brut
    annuel" written after "50 000 €" qualifies that mention, not the next one.
    """
    if previous_end is None:
        return True
    return (amount_start - keyword_end) < (keyword_end - previous_end)


def _symbol_before(text: str, start: int) -> tuple[str, int]:
    """Currency symbol written just before an amount ("€45 000").

    Returns:
        (iso_code, symbol_start) or ("", -1) when there is no symbol.
    """
    index = start - 1
    while index >= 0 and text[index] in " \t\u00a0\u202f":
        index -= 1
    if index >= 0 and text[index] in _CURRENCY_SYMBOLS:
        return _CURRENCY_SYMBOLS[text[index]], index
    return "", -1


def _find_amount_hits(
    text: str,
    currency_hits: list[tuple[int, int, str]],
    currency_starts: list[int],
    keyword_hits: list[tuple[int, int, str]],
    keyword_starts: list[int],
) -> list[_AmountHit]:
    """Find every numeric amount candidate in the text.

    Candidates that carry no currency, no scale suffix and no salary keyword
    around them are dropped right away: they are ordinary numbers, not a
    compensation mention.
    """
    hits: list[_AmountHit] = []
    matches = list(_AMOUNT_RE.finditer(text))
    for position, match in enumerate(matches):
        number_text = match.group("num")
        unit = match.group("unit")
        symbol = match.group("sym")
        base = match.start("num")
        if base > 0:
            previous = text[base - 1]
            if previous.isalnum() or previous == ".":
                continue  # a digit glued to a word ("COVID19") is not an amount
        groups = _split_number_groups(number_text)
        for group_position, (offset, part) in enumerate(groups):
            last = group_position == len(groups) - 1
            start = base + offset
            end = start + len(part)
            value = _parse_number(part)
            scale = 1.0
            currency = ""

            if last:
                if unit:
                    scale = 1_000.0 if unit.lower() == "k" else 1_000_000.0
                    end = match.end("unit")
                if symbol:
                    currency = _CURRENCY_SYMBOLS[symbol]
                    end = match.end("sym")

            if not currency:
                found, found_start, found_end = _adjacent_currency(
                    currency_hits, currency_starts, text, start, end
                )
                if found:
                    currency = found
                    if found_start >= end:
                        end = found_end
                    else:
                        start = found_start
            if not currency:
                found, symbol_start = _symbol_before(text, start)
                if found:
                    currency = found
                    start = symbol_start

            # A lowercase "m" only means "million" when a currency follows,
            # otherwise it is a unit of measure ("10 m").
            if last and unit == "m" and not currency:
                scale = 1.0
            value *= scale

            number_end = base + offset + len(part)
            if not currency and scale == 1.0 and not _near_keyword(
                keyword_hits, keyword_starts, start, end
            ) and not _is_range_bound(text, matches, position, end):
                continue  # an ordinary number, not a compensation mention

            # The percentage sign and the unit counter belong to the amount:
            # they stay inside the mention, so the keyword written right after
            # them ("10% variable", "5000 units vesting") is attached to it.
            percent_end = _percent_end(text, number_end)
            unit_end = _unit_count_end(text, number_end)
            token_end = max(percent_end, unit_end, end)

            hits.append(
                _AmountHit(
                    start=start,
                    end=token_end,
                    value=value,
                    currency=currency,
                    scale=scale,
                    is_percent=percent_end > number_end,
                    is_unit_count=unit_end > number_end,
                    raw=text[start:token_end],
                )
            )
    return hits


def _is_range_bound(text: str, matches: list[re.Match[str]], position: int, end: int) -> bool:
    """True when the amount is the first bound of a range ("45-55k€")."""
    if position + 1 >= len(matches):
        return False
    following = matches[position + 1]
    gap = text[end:following.start("num")]
    stripped = gap.strip()
    if not stripped or stripped[0].lower() not in _RANGE_CONNECTOR_HEADS:
        return False
    return bool(_RANGE_GAP_RE.match(gap))


def _near_keyword(
    keyword_hits: list[tuple[int, int, str]],
    keyword_starts: list[int],
    start: int,
    end: int,
) -> bool:
    """True when a salary keyword sits right next to the amount."""
    if not keyword_hits:
        return False
    index = bisect_right(keyword_starts, start) - 1
    if index >= 0:
        hit = keyword_hits[index]
        if hit[1] <= start and start - hit[1] <= _MAX_KEYWORD_GAP:
            return True
    index = bisect_left(keyword_starts, end)
    if index < len(keyword_hits):
        hit = keyword_hits[index]
        if hit[0] - end <= _MAX_KEYWORD_GAP:
            return True
    return False


def _propagate_scale(first: _AmountHit, second: _AmountHit) -> _AmountHit:
    """Apply the scale of one bound to the other bound of a range."""
    if first.scale == second.scale:
        return first
    if first.scale != 1.0 and second.scale == 1.0:
        # The first bound already carries the scale: nothing to propagate.
        return first
    if second.scale != 1.0 and first.scale == 1.0:
        # The scale of the second bound covers the whole range ("45-55k€").
        return _AmountHit(
            start=first.start,
            end=first.end,
            value=first.value * second.scale,
            currency=first.currency,
            scale=1.0,
            is_percent=first.is_percent,
            is_unit_count=first.is_unit_count,
            raw=first.raw,
        )
    return first


def _merge_ranges(text: str, hits: list[_AmountHit]) -> list[tuple[_AmountHit, _AmountHit]]:
    """Merge two amounts joined by a range connector into a single mention."""
    groups: list[tuple[_AmountHit, _AmountHit]] = []
    index = 0
    while index < len(hits):
        current = hits[index]
        if index + 1 < len(hits):
            following = hits[index + 1]
            gap = text[current.end:following.start]
            if gap.strip() and _RANGE_GAP_RE.match(gap):
                groups.append((_propagate_scale(current, following), following))
                index += 2
                continue
        groups.append((current, current))
        index += 1
    return groups


def _gap_links(gap: str) -> bool:
    """True when a keyword and an amount are part of the same mention."""
    return len(gap) <= _MAX_KEYWORD_GAP and not any(char in gap for char in _TERMINATORS)


def _followed_by_non_salary_counter(text: str, offset: int) -> bool:
    """True when the amount is followed by a non-salary counter ("50k downloads")."""
    tail = text[offset:offset + 30]
    match = re.match(rf"^{_INNER_SPACE}*([A-Za-zÀ-ÿ'’-]+)", tail)
    if not match:
        return False
    return match.group(1).lower() in _NON_SALARY_COUNTERS


def _is_non_salary_context(low: str, start: int, end: int) -> bool:
    """True when the amount sits in a context that is not a compensation.

    "500 000 € de budget de formation" is a budget, not a salary: the amount
    is kept out of the mentions as long as no salary keyword qualifies it.
    """
    window = low[max(0, start - 30):end + 30]
    return any(needle in window for needle in _NON_SALARY_CONTEXTS)


def _excerpt(text: str, offset: int) -> str:
    """~50 characters of context around an offset (same convention as structure.py)."""
    excerpt_start = max(0, offset - 25)
    excerpt_end = min(len(text), offset + 25)
    return text[excerpt_start:excerpt_end].replace("\n", "⏎")


def _score_confidence(
    *,
    has_currency: bool,
    has_type: bool,
    has_period: bool,
    has_context: bool,
    is_range: bool,
    has_scale: bool,
    is_percent: bool,
    is_unit_count: bool,
) -> float:
    """Heuristic confidence score in [0, 1] for a mention."""
    score = 0.15
    if has_currency:
        score += 0.35
    if has_type:
        score += 0.25
    if has_period:
        score += 0.15
    if has_context:
        score += 0.10
    if is_range:
        score += 0.10
    if has_scale:
        score += 0.05
    if is_percent or is_unit_count:
        score -= 0.15
    return round(min(max(score, 0.0), 0.98), 2)


def extract_salary(text: str) -> list[SalaryEvidence]:
    """Extract salary / compensation mentions from a job offer text.

    Deterministic and fully offline: no network call, no LLM, no default value.
    Every returned evidence carries the exact provenance of the mention
    (`source_offset` + `source_excerpt`) and the normalized amounts
    (annualised, k/M expanded) expressed in the currency found in the text —
    no exchange rate is ever applied, so nothing is ever invented.

    Args:
        text: Raw text, typically an offer description.

    Returns:
        The mentions found, ordered by position in the text. Empty when the text
        carries no salary information (never a default amount).
    """
    if not text or not text.strip():
        return []

    low = _lowercase_aligned(text)

    # Keyword and currency positions (C-level substring searches).
    keyword_hits = _scan_keywords(low)
    currency_hits = _find_needles(low, _CURRENCY_NEEDLES)
    currency_starts = [hit[0] for hit in currency_hits]

    type_hits = [(hit[0], hit[1], hit[2][2:]) for hit in keyword_hits if hit[2].startswith("t:")]
    type_starts = [hit[0] for hit in type_hits]
    period_hits = [(hit[0], hit[1], hit[2][2:]) for hit in keyword_hits if hit[2].startswith("p:")]
    period_starts = [hit[0] for hit in period_hits]
    gross_hits = [(hit[0], hit[1], hit[2][2:]) for hit in keyword_hits if hit[2].startswith("g:")]
    gross_starts = [hit[0] for hit in gross_hits]
    keyword_starts = [hit[0] for hit in keyword_hits]

    hits = _find_amount_hits(text, currency_hits, currency_starts, keyword_hits, keyword_starts)
    if not hits:
        return []

    groups = _merge_ranges(text, hits)
    evidences: list[SalaryEvidence] = []
    previous_span_end: int | None = None

    for position, (first, last) in enumerate(groups):
        # The previous mention — with its own qualifiers — bounds the context:
        # "45 000 € brut annuel, variable 10%" gives "annuel" to the first
        # mention, not to the second one.
        prev_end = previous_span_end
        next_start = groups[position + 1][0].start if position + 1 < len(groups) else None

        # --- Context windows ---------------------------------------------------
        window_start = max(0, first.start - _CONTEXT_WINDOW)
        if prev_end is not None:
            window_start = max(window_start, prev_end)
        window_end = min(len(text), last.end + _CONTEXT_WINDOW)
        if next_start is not None:
            window_end = min(window_end, next_start)

        # --- Salary nature ----------------------------------------------------
        # The nature of a mention is the closest keyword around the amount:
        # the one written before it, or the one written after it when it is
        # strictly closer ("50 000 € brut + 10% variable" → "variable").
        salary_type: SalaryType = "unknown"
        keyword_adjacent = False
        keyword_start: int | None = None
        before_type = ""
        before_distance = 0
        before_hit = _closest_before(type_hits, type_starts, window_start, first.start)
        if before_hit is not None:
            gap = text[before_hit[1]:first.start]
            if _gap_links(gap) and _belongs_to_current(before_hit[1], first.start, prev_end):
                before_type = before_hit[2]
                before_distance = first.start - before_hit[1]
                keyword_start = before_hit[0]
                keyword_adjacent = not gap.strip()

        # --- Qualifier run right after the amount ("45 000 € brut annuel") ------
        qualifier_end = last.end
        qualifier_start = last.end
        index = bisect_left(keyword_starts, last.end)
        while index < len(keyword_hits):
            hit = keyword_hits[index]
            if hit[0] >= window_end:
                break
            if text[qualifier_end:hit[0]].strip():
                break
            if qualifier_start == last.end:
                qualifier_start = hit[0]
            qualifier_end = hit[1]
            index += 1

        qualifier_text = text[qualifier_start:qualifier_end] if qualifier_end > last.end else ""
        after_type = ""
        after_distance = 0
        if qualifier_text:
            index = bisect_left(type_starts, qualifier_start)
            while index < len(type_hits) and type_hits[index][0] < qualifier_end:
                hit = type_hits[index]
                if hit[1] <= qualifier_end:
                    distance = hit[0] - last.end
                    if not after_type or distance < after_distance:
                        after_type = hit[2]
                        after_distance = distance
                index += 1

        # A keyword written after the amount qualifies it too, when the two are
        # close enough and no other amount separates them ("5 000 € de bonus").
        after_hit = _closest_after(type_hits, type_starts, qualifier_end, window_end)
        if after_hit is not None and (next_start is None or after_hit[0] < next_start):
            gap = text[last.end:after_hit[0]]
            # A keyword that introduces the next amount ("variable 10%") is not
            # the one of the current amount.
            introduces_next = next_start is not None and (next_start - after_hit[0]) <= _MAX_KEYWORD_GAP
            if _gap_links(gap) and not introduces_next:
                distance = after_hit[0] - last.end
                if not after_type or distance < after_distance:
                    after_type = after_hit[2]
                    after_distance = distance

        if before_type and (not after_type or after_distance >= before_distance):
            salary_type = before_type
        elif after_type:
            salary_type = after_type

        # A gross/net pay with no other nature is the fixed salary.
        if salary_type == "unknown":
            gross_hit = None
            if qualifier_text:
                index = bisect_left(gross_starts, qualifier_start)
                if index < len(gross_hits) and gross_hits[index][0] < qualifier_end:
                    gross_hit = gross_hits[index]
            if gross_hit is None:
                candidate = _closest_before(gross_hits, gross_starts, window_start, first.start)
                if candidate is not None and _gap_links(text[candidate[1]:first.start]):
                    if _belongs_to_current(candidate[1], first.start, prev_end):
                        gross_hit = candidate
            if gross_hit is not None:
                salary_type = "base"

        # --- Periodicity -------------------------------------------------------
        periodicity: SalaryPeriodicity = "unknown"
        raw_period_text = ""
        if qualifier_text:
            index = bisect_left(period_starts, qualifier_start)
            while index < len(period_hits) and period_hits[index][0] < qualifier_end:
                hit = period_hits[index]
                if hit[1] <= qualifier_end:
                    periodicity = hit[2]
                    raw_period_text = text[qualifier_start:qualifier_end]
                index += 1
        if periodicity == "unknown":
            before_period = _closest_before(period_hits, period_starts, window_start, first.start)
            if before_period is not None:
                gap = text[before_period[1]:first.start]
                if _gap_links(gap) and _belongs_to_current(before_period[1], first.start, prev_end):
                    periodicity = before_period[2]
                    raw_period_text = text[before_period[0]:before_period[1]]

        # --- Amounts ------------------------------------------------------------
        is_range = first is not last
        is_percent = first.is_percent or last.is_percent
        is_unit_count = first.is_unit_count or last.is_unit_count
        currency = first.currency or last.currency

        if is_percent or is_unit_count:
            min_annual = None
            max_annual = None
        else:
            low_bound = min(first.value, last.value)
            high_bound = max(first.value, last.value)
            multiplier = _ANNUAL_MULTIPLIER.get(periodicity, 1.0)
            min_annual = round(low_bound * multiplier, 2)
            max_annual = round(high_bound * multiplier, 2)

        # --- Provenance ------------------------------------------------------------
        span_start = first.start
        if keyword_adjacent and keyword_start is not None:
            span_start = keyword_start
        span_end = qualifier_end if qualifier_end > last.end else last.end
        while span_end > span_start and text[span_end - 1].isspace():
            span_end -= 1
        previous_span_end = span_end

        # --- Precision guards ----------------------------------------------------
        if not currency and salary_type == "unknown" and not first.has_scale and not last.has_scale:
            continue  # a bare number without any salary signal: not a mention
        if not currency and not is_percent and not is_unit_count:
            if _followed_by_non_salary_counter(text, last.end):
                continue
        if salary_type == "unknown" and _is_non_salary_context(low, first.start, last.end):
            continue  # "500 000 € de budget de formation" is not a compensation

        raw_amount_text = text[first.start:last.end]
        raw_text = text[span_start:span_end]

        confidence = _score_confidence(
            has_currency=bool(currency),
            has_type=salary_type != "unknown",
            has_period=periodicity != "unknown",
            has_context=keyword_adjacent,
            is_range=is_range,
            has_scale=first.has_scale or last.has_scale,
            is_percent=is_percent,
            is_unit_count=is_unit_count,
        )

        evidences.append(
            SalaryEvidence(
                raw_text=raw_text,
                source_offset=span_start,
                source_excerpt=_excerpt(text, span_start),
                min_annual_eur=min_annual,
                max_annual_eur=max_annual,
                currency=currency,
                salary_type=salary_type,
                periodicity=periodicity,
                raw_amount_text=raw_amount_text,
                raw_period_text=raw_period_text,
                confidence=confidence,
            )
        )

    return evidences
