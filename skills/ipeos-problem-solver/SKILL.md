---
name: ipeos-problem-solver
description: Analyze a technical or software problem, compare solution paths, and recommend a concrete action plan in French. Use when Codex must diagnose beyond the symptom, choose between implementation options, frame tradeoffs, or produce a QUICK or DEEP recommendation before coding. In an IPEOS project, consult `ai_memory/REPO_STATE.md` and `STACK_SPEC.md` when available.
---

# IPEOS Problem Solver

Respond in French.

Analyze before recommending.

## Depth Classification

Classify the request before answering:

- `QUICK`: isolated issue, standard approach, no major architecture choice
- `DEEP`: optimization, architecture, security, performance, multi-component change, AI or ML, or any ambiguous design choice

When in doubt, choose `DEEP`.

Announce the chosen mode in one line.

## QUICK Response Shape

Use:

- `Analyse`
- `Recommandation`
- `Points d'attention`

Keep it direct and scoped.

## DEEP Response Shape

Use:

- `Analyse du probleme`
- `Contexte et contraintes`
- `Meilleures pratiques de reference`
- `Options disponibles`
- `Recommandation`
- `Plan d'action`
- `Risques et points d'attention`
- `Anti-patterns a eviter`

Compare options explicitly and choose one.

## Recommendation Rules

- Start from the existing stack.
- Do not suggest a technology change unless the gain is concrete in this context.
- Argue from measurable benefits, not from novelty.
- Give enough structure that the implementer does not need to invent the architecture.
- Call out technical debt even when it is outside the immediate plan.
- If critical context is missing, ask one targeted question instead of guessing.

## Project Context

In an IPEOS repository, read:

- `ai_memory/REPO_STATE.md`
- `STACK_SPEC.md`

If those files do not exist, ask only for the minimum context needed to produce a reliable recommendation.
