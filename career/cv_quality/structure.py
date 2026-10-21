"""Structural analysis of CV text — pure detection logic.

All detectors are deterministic, local, and offline.
Each finding includes exact provenance (source_offset + source_excerpt).
"""

from __future__ import annotations

import re
from collections import Counter

from .models import (
    CVAnalysisResult,
    DocumentInput,
    ExperienceEntry,
    Finding,
    Provenance,
    ReadabilityScore,
    SectionReading,
    STATUS_INFO,
    STATUS_RISK,
)

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

# Canonical section names (FR/EN) with keywords for detection
SECTION_KEYWORDS: dict[str, list[str]] = {
    "Expérience": [
        "experience", "experience professionnelle", "experiences",
        "work experience", "employment", "emploi", "emplois",
        "parcours professionnel", "career", "carrière",
    ],
    "Formation": [
        "formation", "education", "etudes", "études",
        "diplomes", "diplômes", "degrees", "academic",
        "scolarite", "scolarité", "cursus",
    ],
    "Compétences": [
        "competences", "compétences", "skills", "competencies",
        "technical skills", "compétences techniques", "savoir-faire",
        "expertise", "technologies", "stack",
    ],
    "Langues": [
        "langues", "languages", "language skills",
        "langue", "maîtrise", "maitrise",
    ],
    "Projets": [
        "projets", "projects", "realisations", "réalisations",
        "achievements", "portfolio", "personal projects",
        "projets personnels", "side projects",
    ],
    "Certifications": [
        "certifications", "certificates", "certifications & licenses",
        "licenses", "licences", "credentials", "badges",
    ],
}

# Required sections (missing = RISK)
REQUIRED_SECTIONS = ["Expérience", "Formation", "Compétences", "Langues", "Projets", "Certifications"]

