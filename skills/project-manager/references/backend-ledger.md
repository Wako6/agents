# Backend `ledger` — local Work Item registry (from V2, unchanged in substance)

> Active only when the project configuration says `work_items.backend = "ledger"` (or detection found an existing ledger). Never used in a `gitlab-issues` project.

## Identifier

Format: `WI-YYYYMMDD-<BSLUG>-###`.

`BSLUG` from the current git branch: `git rev-parse --abbrev-ref HEAD` → strip `feature/`, `feat/`, `fix/`, `hotfix/`, `bugfix/`, `release/` → keep alphanumerics → first 6 chars → uppercase. No git → `NONGIT`.
Examples: `main` → `MAIN`; `feature/fix-auth` → `FIXAUT`; `fix/WI-123` → `WI123`.

## Collision-safe reservation protocol

1. Derive `BSLUG`.
2. Read `ai_memory/WI_COUNTER.lock`.
3. Find `BSLUG=WI-YYYYMMDD-BSLUG-###`.
4. Stored date = today → increment; otherwise start at `001`.
5. Upsert **that line only** (never rewrite the file) before any delegation.
6. Lock missing → scan `ai_memory/WORK_ITEMS.md` and `ai_doc/` for the highest ID of that slug, create the lock, continue.

Uniqueness not verifiable → stop, `BLOCKED`.

`WI_COUNTER.lock`:
```text
MAIN=WI-20260325-MAIN-004
FIXAUT=WI-20260325-FIXAUT-001
```

## `ai_memory/WORK_ITEMS.md`

Reservation entry: ID · date/time · short title · status `OPEN` · TOA · primary executor · `attempt_count = 0`. Keep current: status, attempts, owners, note links, pending clarifications, linked `ai_doc/ANALYSIS__<WI>__*.md`, optional `depends_on`, `parent`, `Origin: review <report>#<issue>`. Backlog section for Minor/Trivial review findings.

## `ai_memory/INDEX.md`

```text
WI-YYYYMMDD-BSLUG-### | Short Title | Status | Roles | Note path(s)
ANALYSIS | <WI-ID or n/a> | ai_doc/ANALYSIS__<WI-ID>__<slug>.md | <short title>
```

## Archiving

`DONE` notes older than 7 days → `ai_memory/archive/` (via `memory-clean.md`, never automatically).

## Outgoing operations (ledger projects)

Same approval rule as everywhere: one explicit approval per operation (commit, push, PR/MR creation). A forge CLI (`gh`/`glab`) is optional; absent → the user opens PRs/MRs by hand and the WI records the link.
