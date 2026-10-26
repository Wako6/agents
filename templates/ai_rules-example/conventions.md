# Conventions

### CONV-001 — Services own business logic; views stay thin

Scope: Django apps (views, services)
Origin: migrated from REPO_STATE.md
Added: 2026-10-26
Verified: 2026-10-26
Autoload: yes
Paths: src/**/views.py, src/**/services.py

**Rule:** All mutations go through a service function; a view filters the perimeter, calls the service, translates exceptions, redirects (PRG).

**Why:** Single mutation path, testable without HTTP, no business rules duplicated across views.

**How to apply:** Never call `.save()` / `.create()` from a view; add or extend a service instead.

**Counter-indications:** none.
