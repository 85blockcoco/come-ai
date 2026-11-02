# Contract: Python API `academics.vc`

**Feature**: `004-venture-capital-revision`

The Python API is the source of truth for the CLI and the optional HTTP facade.
All functions are pure unless they explicitly take a `VcStore`. Dates are ISO
strings (`YYYY-MM-DD`); datetimes are ISO strings. No function performs network
I/O.

## Package Exports (`academics/vc/__init__.py`)

```python
from .models import (
    CourseTopic, Concept, Flashcard, CardProgress, ReviewEvent, ReviewSession,
    FormulaDrill, CaseStudy, CaseAttempt, ExamSession, MasteryRecord, StudyPlan,
    NoteSource, ProposedCard, GlossaryEntry, ProgressReport,
)
from .storage import VcStore, default_vc_home
from .content import load_content, ContentPack
from .scheduler import (
    grade_card, select_session_cards, start_session, answer_session,
    resume_session, session_summary, due_cards,
)
from .drills import (
    parse_number, post_money, pre_money, ownership_after, dilution,
    option_pool, cap_table, liquidation_waterfall, moic, irr, tvpi, dpi, rvpi,
    grade_drill, random_drill,
)
from .cases import evaluate_case, unsupported_numbers
from .mastery import mastery_radar, build_study_plan
from .exams import build_exam, grade_exam, oral_questions
from .notes import ingest_notes, approve_proposal, reject_proposal
from .glossary import search_glossary, decode_term_sheet
from .report import build_progress_report
```

## Storage

```python
class VcStore:
    def __init__(self, home: Path | None = None) -> None: ...
    @property
    def home(self) -> Path: ...
    def load_progress(self) -> dict[str, CardProgress]: ...
    def save_progress(self, progress: dict[str, CardProgress]) -> None: ...
    def append_review(self, event: ReviewEvent) -> None: ...
    def load_reviews(self) -> list[ReviewEvent]: ...
    def load_active_session(self) -> ReviewSession | None: ...
    def save_active_session(self, session: ReviewSession) -> None: ...
    def clear_active_session(self) -> None: ...
    def append_session_history(self, summary: dict) -> None: ...
    def load_settings(self) -> dict: ...
    def save_settings(self, settings: dict) -> None: ...
    def delete_all(self, confirmation: str) -> bool: ...
```

Invariants:
- `home` defaults to `$NAGE_VC_HOME` or `~/.nage/vc`;
- directories are created with mode `0700`, files with `0600`;
- `save_progress` is atomic;
- `append_review` never rewrites existing lines;
- `delete_all` requires the exact phrase `SUPPRIMER MES DONNEES VC` and removes
  only the VC home.

## Content

```python
@dataclass(frozen=True)
class ContentPack:
    schema_version: int
    pack_id: str
    topics: tuple[CourseTopic, ...]
    cards: tuple[Flashcard, ...]
    drills: tuple[FormulaDrill, ...]
    cases: tuple[CaseStudy, ...]
    glossary: tuple[GlossaryEntry, ...]

def load_content(path: Path | None = None) -> ContentPack: ...
```

Raises `ContentError` with a readable message when a pack is invalid. The
default path is `academics/vc/content/`. Card ids, drill ids and case ids are
unique across packs.

## Scheduler

```python
def grade_card(
    progress: CardProgress,
    grade: str,
    today: str,
    *,
    event_id: str = "",
    session_id: str = "",
    duration_seconds: int = 0,
) -> tuple[CardProgress, ReviewEvent]: ...

def select_session_cards(
    cards: Sequence[Flashcard],
    progress: Mapping[str, CardProgress],
    *,
    today: str,
    limit: int = 20,
    mode: str = "quick",
    weak_topic_ids: Sequence[str] = (),
) -> list[Flashcard]: ...

def start_session(
    store: VcStore,
    content: ContentPack,
    *,
    minutes: int = 10,
    mode: str = "quick",
    today: str | None = None,
) -> ReviewSession: ...

def answer_session(
    store: VcStore,
    content: ContentPack,
    session: ReviewSession,
    grade: str,
    *,
    duration_seconds: int = 0,
) -> tuple[ReviewSession, ReviewEvent]: ...

def resume_session(store: VcStore) -> ReviewSession | None: ...

def session_summary(session: ReviewSession) -> dict: ...
```

Rules:
- `grade` is one of `again|hard|good|easy`; anything else raises `ValueError`;
- `today` is required for `grade_card`; no hidden clock;
- `select_session_cards` returns due cards first (due date, topic order, card
  id), then new cards (topic order, card id);
- `exam_eve` mode prioritizes cards from `weak_topic_ids`, then due cards;
- a card is never duplicated in one session;
- `answer_session` persists the event and the updated session atomically before
  returning;
- resuming an active session restores `cursor` and `answered` exactly.

## Drills

