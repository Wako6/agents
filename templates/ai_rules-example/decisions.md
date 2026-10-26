# Decisions

### DEC-001 — Tailwind via Play CDN, no JS build

Scope: templates
Origin: migrated from REPO_STATE.md
Added: 2026-10-26
Verified: 2026-10-26

**Decision:** Styling uses the Tailwind Play CDN; the project has no JS build step.

**Why:** Internal tool, small team, no front-end toolchain to maintain.

**How to apply:** Do not add npm/webpack/vite; put utility classes in templates.

**Counter-indications:** revisit if a production CSP forbids the CDN.
