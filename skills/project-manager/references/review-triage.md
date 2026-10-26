# Review triage (V3 — manager only, never delegated)

> Loaded when a reviewer (`backend-reviewer-analyst`, `frontend-reviewer-analyst`, `django-reviewer`, an optional Flutter reviewer) or an optional adversarial review returns a report. Reviewers return their report **inline**; you record it first under `ai_doc/reports/<KIND>_REVIEW_REPORT__<WI>.md` (and their role note under `ai_memory/`).

## Procedure

For every issue of the report:

| Finding | Action |
|---|---|
| inside the reviewed work item's scope, before its commit | fixed in that work item (`developer`), new evidence (and new proof PASS if the project has a proof command), new `verifier` run in `complex`; no new work item |
| Blocker / Critical outside the scope | new work item immediately (GitLab: issue creation = outgoing operation → user approval), open/`todo`, delegated as soon as possible |
| Major | new work item, open/`todo`, user informed |
| Minor / Trivial | backlog: ledger → backlog section of `WORK_ITEMS.md`; GitLab → backlog section of an issue « Dette — <module> » |

Every created work item carries `Origin: review <report path>#<issue-id>`, `attempt_count = 0` (ledger), and a link to the parent work item.

## Summary to the user

Number of issues by severity · created work items · backlog entries · whether the parent can move to review/closure or must wait for the blockers.

## Proposed Rules

Reviewers never emit `Proposed Rules`. A recurring systemic issue is noted in the parent closure and, at the user's discretion, becomes a documentation work item routed to `developer` or `solution-architect` (the only roles allowed to propose rules), then `rules-curator` (two-step triage). The manager never pushes a rule to `ai_rules/` directly.
