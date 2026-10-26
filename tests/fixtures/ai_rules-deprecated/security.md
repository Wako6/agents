# Security

### SEC-001 — Object-link rights are checked under select_for_update

Scope: services that mutate a project
Origin: WI-20260731-MAIN-012
Added: 2026-10-26
Verified: 2026-10-26
Autoload: yes

**Rule:** Role rights are verified outside the transaction; object-link rights (assigned expert, requester) are verified on the object re-read under `select_for_update`, and only that object is mutated.

**Why:** Avoids TOCTOU between the permission check and the write.

**How to apply:** Pattern: `obj = Model.objects.select_for_update().get(pk=pk)` → check link → mutate `obj`.

**Counter-indications:** read-only views.