# Quantification patterns: number + unit
QUANT_PATTERN = re.compile(
    r"""
    (?:
        \d+(?:[.,]\d+)?\s*           # Number (with optional decimal)
        (?:                          # Units
            €|EUR|eur|euros?         # Euros
            |%\s*                    # Percent
            |k€|K€|kEUR|KEUR         # k€
            |M€|M€|MEUR|Meur         # M€
            |\bk\b|\bK\b             # k / K (thousands)
            |\bM\b                   # M (millions)
            |ans?|années?|years?     # Years
            |mois|months?            # Months
            |x\d+                    # xN (multiplier)
        )
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Table detection patterns
TABLE_PATTERNS = [
    re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE),  # Markdown-style tables
    re.compile(r"^\s*\+[-+]+\+\s*$", re.MULTILINE),  # ASCII tables with +---+
    re.compile(r"(?:^|\n)\s{2,}[^\n]{20,}\s{2,}[^\n]{20,}\s*$", re.MULTILINE),  # Multi-column alignment
    re.compile(r"(?:^|\n)[^\n]*\t[^\n]*\t[^\n]*", re.MULTILINE),  # Tab-separated columns (2+ tabs = 3+ columns)
]

# Long block threshold
LONG_BLOCK_LINES = 12
LONG_BLOCK_CHARS = 800

# Repetition detection
NGRAM_SIZE = 3
REPETITION_THRESHOLD = 3

# Text ratio threshold for OCR quality
LOW_TEXT_RATIO_THRESHOLD = 0.6

# CV length threshold (~1800 useful chars ≈ 2 pages A4)
CV_MAX_USEFUL_CHARS = 1800


# ──────────────────────────────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────────────────────────────

def _make_finding(
    code: str,
    status: str,
    message: str,
    offset: int,
    text: str,
    metadata: dict | None = None,
) -> Finding:
    """Create a Finding with proper excerpt (50 chars around offset)."""
    excerpt_start = max(0, offset - 25)
    excerpt_end = min(len(text), offset + 25)
    excerpt = text[excerpt_start:excerpt_end].replace("\n", "⏎")
    return Finding(
        code=code,
        status=status,
        message=message,
        source_offset=offset,
        source_excerpt=excerpt,
        metadata=metadata,
    )


def _normalize(text: str) -> str:
    """Normalize text for comparison (lowercase, remove accents, collapse whitespace)."""
    # Simple normalization without external deps
    text = text.lower()
    # Basic accent removal
    accents = {
        "à": "a", "â": "a", "ä": "a", "é": "e", "è": "e", "ê": "e", "ë": "e",
        "î": "i", "ï": "i", "ô": "o", "ö": "o", "ù": "u", "û": "u", "ü": "u",
        "ç": "c", "ñ": "n",
    }
    for a, b in accents.items():
        text = text.replace(a, b)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences (French/English)."""
    # Simple sentence splitter
    sentences = re.split(r"[.!?]+(?:\s+|$)", text)
    return [s.strip() for s in sentences if s.strip()]


def _count_syllables_fr(word: str) -> int:
    """Rough French syllable count (vowel groups)."""
    word = word.lower()
    vowels = "aeiouyàâäéèêëîïôöùûüÿ"
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    return max(1, count)


def _word_count(text: str) -> int:
    """Count words (sequences of alphanumerics)."""
    return len(re.findall(r"\b\w+\b", text))


# ──────────────────────────────────────────────────────────────────────
# Detector 1: CV Length
# ──────────────────────────────────────────────────────────────────────

def detect_cv_length(text: str) -> list[Finding]:
    """Detect if CV exceeds ~2 pages A4 (≈1800 useful chars)."""
    findings = []
    useful_chars = len(re.sub(r"\s+", " ", text).strip())
    if useful_chars > CV_MAX_USEFUL_CHARS:
        findings.append(_make_finding(
            code="CV_TOO_LONG",
            status=STATUS_RISK,
            message=f"CV trop long ({useful_chars} caractères utiles, max recommandé ~{CV_MAX_USEFUL_CHARS})",
            offset=0,
            text=text,
            metadata={"useful_chars": useful_chars, "threshold": CV_MAX_USEFUL_CHARS},
        ))
    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 2: Missing Sections
# ──────────────────────────────────────────────────────────────────────

def detect_sections(text: str) -> tuple[list[SectionReading], list[Finding]]:
    """Detect CV sections and find missing required ones.

    Returns:
        Tuple of (detected_sections, findings_for_missing_sections).
    """
    # Work with original lines for correct offset calculation
    original_lines = text.split("\n")
    normalized_lines = [_normalize(l) for l in original_lines]
    sections: list[SectionReading] = []
    found_section_titles: set[str] = set()

    # Scan for section headers (lines that look like headers)
    for i, norm_line in enumerate(normalized_lines):
        if not norm_line or len(norm_line) > 80:
            continue

        for canonical, keywords in SECTION_KEYWORDS.items():
            if canonical in found_section_titles:
                continue
            for kw in keywords:
                if kw in norm_line and len(norm_line) < len(kw) + 20:
                    # Found a section header - use original line for offset
                    original_line = original_lines[i]
                    start_offset = text.find(original_line)
                    if start_offset == -1:
                        # Fallback: calculate from line lengths
                        start_offset = sum(len(l) + 1 for l in original_lines[:i])

                    # Find end of section (next header or end of text)
                    end_offset = len(text)
                    for j in range(i + 1, len(normalized_lines)):
                        next_norm = normalized_lines[j]
                        for _, other_kws in SECTION_KEYWORDS.items():
                            for okw in other_kws:
                                if okw in next_norm and len(next_norm) < len(okw) + 20:
                                    next_original = original_lines[j]
                                    end_offset = text.find(next_original)
                                    if end_offset == -1:
                                        end_offset = sum(len(l) + 1 for l in original_lines[:j])
                                    break
                            else:
                                continue
                            break
                        else:
                            continue
                        break

                    preview = text[start_offset:end_offset][:200].replace("\n", " ")
                    sections.append(SectionReading(
                        title=canonical,
                        start_offset=start_offset,
                        end_offset=end_offset,
                        content_preview=preview,
                    ))
                    found_section_titles.add(canonical)
                    break

    # Sort sections by offset
    sections.sort(key=lambda s: s.start_offset)

    # Detect missing required sections
    findings: list[Finding] = []
    for req in REQUIRED_SECTIONS:
        if req not in found_section_titles:
            findings.append(_make_finding(
                code="MISSING_SECTION",
                status=STATUS_RISK,
                message=f"Section obligatoire manquante : {req}",
                offset=0,
                text=text,
                metadata={"section": req},
            ))

    return sections, findings


# ──────────────────────────────────────────────────────────────────────
# Detector 3: Unquantified Experiences
# ──────────────────────────────────────────────────────────────────────

def detect_experiences(text: str, sections: list[SectionReading]) -> tuple[list[ExperienceEntry], list[Finding]]:
    """Parse experience entries and detect unquantified ones."""
    experiences: list[ExperienceEntry] = []
    findings: list[Finding] = []

    # Find the Experience section
    exp_section = None
    for s in sections:
        if s.title == "Expérience":
            exp_section = s
            break

    if not exp_section:
        return experiences, findings

    exp_text = text[exp_section.start_offset:exp_section.end_offset]

    # Split into entries — heuristic: look for date patterns or company-like lines
    # Pattern: "2020-2023 | Role | Company" or "Company | Role | 2020-2023"
    lines = exp_text.split("\n")
    current_entry: dict | None = None
    entry_start_offset = exp_section.start_offset

    date_pattern = re.compile(r"\b(?:janv|fév|mar|avr|mai|juin|juil|août|sept|oct|nov|déc|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}|\d{1,2}/\d{4}|\d{4}\b", re.IGNORECASE)

    # Skip the first line if it's just the section title
    start_idx = 0
    if lines and _normalize(lines[0].strip()) in ("experience", "experience professionnelle", "work experience", "emploi", "emplois", "parcours professionnel", "career", "carriere"):
        start_idx = 1

    for i in range(start_idx, len(lines)):
        line = lines[i]
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Check if this line has a date pattern (likely an entry header)
        has_date = bool(date_pattern.search(line_stripped))

        # Check for "Role | Company | Dates" or "Dates | Role | Company" pattern
        parts = [p.strip() for p in line_stripped.split("|")]
        is_structured_header = len(parts) >= 2 and has_date

        if (has_date or is_structured_header) and current_entry is not None:
            # Save previous entry
            _finalize_entry(current_entry, entry_start_offset, exp_section.start_offset, experiences, findings, text)

            # Start new entry
            current_entry = {"company": "", "role": "", "start_date": None, "end_date": None, "description_lines": []}
            entry_start_offset = exp_section.start_offset + exp_text.find(line)

        if current_entry is None:
            current_entry = {"company": "", "role": "", "start_date": None, "end_date": None, "description_lines": []}
            entry_start_offset = exp_section.start_offset + exp_text.find(line)

        # Parse the line
        if has_date and not current_entry["start_date"]:
            dates = date_pattern.findall(line_stripped)
            if dates:
                current_entry["start_date"] = dates[0]
                if len(dates) > 1:
                    current_entry["end_date"] = dates[1]
                elif "présent" in line_stripped.lower() or "present" in line_stripped.lower() or "actuel" in line_stripped.lower():
                    current_entry["end_date"] = "Présent"

        # If structured header with | separator, parse parts
        if is_structured_header and not current_entry["company"] and not current_entry["role"]:
            # Try to identify company and role from parts
            for part in parts:
                if date_pattern.search(part):
                    continue
                if not current_entry["role"] and len(part) < 60:
                    current_entry["role"] = part
                elif not current_entry["company"] and len(part) < 80:
                    current_entry["company"] = part

        elif line_stripped.startswith(("-", "•", "·", "*")):
            # Bullet point - part of description
            current_entry["description_lines"].append(line_stripped.lstrip("-•·* ").strip())
        elif not current_entry["company"] and len(line_stripped) < 80 and not has_date:
            current_entry["company"] = line_stripped
        elif not current_entry["role"] and len(line_stripped) < 100 and not has_date:
            current_entry["role"] = line_stripped
        else:
            current_entry["description_lines"].append(line_stripped)

    # Finalize last entry
    if current_entry is not None:
        _finalize_entry(current_entry, entry_start_offset, exp_section.start_offset, experiences, findings, text)

    return experiences, findings


def _finalize_entry(
    entry: dict,
    entry_offset: int,
    section_start: int,
    experiences: list[ExperienceEntry],
    findings: list[Finding],
    full_text: str,
) -> None:
    """Finalize an experience entry and check for quantification."""
    description = "\n".join(entry["description_lines"]).strip()
    if not description and not entry["company"] and not entry["role"]:
        return

    has_quantified = bool(QUANT_PATTERN.search(description))

    exp = ExperienceEntry(
        company=entry["company"] or "Inconnu",
        role=entry["role"] or "Non spécifié",
        start_date=entry["start_date"],
        end_date=entry["end_date"],
        description=description,
        has_quantified_result=has_quantified,
        source_offset=entry_offset,
    )
    experiences.append(exp)

    if not has_quantified and (entry["company"] or entry["role"]):
        findings.append(_make_finding(
            code="UNQUANTIFIED_EXPERIENCE",
            status=STATUS_RISK,
            message=f"Expérience sans résultat chiffré : {exp.company} — {exp.role}",
            offset=entry_offset,
            text=full_text,
            metadata={"company": exp.company, "role": exp.role},
        ))


# ──────────────────────────────────────────────────────────────────────
# Detector 4: Long Blocks
# ──────────────────────────────────────────────────────────────────────

def detect_long_blocks(text: str) -> list[Finding]:
    """Detect paragraphs > 12 lines or > 800 chars without line break."""
    findings: list[Finding] = []

    # Split by double newline (paragraphs)
    paragraphs = re.split(r"\n\s*\n", text)
    offset = 0
    for para in paragraphs:
        if not para.strip():
            offset += len(para) + 2
            continue

        lines = para.split("\n")
        char_count = len(para)

        if len(lines) > LONG_BLOCK_LINES or char_count > LONG_BLOCK_CHARS:
            findings.append(_make_finding(
                code="LONG_BLOCK",
                status=STATUS_INFO,
                message=f"Bloc long détecté ({len(lines)} lignes, {char_count} caractères)",
                offset=offset,
                text=text,
                metadata={"line_count": len(lines), "char_count": char_count},
            ))

        offset += len(para) + 2

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 5: Repetitions (3-grams)
# ──────────────────────────────────────────────────────────────────────

def detect_repetitions(text: str) -> list[Finding]:
    """Detect repeated 3-grams appearing more than 3 times."""
    findings: list[Finding] = []

    # Normalize and split into words
    words = re.findall(r"\b\w+\b", text.lower())
    if len(words) < NGRAM_SIZE:
        return findings

    # Generate 3-grams
    ngrams = [" ".join(words[i:i+NGRAM_SIZE]) for i in range(len(words) - NGRAM_SIZE + 1)]
    counts = Counter(ngrams)

    for ngram, count in counts.items():
        if count > REPETITION_THRESHOLD:
            # Find first occurrence offset
            first_idx = ngrams.index(ngram)
            # Approximate character offset
            char_offset = len(" ".join(words[:first_idx]))

            findings.append(_make_finding(
                code="REPETITION",
                status=STATUS_INFO,
                message=f"3-gramme répété {count} fois : « {ngram} »",
                offset=char_offset,
                text=text,
                metadata={"ngram": ngram, "count": count},
            ))

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 6: Tables/Columns (ATS risk)
# ──────────────────────────────────────────────────────────────────────

def detect_tables(text: str) -> list[Finding]:
    """Heuristic detection of tables/columns that break ATS parsing."""
    findings: list[Finding] = []

    for pattern in TABLE_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(_make_finding(
                code="TABLE_DETECTED",
                status=STATUS_RISK,
                message="Tableau/colonnes détectés — risque ATS (préférer texte linéaire)",
                offset=match.start(),
                text=text,
                metadata={"zone": match.group()[:50].replace("\n", "⏎")},
            ))

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 7: Low Text Ratio (OCR quality)
# ──────────────────────────────────────────────────────────────────────

def detect_low_text_ratio(text: str, page_count: int | None) -> list[Finding]:
    """Detect pages with low alphanumeric ratio (possible OCR issues)."""
    findings: list[Finding] = []

    if page_count is None or page_count <= 1:
        # Analyze whole text as one page
        alnum_count = sum(1 for c in text if c.isalnum())
        total_count = len(text)
        if total_count > 0 and (alnum_count / total_count) < LOW_TEXT_RATIO_THRESHOLD:
            findings.append(_make_finding(
                code="LOW_TEXT_RATIO",
                status=STATUS_RISK,
                message=f"Ratio texte faible ({alnum_count}/{total_count} = {alnum_count/total_count:.1%}) — OCR possible ou document image",
                offset=0,
                text=text,
                metadata={"page": 1, "ratio": alnum_count / total_count, "threshold": LOW_TEXT_RATIO_THRESHOLD},
            ))
    else:
        # Rough page split (by estimated chars per page)
        chars_per_page = max(1, len(text) // page_count)
        for page_idx in range(page_count):
            start = page_idx * chars_per_page
            end = min((page_idx + 1) * chars_per_page, len(text))
            page_text = text[start:end]
            alnum_count = sum(1 for c in page_text if c.isalnum())
            total_count = len(page_text)
            if total_count > 100 and (alnum_count / total_count) < LOW_TEXT_RATIO_THRESHOLD:
                findings.append(_make_finding(
                    code="LOW_TEXT_RATIO",
                    status=STATUS_RISK,
                    message=f"Page {page_idx+1}: ratio texte faible ({alnum_count}/{total_count} = {alnum_count/total_count:.1%})",
                    offset=start,
                    text=text,
                    metadata={"page": page_idx + 1, "ratio": alnum_count / total_count, "threshold": LOW_TEXT_RATIO_THRESHOLD},
                ))

    return findings


# ──────────────────────────────────────────────────────────────────────
# Readability Score (Flesch-Kincaid FR approximation)
# ──────────────────────────────────────────────────────────────────────

def compute_readability(text: str) -> ReadabilityScore:
    """Compute approximate French readability metrics."""
    sentences = _split_sentences(text)
    words = re.findall(r"\b\w+\b", text.lower())

    if not sentences or not words:
        return ReadabilityScore(flesch_kincaid_fr=0.0, avg_sentence_length=0.0, complex_word_ratio=0.0)

    avg_sentence_length = len(words) / len(sentences)

    # Complex words: 7+ chars (French heuristic for 3+ syllables)
    complex_words = sum(1 for w in words if len(w) >= 7)
    complex_word_ratio = complex_words / len(words) if words else 0.0

    # French Flesch-Kincaid approximation:
    # FKFR = 0.39 * avg_sentence_length + 11.8 * complex_word_ratio - 15.59
    # (Adapted from English formula with French constants)
    fk_fr = 0.39 * avg_sentence_length + 11.8 * complex_word_ratio - 15.59

    return ReadabilityScore(
        flesch_kincaid_fr=round(fk_fr, 1),
        avg_sentence_length=round(avg_sentence_length, 1),
        complex_word_ratio=round(complex_word_ratio, 3),
    )


# ──────────────────────────────────────────────────────────────────────
# Main analysis function
# ──────────────────────────────────────────────────────────────────────

def analyze_cv(document: DocumentInput) -> CVAnalysisResult:
    """Analyze a CV document for structural quality issues.

    Pure, deterministic, offline analysis. Returns all findings with provenance.

    Args:
        document: DocumentInput with text, filename, filetype.

    Returns:
        CVAnalysisResult with findings, sections, experiences, readability, provenance.
    """
    text = document.text
    all_findings: list[Finding] = []

    # 1. CV Length
    all_findings.extend(detect_cv_length(text))

    # 2. Sections (also returns detected sections)
    sections, section_findings = detect_sections(text)
    all_findings.extend(section_findings)

    # 3. Experiences & unquantified detection
    experiences, exp_findings = detect_experiences(text, sections)
    all_findings.extend(exp_findings)

    # 4. Long blocks
    all_findings.extend(detect_long_blocks(text))

    # 5. Repetitions
    all_findings.extend(detect_repetitions(text))

    # 6. Tables/Columns
    all_findings.extend(detect_tables(text))

    # 7. Low text ratio (OCR quality)
    page_count = document.page_count
    all_findings.extend(detect_low_text_ratio(text, page_count))

    # 8. Readability (info only, not a finding)
    readability = compute_readability(text)

    # Provenance
    provenance = Provenance(
        filename=document.filename,
        filetype=document.filetype,
        text_length=len(text),
        page_count=document.page_count,
        # CVBOOST-21: the exact source text is kept so that a match can
        # quote a verbatim excerpt (and its offset) instead of paraphrasing.
        source_text=text,
    )

    return CVAnalysisResult(
        findings=all_findings,
        sections=sections,
        experiences=experiences,
        readability=readability,
        provenance=provenance,
    )