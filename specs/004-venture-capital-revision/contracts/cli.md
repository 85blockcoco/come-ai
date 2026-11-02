# Contract: `nage.py vc` CLI

**Feature**: `004-venture-capital-revision`

All commands are local, offline and deterministic for the same inputs. `--json`
prints one JSON object to stdout and nothing else. Errors print a readable
message to stderr and exit with code `2`; a valid but empty result exits `0`.

Global defaults:
- data directory: `~/.nage/vc/` (override `NAGE_VC_HOME`);
- date: local today (override `--today YYYY-MM-DD`);
- language: French, English VC terms preserved.

## Review

```bash
nage.py vc review --minutes 10
nage.py vc review --minutes 10 --json
nage.py vc review --session <id> --reveal --json
nage.py vc review --session <id> --grade good --json
nage.py vc review --session <id> --status --json
```

`review --minutes N` starts a session, or resumes the active one, and prints the
first question. Interactive mode (no `--json`) asks for `Enter` to reveal, then
reads one of `again|hard|good|easy`, and repeats until the queue is empty.

JSON output for start/next:

```json
{
  "session_id": "2026-11-02T18-30-00-abc123",
  "mode": "quick",
  "target_minutes": 10,
  "cursor": 0,
  "total": 12,
  "done": 0,
  "current": {
    "card_id": "VC04-C01",
    "topic_id": "VC04",
    "question": "Une société vaut 8 M€ pre-money. Un investisseur met 2 M€. Quel est le post-money ?",
    "due_date": "2026-11-02",
    "reason": "nouvelle carte"
  },
  "summary": null
}
```

`--reveal` adds `"answer"` and `"explanation"` to `current`.
`--grade` accepts `again|hard|good|easy` and returns the next card plus
`"last_result": {"card_id": "...", "grade": "good", "due_after": "2026-11-03"}`.
When the queue is empty, `"current": null` and `"summary"` is populated:

```json
{
  "seen": 12,
  "correct": 9,
  "to_consolidate": 3,
  "minutes": 9.4,
  "due_tomorrow": 8,
  "topics": {"VC04": {"seen": 4, "correct": 3}}
}
```

`--status` returns the same shape without changing the cursor.

## Formula Lab

```bash
nage.py vc drill list [--topic VC04] [--json]
nage.py vc drill run VC04-D01 [--answer 10] [--json]
nage.py vc drill random [--topic VC04] [--seed 7] [--answer 10] [--json]
```

`list` returns `{"drills": [{"id", "topic_id", "prompt", "difficulty"}]}`.
`run` without `--answer` returns the prompt and variables but not the answer.
With `--answer`, it returns:

```json
{
  "drill_id": "VC04-D01",
  "accepted": true,
  "expected": 10.0,
  "expected_unit": "m_eur",
  "given": {"value": 10.0, "unit": "m_eur"},
  "steps": [
    {"label": "Formule", "expression": "post_money = pre_money + investment", "result": 10.0}
  ],
  "diagnostic": null,
  "alternative": null
}
```

On failure, `accepted` is false and `diagnostic` is one of
`formula|order|unit|missing_data|convention`, with a readable `message`.
Non-numeric input returns `accepted: false`, `diagnostic: "unit"`, and does not
change any state.

## Case Studio

```bash
nage.py vc case list [--topic VC03] [--json]
nage.py vc case show VC03-CASE01 [--json]
nage.py vc case grade VC03-CASE01 --answers answers.json [--json]
```

`answers.json` maps question ids to text:

```json
{"q1": "Post-money = 10 M€ ...", "q2": "L'investisseur détient 20 % ..."}
```

Result:

```json
{
  "case_id": "VC03-CASE01",
  "score": 0.75,
  "criteria": [
    {"question_id": "q1", "criterion_id": "q1-c1", "label": "Post-money correct", "earned": 0.25, "max": 0.25, "matched": true}
  ],
  "unsupported_numbers": [42.0],
  "model_answer": "...",
  "notice": "Correction par critères, pas une note humaine."
}
```

## Radar and Plan

```bash
nage.py vc radar [--today 2026-11-02] [--json]
nage.py vc plan --minutes 60 [--exam-date 2026-12-15] [--json]
```

Radar:

```json
{
  "topics": [
    {"topic_id": "VC04", "title": "Pre-money, post-money", "attempts": 12, "accuracy": 0.58, "status": "fragile", "due_cards": 4, "top_errors": ["formula"]}
  ],
  "untested": ["VC19"],
  "generated_at": "2026-11-02T18:30:00"
}
```

Plan:

```json
{
  "date": "2026-11-02",
  "capacity_minutes": 60,
  "total_minutes": 55,
  "activities": [
    {"kind": "review", "ref_id": "VC04", "topic_id": "VC04", "minutes": 20, "reason": "4 cartes dues + taux de réussite 58 %"}
  ]
}
```

## Mock Exam and Oral

```bash
nage.py vc exam start --questions 20 --minutes 30 --seed 7 [--json]
nage.py vc exam submit <exam_id> --answers answers.json [--json]
nage.py vc oral <topic_id> [--count 5] [--json]
```

`exam start` returns the questions without answers. `exam submit` returns the
score, per-topic scores, elapsed time and weak topics. An expired exam keeps all
answers and is graded with `"status": "expired"`.

## Notes

```bash
nage.py vc notes ingest notes.md --topic VC04 [--json]
nage.py vc notes list [--json]
nage.py vc notes approve <proposal_id> [--json]
nage.py vc notes reject <proposal_id> [--json]
```

`ingest` returns proposals with citations. It never activates a card. `approve`
adds the card to `deck.json`; `reject` records the rejection and prevents
automatic reintroduction.

## Glossary and Term Sheet

```bash
nage.py vc glossary search "liquidation preference" [--json]
nage.py vc term-sheet decode term_sheet.txt [--json]
```

`glossary search` returns `{"matches": [...]}`; an unknown term returns
`{"matches": [], "notice": "non documenté"}`. `term-sheet decode` returns one
entry per recognized clause and an `unknown_clauses` list; it never invents a
clause.

## Report

```bash
nage.py vc report [--days 30] [--json]
```

Writes `~/.nage/vc/reports/<date>-progress.md` and returns the sections and the
path. The report contains no personal data beyond the learner's own progress.

## Delete

```bash
nage.py vc delete --confirm "SUPPRIMER MES DONNEES VC"
```

Deletes only `~/.nage/vc/`. The confirmation phrase is required. It never
touches Career data, `data/`, `output/` or `memory_data/`.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | success, including an empty result |
| 2 | invalid input, missing file, or unknown id |
| 3 | local storage permission or write failure |
| 4 | content pack invalid or unsupported schema |
