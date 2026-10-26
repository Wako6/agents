# Pitfalls

### PIT-001 — Celery beat skips tasks on DST rollover

Scope: scheduled jobs
Origin: incident 2026-03
Added: 2026-03-22
Verified: 2026-03-22
Deprecated: 2026-09-01 — Celery removed, superseded by DEC-004
Autoload: yes

**Pitfall:** Beat computed the next run in local time and skipped the DST hour.

**Why:** historical.

**How to apply:** n/a.
