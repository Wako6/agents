# Review Triage

> Loaded only when `frontend-reviewer-analyst` or `backend-reviewer-analyst` returns a report. The triage is the manager's job — it cannot be delegated.

## Procedure

Read the produced report (`ai_doc/reports/FRONTEND_REVIEW_REPORT.md` or `ai_doc/reports/BACKEND_REVIEW_REPORT.md`) and triage every issue:

- **Blocker or Critical**: create a new work item immediately and delegate to `developer`.
- **Major**: create a new work item, record it as `OPEN`, inform the user.
- **Minor or Trivial**: record it in the backlog section of `ai_memory/WORK_ITEMS.md`.

Every created work item gets a fresh ID via the reservation protocol in `work-items.md`, with:

- `Origin: review <report path>#<issue-id>`
- `attempt_count = 0`
- a link back to the parent work item in the memory notes

## Summary format

After triage, summarize to the user:

- number of issues by severity
- created work items and their IDs
- backlog items recorded
- whether the parent work item can still be closed, or whether it must remain `READY_FOR_REVIEW` until the blockers land

## Proposed Rules from reviewers

Reviewers do NOT emit a `Proposed Rules` section directly. If the reviewer flagged a recurring systemic issue worth codifying (e.g. "every endpoint without rate limiting should fail review"), note it in the parent WI closure and, at the user's discretion, open a dedicated documentation work item that routes a `Proposed Rules` entry through `developer` or `solution-architect` — those are the only roles allowed to propose rules.

Never short-circuit by having the manager push the rule directly to `ai_rules/`. The curator path stays single-source.
