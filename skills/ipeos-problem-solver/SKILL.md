---
name: ipeos-problem-solver
description: "Structured French-language problem analysis before coding. Use at top level for technical choices, ambiguity, tradeoffs, architecture, performance, security, migrations, or failed attempts with unclear root cause. QUICK mode answers inline; DEEP mode delegates to `solution-architect` and persists a reusable analysis in `ai_doc/`. Never run inside a spawned sub-agent."
---

# IPEOS Problem Solver

Respond in French. Analyze before recommending.

Do not write code — produce a reasoned analysis the developer or the orchestrator will act on.

## Cascade Guard

This skill runs ONLY at the top level of the main Claude Code conversation.

- If you are a spawned sub-agent (developer, explorer, solution-architect, devops-engineer, etc.), do NOT invoke this skill. Solution design is either already done by the top-level controller or delegated to the `solution-architect` agent.
- Sub-agents that feel they lack design guidance must stop and return the ambiguity to the caller, not re-enter this skill.

## When to Activate

Activate at the top level when any of these is true:

- The user uses a trigger phrase listed in the description (FR or EN).
- The user asks to analyze, compare, choose, recommend, or explain a technical tradeoff.
- The user asks about architecture, performance, security, optimization, migration, or refactor strategy.
- A prior implementation attempt failed and the cause or next step is unclear.
- Multiple viable implementations exist and one must be chosen before coding.

Do not activate when:

- The task is unambiguous and mechanical (rename, typo fix, straightforward feature with a clear path).
- The user asks a pure factual or documentation question (answer directly, use `find-docs` if a library is involved).
- The user is mid-implementation and just needs the next line of code.
- You are running as a spawned sub-agent.

When in doubt between activating and answering directly, prefer activating only if a wrong choice would be costly to reverse.

## Mode Selection

Classify the request, announce the mode in one line, then follow the matching path.

- `QUICK`: isolated issue, standard approach, no architecture choice, no cross-cutting concern. Inline response, no persisted artifact.
- `DEEP`: optimization, architecture, security, performance, multi-component change, AI or ML, any ambiguous design choice, or any task that would benefit from a reusable reference document for later agents.

When in doubt, choose `DEEP`.

## QUICK Path — inline

Answer directly, in French, using this shape:

- `Analyse`
- `Recommandation`
- `Points d'attention`

Keep it direct and scoped. Do not delegate. Do not write files. Do not persist anything in `ai_doc/`.

## DEEP Path — delegated and persisted

### 1. Build the brief

- Identify the active Work Item ID if any (from the request, or from `ai_memory/WORK_ITEMS.md`).
- Derive a slug from the problem title: first 4 significant words, kebab-case, ASCII, lowercase. Example: "Optimiser le pipeline d'ingestion" → `optimiser-pipeline-ingestion`.
- Compute the output path (repo root). Ensure `ai_doc/` exists; create it if missing.
  - If a Work Item ID is known: `ai_doc/ANALYSIS__<WI-ID>__<slug>.md`
  - If no Work Item ID: `ai_doc/ANALYSIS__<slug>.md`
  - The date goes inside the document header, not in the filename — this keeps `ls ai_doc/*<WI-ID>*` a single fast lookup.
- Collect context pointers to pass to the sub-agent:
  - `STACK_SPEC.md` if present
  - `ai_memory/REPO_STATE.md` if present
  - the entry in `ai_memory/WORK_ITEMS.md` for the active work item, if any
  - specific source files or directories the user or the request points to

### 2. Delegate to `solution-architect`

Invoke the `solution-architect` sub-agent with a self-contained brief that includes:

- the problem statement (verbatim or faithfully rephrased)
- classification = `DEEP`
- required reads: the context pointers from step 1
- required output path (exact, computed in step 1): `ai_doc/ANALYSIS__<WI-ID>__<slug>.md` or `ai_doc/ANALYSIS__<slug>.md` when no WI is open
- required language: French
- required document structure (use these section titles):
  - `Analyse du problème`
  - `Contexte et contraintes`
  - `Meilleures pratiques de référence`
  - `Options disponibles`
  - `Recommandation`
  - `Plan d'action`
  - `Risques et points d'attention`
  - `Anti-patterns à éviter`
- explicit instruction: compare options and pick one
- explicit instruction: do not implement anything; produce the document only
- explicit instruction: cite the files read in the document so later agents can retrace

### 3. Close the loop

When `solution-architect` returns:

- confirm the file exists at the expected path
- report to the user: the path, a one-paragraph TL;DR, and the chosen option
- if `ai_memory/INDEX.md` exists, append one line so orchestrator and later agents can find the analysis:

  ```text
  ANALYSIS | <WI-ID or n/a> | ai_doc/ANALYSIS__<WI-ID>__<slug>.md | <short title>
  ```

- do NOT mutate `ai_memory/WORK_ITEMS.md` — that file is owned by `ipeos-manager`. If a work item is active, the manager links the document in the work item itself.

## Recommendation Rules — both modes

- Start from the existing stack.
- Do not suggest a technology change unless the gain is concrete in this context.
- Argue from measurable benefits, not from novelty.
- Give enough structure that the implementer does not need to invent the architecture.
- Call out technical debt even when it is outside the immediate plan.
- If critical context is missing, ask one targeted question instead of guessing.

## Project Context

In an IPEOS repository, both modes read or reference:

- `ai_memory/REPO_STATE.md`
- `STACK_SPEC.md`

In QUICK mode read them inline if cheap and relevant. In DEEP mode pass them to `solution-architect` via the brief.

If neither file exists, ask only for the minimum context needed to produce a reliable analysis.
