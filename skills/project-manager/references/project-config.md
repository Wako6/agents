# Project configuration and adapters (V3)

> The kit is universal: nothing project-specific is hard-coded in the skill. A project states its particulars in **one** small file, optionally completed by a **profile** (Markdown, project-local rules). Values that a project already keeps elsewhere are **referenced, not copied** (one source of truth).

## File

`<repo>/.claude/project-manager.config.json` (versioned with the project). Schema `pm-v3/1`:

```json
{
  "schema": "pm-v3/1",
  "work_items": {
    "backend": "ledger | gitlab-issues",
    "gitlab": {
      "referential": { "file": "CLAUDE.md", "rows": { "project": "<projet>", "integration": "<intégration>", "state_labels": "labels d'état" } },
      "project": "group/name",
      "integration_branch": "develop",
      "state_labels": ["todo", "doing", "tests", "review", "blocked"],
      "production_branch": "main"
    }
  },
  "profile": ".claude/project-manager.profile.md",
  "reading_map": ["CLAUDE.md"],
  "proof": { "command": "<command producing a PASS/FAIL proof>", "file": "ai_memory/verification.json" },
  "multi_team": { "enabled": false, "lead_in_main_checkout": true },
  "language": { "user": "fr", "memory": "en" }
}
```

- `gitlab`: either `referential` (values read from a Markdown table: a row whose first cell contains the given text; the value is the first back-quoted token of the second cell; `state_labels` takes all back-quoted tokens) **or** direct values — not both. A row that cannot be read is an **error**, never a silent default.
- `profile`: optional; can only **add** constraints (proof hooks, command forms, branch rules). It never removes a rule of the skill.
- `proof`: optional; when set, state changes towards verification/review require PASS on the current tree, and on the new `HEAD` after each commit.
- `orchestration` (pilot, optional): `enabled`, `max_parallel`, `max_attempts`, `auto_retry`, `debate` (`max_rounds`, `order`, `agents`), `teams` (`<name>: {adapter: codex-cli|claude-cli|cmd|drop|docker, label, model, settings, reviewer, docker}` — `docker`: `image` (local, never pulled), `argv`, `cpus`, `memory`, `pids`, `tmpfs_size`, `nofile`, `network` (`none` only), `agent_dir`; any other key is refused; see `docs/PILOT-DOCKER.md`), `cross_review`, `worktree_root`, `branch_prefix`, `integration_branch`, `protected_branches`, `confinement` (`native`: pmx imposes the official Claude Code sandbox and the Codex permission profile — tools confined to the worktree, no network, no Docker, no `/mnt`, no WSL interop; preflight before any agent, hard stop otherwise; mandatory in the hybrid mode), `mode` (`default` | `host-agents+docker-verification`: host CLIs with native permissions + mandatory isolated verification; pmx refuses to run unless `verify_runner` is docker, the integration policy has `require_isolated_verification: true`, every agent runs on the host and claude-cli settings deny `Bash(docker:*)`), `verify_commands`, `verify_runner` (`{adapter: host|docker, docker: {image, cpus, memory, pids, tmpfs_size, nofile, network}}`; `docker` runs every trusted test command of `verify`/`integrate` in an isolated container — `host` (default) is the 3.1 behaviour, NOT isolated), `gateway` (opt-in egress gateway for docker teams: `image`, `upstream_network`, `keys_file` (dedicated upstream keys provided by the human), `token_ttl_s`, `routes` {name: {upstream, allow_private, auth_header, key}}, `limits`, `quota`; teams opt in with docker `network: "gateway"` + `gateway_routes` [+ `gateway_quota`]; see `docs/PILOT-DOCKER.md`), `allowed_test_commands` (trusted test commands a plan may reference verbatim; with `verify_commands`, the only commands pmx ever runs — no shell, no metacharacters), `sensitive_paths` (adds to the built-in list, never removes), `integration_policy`. Requires `work_items.backend: "ledger"`. See `orchestration-pilot.md`.
- Unknown keys are reported, not ignored silently.

## Resolution (read-only)

```
python3 -I ${CLAUDE_SKILL_DIR}/scripts/pm_config.py resolve --root <repo>     # prints the resolved configuration (JSON)
python3 -I ${CLAUDE_SKILL_DIR}/scripts/pm_config.py validate --root <repo>    # exit 0 valid, 1 invalid
```

## Detection when there is no configuration file

| Signals found in the repository | Result | Manager action |
|---|---|---|
| `ai_memory/WI_COUNTER.lock` or `ai_memory/WORK_ITEMS.md` only | `ledger` | proceed (V2-compatible); propose to write the configuration |
| GitLab-registry signals only (`REPO_STATE.md` has `active_issues` / `gitlab_reachable`, `ai_memory/PENDING_GITLAB.md`, an `ai_rules/` decision naming GitLab issues as the registry, a `CLAUDE.md` referential with state labels) | `gitlab-issues` **to confirm** | ask the user to confirm (or to install the project adapter) before any registry write |
| both kinds | `conflict` | STOP: present the evidence, the user decides; nothing is written |
| none | `new-project` | propose `ledger` (default) or `gitlab-issues`; wait for the answer |

The manager **never creates a second registry** to "make things work".

## Adapters shipped with the kit

- `adapters/generic/` — example configuration for a new project (`ledger`).
- `adapters/gitlab-multi-team/` — example for a GitLab multi-team project: `gitlab-issues`, values referenced from a `CLAUDE.md` § Référentiel table (`referentiel.example.md`; a project hook may parse the same table — the adapter adds no copy), profile with typical local rules (proof hook bound to `HEAD`, one environment per worktree, literal outgoing commands, no `git stash`). Installing it in a repository is a repository change: commit and MR on explicit approval only.
