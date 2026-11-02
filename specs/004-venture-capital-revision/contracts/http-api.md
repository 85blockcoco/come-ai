# Contract: Local HTTP Facade

**Feature**: `004-venture-capital-revision`

Status: P2, after the CLI MVP. All routes are mounted on the existing local
FastAPI app (`127.0.0.1:8765`) under `/api/vc/`. They call the same pure
functions as the CLI. No route performs network I/O.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/vc/review/start` | start or resume a review session |
| POST | `/api/vc/review/{session_id}/answer` | grade the current card |
| GET | `/api/vc/review/{session_id}` | session status |
| GET | `/api/vc/drills` | list drills, optional `topic` |
| POST | `/api/vc/drills/{drill_id}/grade` | grade one drill |
| GET | `/api/vc/cases` | list cases |
| GET | `/api/vc/cases/{case_id}` | case statement without model answer |
| POST | `/api/vc/cases/{case_id}/grade` | grade answers |
| GET | `/api/vc/radar` | mastery radar |
| POST | `/api/vc/plan` | minute-bounded plan |
| POST | `/api/vc/exams` | start a mock exam |
| POST | `/api/vc/exams/{exam_id}/submit` | submit answers |
| GET | `/api/vc/oral/{topic_id}` | oral questions |
| POST | `/api/vc/notes/ingest` | upload notes text (local only) |
| POST | `/api/vc/notes/{proposal_id}/approve` | approve a proposal |
| POST | `/api/vc/notes/{proposal_id}/reject` | reject a proposal |
| GET | `/api/vc/glossary` | search the lexicon |
| POST | `/api/vc/term-sheet/decode` | decode clauses |
| GET | `/api/vc/report` | generate a report |
| DELETE | `/api/vc/data` | delete all VC data with confirmation |

## Common Envelope

```json
{"result": {...}, "warnings": [], "blockers": []}
```

`blockers` is non-empty only for invalid input or an unavailable local store.
A blocker message is readable and never contains a stack trace or a local
absolute path.

## Example: Start Review

```http
POST /api/vc/review/start
Content-Type: application/json

{"minutes": 10, "mode": "quick", "today": "2026-11-02"}
```

```json
{
  "result": {
    "session_id": "2026-11-02T18-30-00-abc123",
    "total": 12,
    "cursor": 0,
    "current": {"card_id": "VC04-C01", "question": "..."}
  },
  "warnings": [],
  "blockers": []
}
```

## Example: Delete

```http
DELETE /api/vc/data
Content-Type: application/json

{"confirmation": "SUPPRIMER MES DONNEES VC"}
```

Deletes only `~/.nage/vc/`. A wrong phrase returns `400` and changes nothing.

## Security

- routes are available only on the loopback interface;
- no route accepts an arbitrary filesystem path for reading; notes ingestion
  accepts text or a path under `~/.nage/vc/notes/`;
- request bodies are bounded (notes: 2 MB, answers: 100 KB);
- no note content is logged;
- no CORS wildcard.
