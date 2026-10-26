# Protocol — problem solving (ex skill `project-problem-solver`, logic unchanged)

> Executed by the manager in the lead session when the intent is analysis / decision. Never inside a subagent. Answer in French. Analyse before recommending; no code.

## When

Technical choice, ambiguity, trade-off, architecture, performance, security, migration, optimisation, refactor strategy; several viable implementations; a failed attempt with unclear cause.
Not when: mechanical task (rename, typo, clear feature), pure factual/documentation question (answer directly; use Context7 `ctx7` CLI or connector if installed for library/framework/API questions), the user just needs the next line of code. Doubt → activate only if a wrong choice would be costly to reverse.

## Mode

Announce in one line.
- `QUICK`: isolated issue, standard approach, no architecture choice → inline answer: **Analyse** · **Recommandation** · **Points d'attention**. No delegation, no file.
- `DEEP`: optimisation, architecture, security, performance, multi-component, AI/ML, ambiguous design, or a reusable reference is useful. Doubt → `DEEP`.

## DEEP

1. **Brief**: active work item (`<WI>`) if any (registry of the configured backend); slug = first 4 significant words, kebab-case ASCII; output path `ai_doc/ANALYSIS__<WI>__<slug>.md` (or `ai_doc/ANALYSIS__<slug>.md`), date inside the document. Before delegating, reuse an existing analysis covering the same scope with an unchanged stack.
2. **Delegate to `solution-architect`** (Agent tool). The prompt contains: the problem (verbatim or faithful); `DEEP`; reads (`STACK_SPEC.md`, `ai_memory/REPO_STATE.md`, the work-item entry or issue, `ai_rules/INDEX.md` + relevant topics, pointed files); exact output path; French; sections `Analyse du problème`, `Contexte et contraintes`, `Meilleures pratiques de référence`, `Options disponibles` (2–3), `Recommandation` (one option, why the others are rejected, invalidating conditions), `Plan d'action` (ordered steps, files, anti-scope, expected tests), `Risques et points d'attention` (≤ 5), `Anti-patterns à éviter`, `Fichiers lus`; compare and pick one; implement nothing.
3. **Close the loop**: check the file exists; give the user the path, a one-paragraph TL;DR and the chosen option. Ledger backend: append to `ai_memory/INDEX.md` `ANALYSIS | <WI or n/a> | <path> | <short title>`. GitLab backend: post the path in a note on the issue only with the user's approval (it is an outgoing write); otherwise mention it in the next status. The manager links the analysis to the work item.

## Recommendation rules (both modes)

Start from the existing stack; change technology only for a concrete, measurable gain; never "because it is modern"; give enough structure that the implementer has no architecture choice left; call out technical debt even outside the plan; if a recommendation contradicts an `ai_rules/` entry, say so explicitly — the user decides; missing critical context → one targeted question.

## Optional second opinion (extension, never required)

If the plan includes it and the capability is detected (`extension-points.md`): Claudex debate or Codex adversarial review on the analysis. Unresolved disagreements go to the user.
