# Contract: Local Storage

**Feature**: `004-venture-capital-revision`

## Location

```text
default:   ~/.nage/vc/
override:  $NAGE_VC_HOME
tests:     tmp_path / "vc"
```

The override must be an absolute path. A relative path is rejected with a
readable error. The directory is created with mode `0700`; files are created
with mode `0600`. Symlinks are refused.

## Files

| File | Format | Purpose |
|------|--------|---------|
| `progress.json` | JSON object | `{"schema_version": 1, "cards": {...}}` |
| `reviews.jsonl` | JSONL | one `ReviewEvent` per line, append-only |
| `sessions/active.json` | JSON | resumable session |
| `sessions/history.jsonl` | JSONL | completed session summaries |
| `deck.json` | JSON | approved imported cards + version history |
| `notes/index.json` | JSON | note sources and proposals |
| `notes/<source_id>.txt` | UTF-8 text | normalized source snapshot |
| `exams/active.json` | JSON | current exam |
| `exams/history.jsonl` | JSONL | completed exam summaries |
| `reports/<date>-progress.md` | Markdown | generated report |
| `settings.json` | JSON | language, exam date, daily capacity |

## Atomicity

For JSON files:

1. write `name.tmp` in the same directory;
2. `flush()` and `os.fsync()`;
3. `os.replace(name.tmp, name)`;
4. optionally `fsync` the directory.

For JSONL: open with `O_APPEND`, write one line, `flush`, `fsync`. A malformed
line is skipped on read and reported in `warnings`; it never crashes the app.

## Corruption and Recovery

- A missing file is treated as empty, not as an error.
- An invalid `progress.json` is backed up as `progress.json.corrupt-<timestamp>`
  and replaced by an empty state; the CLI prints a warning.
- A partially written session is discarded; review events already appended are
  kept.
- `delete_all` removes the VC home only after the exact confirmation phrase.

## Privacy

- no learner note content is written to the repository;
- no note content is written to logs;
- report files contain progress only, not raw answers or note text;
- `settings.json` contains no email, name or account id.

## Backup

The user may copy `~/.nage/vc/` while the app is stopped. The app does not
upload backups. A future export command writes a single JSON archive under
`~/.nage/vc/exports/`.
