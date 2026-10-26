# Backend `gitlab-issues` — GitLab issues as the registry (from the multi-team PM of the pilot project, generalised)

> Active only when the project configuration says `work_items.backend = "gitlab-issues"`. `<project>`, `<integration>` and the state labels come from the configuration — or from the source it designates (e.g. the `CLAUDE.md` § Référentiel table): **one source, no exception per brief**. Every `glab` command carries `-R <project>`.

## Reachability and offline mode

At start: `timeout 5 glab auth status` → record `gitlab_reachable` (true/false + timestamp) in `REPO_STATE.md`.
Unreachable: say so; work in **local mode** (specs, analyses, code); append every action to replay to `ai_memory/PENDING_GITLAB.md` (issue to create, label to set, MR to open). **Never simulate a GitLab state.**

## Issue lifecycle

`todo` → `doing` → `tests` → `review` → human merge → issue **closed by the manager**. One state label at a time; a change always removes the previous one (`--label <new> --unlabel <old>`). `blocked` replaces the current state; the blocking note gives: exact blocker, hypothesis, recommended action, **state to restore**.

Who sets what:
- manager: creates the issue (`todo`, or `blocked` alone if a dependency is not integrated), replaces `blocked` by `todo` when the dependency is integrated, closes after verified merge, reassigns;
- feature-lead: `doing`, `tests`, `review`, `blocked` on **its own issue only**, each change with a note (`glab issue note`) carrying the evidence.

## Reference commands (each outgoing one needs its own approval)

```
glab issue create -R <project> --title "F1 — <title>" --description "$(cat docs/specs/F1-<slug>.md)" --label todo
glab issue create -R <project> --title "F2 — <title>" --description "$(cat docs/specs/F2-<slug>.md)" --label blocked   # dependency not integrated
glab issue update <NN> -R <project> --label doing --unlabel todo
glab issue note   <NN> -R <project> --message "doing: branch feat/<slug>-<NN>, worktree created"
glab issue update <NN> -R <project> --label tests --unlabel doing
glab issue update <NN> -R <project> --label blocked --unlabel <state>      # + note with the state to restore
glab mr create -R <project> --draft --fill --source-branch feat/<slug>-<NN> --target-branch <integration> --label review
glab issue update <NN> -R <project> --label review --unlabel tests
glab issue update <NN> -R <project> --label todo --unlabel blocked        # manager, dependency integrated
glab issue close  <NN> -R <project>                                       # manager, after verified merge
for l in <state labels>; do echo "== $l"; glab issue list -R <project> --label "$l"; done
```
- `glab issue create` has no `--description-file` (glab 1.53): pass the content with `--description "$(cat …)"`.
- Never `glab issue list --label a,b,c`: GitLab combines labels with AND; with one label per issue it returns nothing.
- MR fallback if `glab mr create` fails (remote resolution) — same approval as the MR, literal description path:
  `glab api --method POST projects/<id-or-encoded-path>/merge_requests -f source_branch=<branch> -f target_branch=<integration> -f "title=Draft: <title>" -F description=@ai_doc/MR__#<NN>.md -F remove_source_branch=false -F squash=false`.
  `--input -` triggers an extra approval: show the JSON body to the user first.
- An MR towards a non-default branch does not close the issue automatically: the manager closes it.

## Dependencies

Description line: `Depends on: #NN (must be integrated into <integration>)`. The dependent issue is created `blocked` alone. It is unblocked only after the integration check below returns **INTÉGRÉE** for every dependency; its branch is then created from an up-to-date `origin/<integration>` — never from a `feat/*` branch, never from the production branch. `review` on a dependency is not enough.

## Verify that an MR is integrated (S7)

No assumption on the merge strategy (merge commit, squash, fast-forward) nor on the fields it fills: read what GitLab returns, then confront it with the target branch.

1. Read and record the real data (copied into the verification note):
```
glab mr view <MR> -R <project> -F json | python3 -c '
import json, sys
m = json.load(sys.stdin)
for k in ("state", "target_branch", "merged_at", "merge_commit_sha", "squash_commit_sha", "sha"):
    print(k, "=", m.get(k, "<ABSENT>"))'
```
   An absent, null or empty SHA field is not an anomaly: it is simply not a candidate. If `glab mr view -F json` no longer provides `state`, `target_branch` or any SHA, read-only fallback: `glab api "projects/<encoded path>/merge_requests/<MR>"` (GET only).
2. Candidates = every non-empty value among `merge_commit_sha`, `squash_commit_sha`, `sha`. For each (a fetch is itself an approved operation in projects that require it):
```
git fetch origin
git cat-file -e "<sha>^{commit}" && git merge-base --is-ancestor "<sha>" "origin/<integration>" && echo "ancestor: <sha>"
```
   Where local fetches are restricted, the same ancestry can be read from the API: `glab api "projects/<encoded>/repository/merge_base?refs[]=<sha>&refs[]=<head>"` (result = `<sha>` ⇔ ancestor), and parents from `repository/commits/<sha>`.
3. Verdict, recorded with the data of step 1:

| `state` = `merged` and `target_branch` = `<integration>` | ≥ 1 candidate ancestor of `origin/<integration>` | Verdict |
|---|---|---|
| yes | yes | **INTÉGRÉE** (record the candidate) |
| no | no | **NON INTÉGRÉE** (merged into another target, production especially → immediate escalation) |
| yes | no (no candidate, not found after fetch, not ancestor) | **INCERTAINE** — no reliable proof |
| no | yes | **INCERTAINE** — contradictory checks |
| `state` or `target_branch` unreadable | — | **INCERTAINE** |

4. Only **INTÉGRÉE** unblocks. NON INTÉGRÉE / INCERTAINE → the dependent issue **stays `blocked`**, the note quotes the raw data; the manager decides or escalates. Never unblock by deduction. Feature-lead side: the retained candidate must also be an ancestor of its branch (`git merge-base --is-ancestor "<sha>" HEAD`), otherwise STOP, `blocked`, report.

## Branches, MR and approvals (generic part; a project profile may add stricter rules)

- Every branch (`feat/*`, `chore/*`) starts from `origin/<integration>`; every MR targets `<integration>`, in draft. The production branch is never a base nor a target.
- One explicit approval per operation: `git commit`, then `git push`, then MR creation, then each `glab issue create`. An approval covers only the named operation.
- If the project has a proof command: after every commit, re-run it and obtain PASS on the new `HEAD` before asking for the push.
- The lead session runs its commands from the **main checkout root** and reaches team worktrees only by absolute path or `git -C <worktree>` (read-only) — never `cd` into a team worktree. Never `git stash` (the stash stack is shared by all worktrees).
- Never read CI/CD variable values, tokens, keys or integration settings through `glab` or the API; never change project settings.

## Collisions

Before launching two sessions, compare the specs' "files probably touched". Non-empty intersection → sequence, or re-split.

## Review triage in this backend

Blocker/Critical outside the feature scope → new issue (with approval), `todo`, `Origin: review <report>#ISSUE-xxx`; Major → new issue `todo`; Minor/Trivial → backlog section of an issue « Dette — <module> ». See `review-triage.md`.
