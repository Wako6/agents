# ai_rules — durable knowledge index

Format: <TOPIC> | <ID> | <short title> | <file>#<id-lower> | Verified: YYYY-MM-DD
Single writer: rules-curator (invoked by project-manager). Entries with `Autoload: yes` are exported to .claude/rules/ by rules_sync.py.

CONVENTION | CONV-001 | Services own business logic; views stay thin | conventions.md#conv-001 | Verified: 2026-10-26
SECURITY   | SEC-001  | Object-link rights are checked under select_for_update | security.md#sec-001 | Verified: 2026-10-26
DECISION   | DEC-001  | Tailwind via Play CDN, no JS build | decisions.md#dec-001 | Verified: 2026-10-26
# DEPRECATED PITFALL | PIT-001 | Celery beat skips tasks on DST rollover | pitfalls.md#pit-001 | Verified: 2026-03-22
