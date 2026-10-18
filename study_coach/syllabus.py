"""Revision programme built from a course, with verifiable source references.

The syllabus builder is heuristic and deterministic.  Its one hard rule:

    every notion, keyword and question is copied from the ingested text, and
    the character range of the excerpt always matches the course.

When the course does not say something, the builder reports a ``Gap``
(``information_absente`` / ``information_ambigue``) instead of filling the hole
with a plausible-sounding sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .errors import SyllabusError
from .models import (
    STUDY_DOMAIN,
    SYLLABUS_VERSION,
    Gap,
    Notion,
    SourceRef,
    StudyDocument,
    Syllabus,
    clean_text,
    content_words,
    normalize_text,
    unit_label,
    utc_now,
)
from .numeric import extract_numeric_facts, split_sentences

MIN_STATEMENT_CHARS = 40
MAX_STATEMENTS_PER_SECTION = 6

_HEADING_PATTERNS = (
    re.compile(r"^\s*(#{1,6})\s+(\S.*)$"),
    re.compile(r"^\s*((?:chapitre|chapter|section|partie|module)\b[\s:.-]*.{0,80})$", re.IGNORECASE),
    re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+([A-ZÀ-ÖØ-Ý][^:]{2,80})$"),
    re.compile(r"^\s*((?:[IVXLC]+)\.)\s+([A-ZÀ-ÖØ-Ý][^:]{0,80})$"),
    re.compile(r"^\s*([A-ZÀ-ÖØ-Ý][A-ZÀ-ÖØ-Ý '\-/]{4,60})\s*$"),
)

_DEFINITION_RE = re.compile(
    r"^(?:Le[su]?\s+|La?\s+|L'|Une?\s+|Ce[t]?\s+|Cette\s+)"
    r"(?P<term>[\wÀ-ÿ'\-()]{2,30}(?:\s+[\wÀ-ÿ'\-()]{2,30}){0,5}?)\s+"
    r"(?P<verb>se\s+définit|est\s+défini|correspond\s+à|correspondent\s+à|consiste\s+en|"
    r"dépend\s+de|résulte\s+de|sert\s+à|est|sont|désigne|désignent|représente|représentent|"
    r"signifie|signifient|indique|indiquent|montre|montrent|comprend|comprennent|contient|"
    r"contiennent|définit|exprime|exprime|traduit|traduit|caractérise|caractérisent|mesure|"
    r"mesurent|rapporte|engage|donne|permet|vaut|valent)\b",
    re.IGNORECASE,
)
# Same rule without the leading ``^``: used to re-anchor a definition that a
# glued course heading pushed to the right (``"3. Le bilan Le bilan est…"``).
# It is only ever applied through ``_definition_match``, which validates the
# term, so an unanchored search can never accept an arbitrary fragment.
_DEFINITION_INNER_RE = re.compile(_DEFINITION_RE.pattern[1:], _DEFINITION_RE.flags)

_STRONG_DEFINITION_VERBS = {
    "defini",
    "definit",
    "designe",
    "signifie",
    "correspond",
    "consiste",
    "caracterise",
    "mesure",
}
_INNER_DETERMINER_RE = re.compile(r"(?:^|\s)(?:Le|La|Les|L'|Un|Une|Ce|Cet|Cette)\s", re.IGNORECASE)
_DETERMINER_START_RE = re.compile(r"(?:\b(?:Le[su]?|La?|L'|Une?|Ce[t]?|Cette)\s+)", re.IGNORECASE)
# Words proving that the matched "term" is a clause and not a concept.
_FORBIDDEN_TERM_WORDS = frozenset(
    """
    dont qui que quoi lequel laquelle lesquels desquelles cela celui celle on si donc alors mais or ne pas
    """.split()
)
_FORMULA_LINE_RE = re.compile(r"^\s*[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ_]{1,10}\s*=\s*\S")
# Labels that structure a course without naming a concept.
_GENERIC_TERM_LABELS = frozenset(
    """
    exemple exemples note notes remarque remarques cas definition introduction conclusion objectif objectifs
    resume synthese rappel attention plan partie chapitre fiche precision
    """.split()
)
_LEADING_CLAUSE_RE = re.compile(
    r"^(?:Dans|Au|Aux|Pour|Selon|Nous|Notre|Ce|Cet|Cette|En|Sur)\b[^,]{0,40},\s*", re.IGNORECASE
)
_ABBREVIATIONS = frozenset({"etc", "p", "pp", "cf", "ex", "n", "m", "mr", "mme", "dr", "art", "fig", "env", "nb"})
_VALUE_VERB_RE = re.compile(
    r"\s+(?:vaut|valent|est de|sont de|représente|atteint|égale|égalent|s'élève à|monte à)\s+",
    re.IGNORECASE,
)
_GLOSSARY_RE = re.compile(r"^(?P<term>[\wÀ-ÿ'\- ]{2,42}?)\s*[:：]\s*(?P<definition>\S.{10,})$")
_BULLET_RE = re.compile(r"^\s*(?:[-*•·]|\d+[.)])\s+(?P<content>\S.*)$")
# A sentence that starts with a course heading glued to its body.
_HEADING_PREFIX_RE = re.compile(r"^(?:\d{1,2}(?:\.\d+)*[.)]\s+|#[A-Za-z0-9 \t]{0,4})")


@dataclass
class _Block:
    """A paragraph (or a bullet) of the course, with its exact line range."""

    start: int
    end: int  # exclusive
    text: str
    bullet: bool = False
    truncated_start: bool = False
    truncated_end: bool = False


@dataclass
class _Section:
    title: str
    level: int
    heading_line: int
    blocks: list[_Block]
    is_preamble: bool = False


def _sentences(line: str) -> list[str]:
    return split_sentences(line)


def _looks_like_heading(line: str, *, truncated_end: bool = False) -> tuple[int, str] | None:
    stripped = line.strip()
    if not stripped:
        return None
    if truncated_end:
        # A heading cut by the 420 character window of the document store is not
        # a heading: acting on it would invent a section the course lacks.
        return None
    if stripped.endswith(".") and not stripped.startswith("#"):
        return None
    for index, pattern in enumerate(_HEADING_PATTERNS):
        match = pattern.match(stripped)
        if not match:
            continue
        level = {
            0: len(match.group(1)),
            1: 1,
            2: min(1 + match.group(1).count("."), 3),
            3: 1,
            4: 2,
        }[index]
        title = _heading_title(stripped)
        if not title or len(title.split()) > 10:
            continue
        if _DEFINITION_RE.match(title):
            # "1. Une provision est une retenue…" is a sentence, not a chapter.
            continue
        return level, title
    return None


def _heading_title(line: str) -> str:
    stripped = line.strip().lstrip("#").strip()
    stripped = re.sub(r"^\d+(?:\.\d+)*[.)]?\s*", "", stripped)
    stripped = re.sub(
        r"^(?:chapitre|chapter|section|partie|module)\b[\s:.-]*", "", stripped, flags=re.IGNORECASE
    )
    return stripped.strip().rstrip(":").strip()


def _ends_a_sentence(line: str) -> bool:
    """True when a wrapped line also terminates a sentence (new paragraph)."""

    stripped = line.rstrip()
    if not stripped:
        return False
    if stripped.endswith(("!", "?", ";", ":")):
        return True
    if not stripped.endswith("."):
        return False
    last_word = stripped[:-1].split(" ")[-1].lower().strip("(\"")
    return last_word not in _ABBREVIATIONS


def _parse_blocks(
    lines: list[str],
    *,
    forced_breaks: frozenset[int] = frozenset(),
    line_flags: list[str] | None = None,
) -> list[tuple[str | None, list[_Block]]]:
    """Split the course into (heading, blocks) sections, headings included.

    Wrapped lines are merged back into their paragraph, while a line that ends a
    sentence, an isolated formula (``VAN = ...``), a bullet or the first line of
    a retrieved passage always opens a new block, so that two different ideas
    never share a citation.
    """

    sections: list[tuple[str | None, list[_Block]]] = []
    heading: str | None = None
    pending: list[str] = []
    pending_start = 0
    flags = list(line_flags or [])

    def _flags(start: int, end: int) -> tuple[bool, bool]:
        """Truncation marks of the block boundaries, if the source provided any."""

        first = flags[start] if start < len(flags) else ""
        last = flags[end - 1] if 0 <= end - 1 < len(flags) else ""
        return "truncated_start" in first, "truncated_end" in last

    def flush(end_line: int) -> None:
        nonlocal pending
        if not pending:
            return
        if not sections:
            sections.append((None, []))
        truncated_start, truncated_end = _flags(pending_start, end_line)
        sections[-1][1].append(
            _Block(pending_start, end_line, " ".join(pending), False, truncated_start, truncated_end)
        )
        pending = []

    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if not stripped:
            index += 1
            continue
        truncated_end = index < len(flags) and "truncated_end" in flags[index]
        heading_match = _looks_like_heading(raw, truncated_end=truncated_end)
        if heading_match:
            flush(index)
            sections.append((heading_match[1], []))
            heading = heading_match[1]
            index += 1
            continue
        if index in forced_breaks:
            # One retrieved passage = one reviewable block.  A passage that
            # starts a new heading-less part also starts a new section, so that
            # unrelated windows never compete for the same notion budget.
            # Exception: if the flushed block does not end a sentence, it is a
            # fragment that should stay in the same section so that
            # _merge_continuations can re-join it with the next passage.
            flush(index)
            last_block = sections[-1][1][-1] if sections and sections[-1][1] else None
            if last_block is not None and not _ends_a_sentence(last_block.text):
                # Incomplete fragment: remain in the current section for merging.
                pending_start = index
            elif pending or (sections and sections[-1][1]):
                if heading is None:
                    sections.append((None, []))
                pending_start = index
        bullet = _BULLET_RE.match(stripped)
        if bullet:
            flush(index)
            if not sections:
                sections.append((None, []))
            sections[-1][1].append(_Block(index, index + 1, bullet.group("content").strip(), bullet=True))
            index += 1
            continue
        if pending and _ends_a_sentence(pending[-1]):
            flush(index)
        if _FORMULA_LINE_RE.match(stripped):
            # A formula is always a reviewable block of its own.
            flush(index)
            if not sections:
                sections.append((None, []))
            sections[-1][1].append(_Block(index, index + 1, stripped))
            pending_start = index + 1
            index += 1
            continue
        if not pending:
            pending_start = index
        pending.append(stripped)
        index += 1
    flush(len(lines))
    if heading is not None and not pending and not sections:
        sections.append((heading, []))
    return sections


class _ExcerptFactory:
    """Build :class:`SourceRef` objects whose excerpt matches the course bytes."""

    def __init__(self, document: StudyDocument) -> None:
        self.document = document
        self.lines = document.lines
        self.offsets: list[int] = []
        position = 0
        for line in self.lines:
            self.offsets.append(position)
            position += len(line) + 1
        # Passages supplied by the Côme AI document store keep their page here.
        self.passages = list(document.metadata.get("passages") or [])

    def _passage_for(self, line_number: int) -> dict[str, Any]:
        for passage in self.passages:
            if passage.get("line_start") and passage["line_start"] <= line_number <= (passage.get("line_end") or 0):
                return passage.get("citation") or {}
        return {}

    def refs(self, start: int, end: int) -> list[SourceRef]:
        """One reference per retrieved passage covered by the block.

        A sentence rebuilt from several passages keeps one verifiable reference
        per passage, so the learner is pointed back to each original location.
        """

        if not self.passages:
            return [self.ref(start, end)]
        boundaries: list[tuple[int, int]] = []
        for index in range(start, end):
            citation = self._passage_for(self.document.line_number(index))
            if not citation:
                continue
            line_start = citation.get("line_start")
            line_end = citation.get("line_end")
            if line_start is None or line_end is None:
                continue
            if boundaries and boundaries[-1][1] == index - 1 and boundaries[-1][0] == line_start:
                boundaries[-1] = (boundaries[-1][0], index + 1)
            else:
                boundaries.append((index, index + 1))
        references = [self.ref(*segment) for segment in boundaries]
        return references or [self.ref(start, end)]

    def ref(self, start: int, end: int, *, label: str = "") -> SourceRef:
        start = max(0, min(start, max(0, len(self.lines) - 1)))
        end = max(start + 1, min(end, len(self.lines)))
        excerpt = "\n".join(self.lines[start:end])
        char_start = self.offsets[start]
        char_end = self.offsets[end - 1] + len(self.lines[end - 1])
        document_line_start = self.document.line_number(start)
        document_line_end = self.document.line_number(end - 1)
        citation = self._passage_for(document_line_start)

        # Source coordinates: the original document, when the course was rebuilt
        # from the Côme AI document store.  Otherwise the document coordinates.
        source_line_start = citation.get("line_start")
        source_line_end = citation.get("line_end")
        source_page = citation.get("page")

        locator: dict[str, Any] = {
            "document_line_start": document_line_start,
            "document_line_end": document_line_end,
            "char_start": char_start,
            "char_end": char_end,
            "domain": STUDY_DOMAIN,
        }
        if citation:
            if source_line_start is not None:
                locator["line_start"] = source_line_start
            if source_line_end is not None:
                locator["line_end"] = source_line_end
            if source_page is not None:
                locator["page"] = source_page
            if citation.get("sheet"):
                # Spreadsheet citations are self-describing in the store contract.
                locator["sheet"] = citation["sheet"]
                locator["row_start"] = citation.get("row_start")
                locator["row_end"] = citation.get("row_end")
            if citation.get("chunk_id"):
                locator["chunk_id"] = citation["chunk_id"]
        else:
            locator["line_start"] = document_line_start
            locator["line_end"] = document_line_end
        locator["label"] = label or str(citation.get("label") or "")
        return SourceRef(
            source_id=self.document.source_id,
            title=self.document.title,
            excerpt=excerpt,
            locator=locator,
        )


def _acceptable_term(term: str) -> bool:
    tokens = [token for token in normalize_text(re.sub(r"[^A-Za-zÀ-ÿ0-9' \-]", " ", term)).split(" ") if token]
    if not tokens or len(tokens) > 6:
        return False
    return not any(token in _FORBIDDEN_TERM_WORDS for token in tokens)


def _fallback_title(statement: str, section_title: str) -> str:
    value_split = _VALUE_VERB_RE.split(statement, maxsplit=1)
    subject = _LEADING_CLAUSE_RE.sub("", value_split[0]).strip(" ,;:")
    if 2 <= len(subject.split()) <= 8 and _acceptable_term(subject):
        return subject[:120] or section_title[:120]
    words = statement.split()
    head = " ".join(words[:6])
    return head + ("…" if len(words) > 6 else "")


def _forced_breaks(document: StudyDocument) -> frozenset[int]:
    """Line indexes where a retrieved passage starts (citation precision)."""

    breaks: set[int] = set()
    for passage in document.metadata.get("passages") or []:
        try:
            index = int(passage.get("line_start") or 0) - document.base_line
        except (TypeError, ValueError):
            continue
        if index > 0:
            breaks.add(index)
    return frozenset(breaks)


def _collect_notions(document: StudyDocument, excerpts: _ExcerptFactory) -> tuple[list[Notion], list[Gap]]:
    sections = _parse_blocks(
        document.lines,
        forced_breaks=_forced_breaks(document),
        line_flags=document.metadata.get("line_flags"),
    )
    notions: list[Notion] = []
    gaps: list[Gap] = []
    seen_statements: dict[str, Notion] = {}
    section_order: list[_Section] = []

    for heading_title, blocks in sections:
        section = _Section(
            title=heading_title or document.title,
            level=1,
            heading_line=blocks[0].start if blocks else 0,
            blocks=blocks,
            is_preamble=heading_title is None,
        )
        section_order.append(section)
        blocks = _merge_continuations(blocks)
        section.blocks = blocks
        body_chars = sum(len(block.text) for block in blocks)
        is_document_title = normalize_text(section.title) == normalize_text(document.title)

        if not blocks:
            # A heading with no body carries no content: there is nothing to
            # clarify, so it must not become a false "ambiguous information".
            continue

        produced = 0
        for block in blocks:
            references = excerpts.refs(block.start, block.end)
            ref = references[0]
            candidates = _candidates_for_block(block, section.title)
            for candidate in candidates:
                statement = clean_text(candidate["statement"], limit=800)
                key = normalize_text(statement)
                if not key:
                    continue
                if key in seen_statements:
                    previous = seen_statements[key]
                    for extra in references:
                        if extra not in previous.source_refs:
                            previous.source_refs.append(extra)
                    continue
                if produced >= MAX_STATEMENTS_PER_SECTION:
                    break
                title = clean_text(candidate["title"] or _fallback_title(statement, section.title), limit=120)
                notion = Notion(
                    id="",
                    title=title,
                    statement=statement,
                    source_refs=list(references),
                    keywords=content_words(f"{title} {statement}", limit=10),
                    importance=2,
                    status="extraite",
                    section=section.title,
                    explicit_term=bool(candidate["explicit_term"]),
                    numeric_facts=candidate["numeric_facts"],
                )
                notions.append(notion)
                seen_statements[key] = notion
                produced += 1

        if produced == 0:
            fallback_sentences = [
                sentence
                for sentence in _admissible_sentences(blocks[0])
                if len(sentence) >= 60
            ]
            if fallback_sentences and not is_document_title:
                # A cited statement is still reviewable even without a definition verb.
                statement = fallback_sentences[0]
                notion = Notion(
                    id="",
                    title=_fallback_title(statement, section.title),
                    statement=statement,
                    source_refs=list(references),
                    keywords=content_words(statement, limit=10),
                    importance=1,
                    status="extraite",
                    section=section.title,
                    explicit_term=False,
                    numeric_facts=extract_numeric_facts(statement),
                )
                notions.append(notion)
                seen_statements[normalize_text(statement)] = notion
                produced = 1

        if produced == 0 and body_chars > 0 and not is_document_title:
            gaps.append(
                Gap(
                    id="",
                    kind="information_ambigue",
                    topic=section.title,
                    reason=(
                        f"La section « {section.title} » ne contient aucune définition exploitable "
                        f"({body_chars} caractères de contenu)."
                    ),
                    clarification_question=f"Peux-tu préciser ce que dit le cours sur « {section.title} » ?",
                    source_refs=[excerpts.ref(blocks[0].start, blocks[0].end)],
                )
            )

    _score_importance(notions, section_order)
    _flag_conflicts(notions, gaps)
    return notions, gaps


_CONTINUATION_RE = re.compile(r"^[^A-ZÀ-ÖØ-Ýa-z0-9]?[a-zà-öø-ÿ]")


def _merge_continuations(blocks: list[_Block]) -> list[_Block]:
    """Re-join a sentence split across two retrieved passages.

    A block that does not end on a sentence boundary and whose successor starts
    with a lower-case word is the same sentence, cut in two by the retrieval.
    Merging them restores the full wording; the citations stay per passage.
    """

    merged: list[_Block] = []
    for block in blocks:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and not _ends_a_sentence(previous.text)
            and _CONTINUATION_RE.match(block.text.lstrip())
        ):
            # Two halves of the same cut sentence: the merge restores it, so the
            # truncation marks of the shared boundary no longer apply.
            healed_start = previous.truncated_start and not block.truncated_start
            healed_end = block.truncated_end and not previous.truncated_end
            merged[-1] = _Block(
                start=previous.start,
                end=block.end,
                text=f"{previous.text} {block.text}".strip(),
                bullet=previous.bullet,
                truncated_start=previous.truncated_start if not block.truncated_start else healed_start,
                truncated_end=healed_end,
            )
            continue
        merged.append(block)
    return merged


def _is_heading_prefix(prefix: str) -> bool:
    """True when the text before a candidate definition looks like a heading.

    It must be short, free of clause words (``Un projet dont la VAN est…`` must
    not be re-anchored on ``la VAN``) and made of few words.
    """

    stripped = prefix.strip()
    if not stripped or len(stripped) > 60:
        return False
    words = stripped.split()
    if not words or len(words) > 8:
        return False
    tokens = {token.strip(".,;:!?").casefold() for token in words}
    return not tokens & _FORBIDDEN_TERM_WORDS


def _definition_match(sentence: str) -> tuple[re.Match[str] | None, str]:
    """Find the definition inside a sentence, ignoring a glued heading prefix.

    ``"3. Les flux disponibles Le flux de trésorerie disponible est…"`` really
    defines *le flux de trésorerie disponible*: when the first match swallows an
    inner determiner (``Les flux disponibles Le flux…``), the match is re-anchored
    on the last determiner of the sentence and the returned statement starts
    there, which also keeps the graded wording free of the heading.

    The re-anchoring is deliberately conservative: it only fires when the first
    match *does* swallow an inner determiner, so a plain sentence keeps its
    first match.

    Implementation note: candidate positions are scanned with
    ``_DETERMINER_START_RE`` and re-matched with ``_DEFINITION_INNER_RE`` at that
    offset, because ``finditer`` cannot return two **overlapping** matches and
    would otherwise stop after the first glued definition.
    """

    first = _DEFINITION_RE.match(sentence)
    if first and not _INNER_DETERMINER_RE.search(first.group("term")) and _acceptable_term(first.group("term")):
        return first, sentence

    best = first
    for determiner in _DETERMINER_START_RE.finditer(sentence):
        if determiner.start() == 0:
            continue
        if not _is_heading_prefix(sentence[: determiner.start()]):
            continue
        candidate = _DEFINITION_INNER_RE.match(sentence, determiner.start())
        if candidate is not None and (best is None or candidate.start() > best.start()):
            best = candidate
    if best is None or not _acceptable_term(best.group("term")):
        # A match that does not name a real concept is not a definition.
        return None, sentence
    statement = sentence[best.start():]
    if len(statement.strip()) < 20:
        # A definition too short to stand on its own is not a notion.
        return None, sentence
    return best, statement


def _admissible_sentences(block: _Block) -> list[str]:
    """Sentences of a block that are complete enough to be reviewed.

    A sentence cut by the retrieval (the document store ends its 420 character
    window with ``…``) is incomplete: half a sentence cannot be graded against
    the course, so it never becomes a notion.
    """

    sentences = _sentences(block.text)
    if not sentences:
        return []
    first_index = 1 if block.truncated_start else 0
    last_index = len(sentences) - (1 if block.truncated_end else 0)
    return sentences[first_index:max(last_index, first_index)]


def _candidates_for_block(block: _Block, section_title: str) -> list[dict[str, Any]]:
    """Propose notions found in one block; every candidate stays a verbatim quote."""

    candidates: list[dict[str, Any]] = []
    sentences = _admissible_sentences(block)
    if block.bullet:
        body = block.text.strip()
        if len(body) >= 20 and sentences and not (block.truncated_start or block.truncated_end):
            definition, statement = _definition_match(body)
            term = definition.group("term").strip(" .") if definition else ""
            candidates.append(
                {
                    "title": term,
                    "statement": statement if definition else body,
                    "explicit_term": bool(term),
                    "numeric_facts": extract_numeric_facts(body),
                }
            )
        return candidates

    for sentence in sentences:
        definition, statement = _definition_match(sentence)
        if definition and _acceptable_term(definition.group("term")):
            candidates.append(
                {
                    "title": definition.group("term").strip(" ."),
                    "statement": statement,
                    "explicit_term": True,
                    "numeric_facts": extract_numeric_facts(statement),
                }
            )
            continue
        if definition is not None and statement is not sentence:
            continue
        glossary = _GLOSSARY_RE.match(sentence)
        if glossary and len(glossary.group("term").split()) <= 5 and _acceptable_term(glossary.group("term")):
            definition_text = glossary.group("definition").strip()
            term = glossary.group("term").strip()
            candidates.append(
                {
                    "title": term,
                    "statement": f"{term} : {definition_text}",
                    "explicit_term": normalize_text(term) not in _GENERIC_TERM_LABELS,
                    "numeric_facts": extract_numeric_facts(definition_text),
                }
            )
            continue
        facts = extract_numeric_facts(sentence)
        if facts:
            candidates.append(
                {
                    "title": "",
                    "statement": sentence,
                    "explicit_term": False,
                    "numeric_facts": facts,
                }
            )
    return candidates


def _score_importance(notions: list[Notion], sections: list[_Section]) -> None:
    section_levels = {section.title: section.level for section in sections}
    for notion in notions:
        score = 2
        if notion.numeric_facts:
            score += 1
        statement_normalized = normalize_text(notion.statement)
        if any(verb in statement_normalized for verb in _STRONG_DEFINITION_VERBS):
            score += 1
        if section_levels.get(notion.section, 2) <= 1:
            score += 1
        if len(notion.statement.strip()) < MIN_STATEMENT_CHARS:
            score -= 1
        if len(notion.statement) > 400:
            score -= 1
        notion.importance = max(1, min(3, score))


def _flag_conflicts(notions: list[Notion], gaps: list[Gap]) -> None:
    """Mark notions the course states twice with different wordings."""

    by_title: dict[str, list[Notion]] = {}
    for notion in notions:
        by_title.setdefault(normalize_text(notion.title), []).append(notion)
    for title, group in by_title.items():
        if len(group) < 2 or not title:
            continue
        statements = {normalize_text(notion.statement) for notion in group}
        if len(statements) < 2:
            continue
        note = "Notion énoncée plusieurs fois avec des formulations différentes dans le cours."
        for notion in group:
            notion.status = "ambigue"
            notion.ambiguity_note = note
            notion.importance = max(1, notion.importance - 1)
        gaps.append(
            Gap(
                id="",
                kind="information_ambigue",
                topic=group[0].title,
                reason=note,
                clarification_question=(
                    f"Le cours utilise plusieurs définitions pour « {group[0].title} ». "
                    "Laquelle faut-il retenir ?"
                ),
                source_refs=list(group[0].source_refs),
            )
        )


def _missing_topic_gaps(notions: list[Notion], title: str, requested_topics: Iterable[str]) -> list[Gap]:
    gaps: list[Gap] = []
    haystack = normalize_text(" ".join(f"{notion.title} {notion.statement} {notion.section}" for notion in notions))
    for raw_topic in requested_topics or ():
        topic = clean_text(raw_topic, limit=120)
        if not topic:
            continue
        normalized_topic = normalize_text(topic)
        if normalized_topic and normalized_topic in haystack:
            continue
        gaps.append(
            Gap(
                id="",
                kind="information_absente",
                topic=topic,
                reason=f"Aucun passage de « {title} » ne traite de {topic}.",
                clarification_question=(
                    f"Peux-tu fournir le passage du cours sur {topic} ? Sans lui, aucune question ne peut être posée."
                ),
            )
        )
    return gaps


def _assign_ids(notions: list[Notion], gaps: list[Gap]) -> None:
    used: set[str] = set()
    for position, notion in enumerate(notions, start=1):
        slug = normalize_text(notion.title)[:24].replace(" ", "_") or "notion"
        candidate = f"not_{position:02d}_{slug}"
        while candidate in used:
            candidate = f"{candidate}_b"
        used.add(candidate)
        notion.id = candidate
    used_gap: set[str] = set()
    for position, gap in enumerate(gaps, start=1):
        slug = normalize_text(gap.topic)[:24].replace(" ", "_") or "trou"
        candidate = f"gap_{position:02d}_{slug}"
        while candidate in used_gap:
            candidate = f"{candidate}_b"
        used_gap.add(candidate)
        gap.id = candidate


def build_syllabus(
    document: StudyDocument,
    *,
    max_notions: int = 24,
    notions_per_session: int = 5,
    requested_topics: Iterable[str] = (),
    include_numeric_gap: bool = True,
) -> Syllabus:
    """Turn a course into notions, a revision programme and reported gaps."""

    if not isinstance(document, StudyDocument):
        raise SyllabusError("Un document de cours StudyDocument est requis.")
    if not clean_text(document.text):
        raise SyllabusError(f"Le cours « {document.title} » est vide : aucun programme de révision possible.")

    excerpts = _ExcerptFactory(document)
    notions, gaps = _collect_notions(document, excerpts)
    gaps.extend(_missing_topic_gaps(notions, document.title, requested_topics))

    has_numeric = any(notion.numeric_facts for notion in notions)
    if include_numeric_gap and not has_numeric:
        gaps.append(
            Gap(
                id="",
                kind="information_absente",
                topic="Exercices numériques",
                reason="Le cours ne contient aucun chiffre avec unité : aucun exercice numérique ne peut être construit.",
                clarification_question="Peux-tu ajouter un énoncé chiffré (formule, exemple ou exercice) au cours ?",
            )
        )

    limit = max(1, int(max_notions or 24))
    ordered = sorted(notions, key=lambda notion: -notion.importance)[:limit]
    stable = sorted(ordered, key=lambda notion: notions.index(notion))
    _assign_ids(stable, gaps)

    return Syllabus(
        id=f"syll_{document.document_id}",
        document_id=document.document_id,
        title=document.title,
        notions=stable,
        gaps=gaps,
        program=build_program(stable, notions_per_session=notions_per_session),
        created_at=utc_now(),
        syllabus_version=SYLLABUS_VERSION,
    )


def build_program(notions: list[Notion], *, notions_per_session: int = 5) -> list[dict[str, Any]]:
    """Split the notions into ordered review sessions (most important first)."""

    step_size = max(1, min(int(notions_per_session or 5), 10))
    program: list[dict[str, Any]] = []
    for start in range(0, len(notions), step_size):
        chunk = notions[start:start + step_size]
        if not chunk:
            continue
        index = len(program) + 1
        program.append(
            {
                "index": index,
                "label": f"Séance {index} — {chunk[0].title[:60]}",
                "notion_ids": [notion.id for notion in chunk],
                "notion_count": len(chunk),
                "estimated_minutes": 2 + 2 * len(chunk),
                "importance": max(notion.importance for notion in chunk),
            }
        )
    return program


def syllabus_to_markdown(syllabus: Syllabus, *, max_excerpt_chars: int = 160) -> str:
    """Readable programme, used by the demo and by the handoff documents."""

    lines = [f"# Programme de révision — {syllabus.title}", ""]
    for step in syllabus.program:
        lines.append(f"## {step['label']} (~{step['estimated_minutes']} min)")
        for notion_id in step["notion_ids"]:
            notion = syllabus.notion(notion_id)
            if not notion:
                continue
            excerpt = notion.statement
            if len(excerpt) > max_excerpt_chars:
                excerpt = excerpt[: max_excerpt_chars - 1] + "…"
            flag = " ⚠️ ambigu" if notion.is_ambiguous else ""
            lines.append(f"- **{notion.title}**{flag} — {excerpt}")
            lines.append(f"  - source : {notion.source_refs[0].citation_label if notion.source_refs else '—'}")
        lines.append("")
    if syllabus.gaps:
        lines.append("## À clarifier avant de réviser")
        for gap in syllabus.gaps:
            lines.append(f"- [{gap.kind}] {gap.topic} : {gap.reason}")
        lines.append("")
    return "\n".join(lines)