```python
def post_money(pre_money: float, investment: float) -> float: ...
def pre_money(post_money: float, investment: float) -> float: ...
def ownership_after(investment: float, post_money: float) -> float: ...
def dilution(existing_shares: float, new_shares: float) -> float: ...
def option_pool(pre_money: float, investment: float, pool_percent: float) -> dict: ...
def cap_table(holders: Sequence[dict], new_shares: float = 0) -> list[dict]: ...
def liquidation_waterfall(
    proceeds: float,
    holders: Sequence[dict],
    *,
    participating: bool = False,
    cap_multiple: float | None = None,
) -> list[dict]: ...
def moic(invested: float, exit_value: float) -> float: ...
def irr(cashflows: Sequence[float]) -> float | None: ...
def tvpi(contributions: float, distributions: float, residual: float) -> float: ...
def dpi(contributions: float, distributions: float) -> float: ...
def rvpi(contributions: float, residual: float) -> float: ...
```

`parse_number(raw: str, default_unit: str = "eur") -> tuple[float, str]` accepts
`10`, `10 M€`, `10m€`, `12 %`, `2.5x`, spaces and commas as thousands
separators. It raises `ValueError` on ambiguity or non-numeric input.

`grade_drill(drill, raw_answer) -> DrillResult` returns `accepted`, `expected`,
`expected_unit`, `given`, `steps`, `diagnostic`, `message`, `alternative`.
Tolerance is absolute in the canonical unit, plus a relative tolerance of
`1e-6`.

## Cases

```python
def evaluate_case(case: CaseStudy, answers: Mapping[str, str]) -> CaseAttempt: ...
def unsupported_numbers(case: CaseStudy, text: str) -> list[float]: ...
```

Rules:
- each criterion is evaluated separately;
- a criterion with `required_keywords` matches only if all are present
  (case-insensitive, accent-insensitive);
- `any_keywords` matches if at least one is present;
- `expected_numbers` matches within tolerance;
- a criterion with both keywords and numbers requires both;
- numbers in the answer that are neither in `case.allowed_numbers` nor a
  declared intermediate are listed in `unsupported_numbers`;
- the score is the weighted sum, rounded to 4 decimals;
- the model answer is returned after evaluation, never before.

## Mastery

```python
def mastery_radar(
    content: ContentPack,
    reviews: Sequence[ReviewEvent],
    *,
    today: str,
    case_attempts: Sequence[CaseAttempt] = (),
    exam_results: Sequence[dict] = (),
) -> list[MasteryRecord]: ...

def build_study_plan(
    content: ContentPack,
    radar: Sequence[MasteryRecord],
    *,
    minutes: int,
    today: str,
    exam_date: str | None = None,
) -> StudyPlan: ...
```

Rules:
- zero attempts -> `untested`, `accuracy = None`;
- `accuracy < 0.6` and at least 3 attempts -> `fragile`;
- `accuracy < 0.8` -> `developing`;
- otherwise `solid`;
- the plan never exceeds `minutes`; activities are ordered by urgency, weakness,
  due cards, then topic order;
- every activity has a `reason` string.

## Exams

```python
def build_exam(
    content: ContentPack,
    *,
    questions: int = 20,
    minutes: int = 30,
    seed: int = 0,
    topic_ids: Sequence[str] = (),
) -> ExamSession: ...

def grade_exam(exam: ExamSession, content: ContentPack) -> dict: ...
def oral_questions(content: ContentPack, topic_id: str, count: int = 5) -> list[dict]: ...
```

Rules:
- composition is deterministic for `(seed, questions, topic_ids)`;
- points sum to 100;
- a question is not repeated in one exam;
- `grade_exam` returns per-topic scores and recomputes the global score from
  the answers;
- oral questions include follow-ups but never the model answer.

## Notes

```python
def ingest_notes(
    store: VcStore,
    text: str,
    *,
    filename: str,
    topic_id: str,
) -> list[ProposedCard]: ...

def approve_proposal(store: VcStore, proposal_id: str) -> Flashcard: ...
def reject_proposal(store: VcStore, proposal_id: str) -> None: ...
```

Rules:
- every proposal has a citation `{locator, quote}`;
- no proposal is `active` before approval;
- uncertain extraction is `a_completer` with `answer = None`;
- rejecting a proposal records it and prevents automatic reintroduction;
- the source text is stored locally only, never in the repository.

## Glossary

```python
def search_glossary(content: ContentPack, query: str) -> list[GlossaryEntry]: ...
def decode_term_sheet(content: ContentPack, text: str) -> dict: ...
```

Rules:
- search is accent-insensitive and matches FR/EN terms;
- an unknown term returns an empty list and the notice `non documenté`;
- term-sheet decoding recognizes only known clause patterns; unknown clauses are
  listed in `unknown_clauses`, never invented.

## Report

```python
def build_progress_report(
    content: ContentPack,
    reviews: Sequence[ReviewEvent],
    *,
    today: str,
    days: int = 30,
    output_dir: Path | None = None,
) -> ProgressReport: ...
```

Rules:
- every number is recomputable from the inputs;
- untested topics are listed as `untested`;
- the Markdown file is written under `~/.nage/vc/reports/` by default;
- no personal note content is included.
