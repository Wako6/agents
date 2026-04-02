---
name: context7-cli
description: Use the globally installed ctx7 CLI to fetch up-to-date library documentation and manage Context7 skills. Activate when the user mentions "context7" or "ctx7", asks about a library/framework/API, or wants to install/search/manage skills.
---

# Context7 CLI

Use Context7 through the globally installed CLI:

```bash
ctx7
```

Prefer this skill over MCP for library and framework documentation lookups.

If `ctx7` is not available, install it globally first:

```bash
npm install -g ctx7@latest
```

## Documentation workflow

Resolve the library first, then query docs with the returned ID:

```bash
ctx7 library <name> <query>
ctx7 docs <libraryId> <query>
```

Rules:

- Always run `library` first unless the user already provides a Context7 ID like `/org/project` or `/org/project/version`.
- Use the user's actual question as the query when possible.
- Do not include secrets, tokens, passwords, or proprietary sensitive data in the query.
- Do not run more than 3 Context7 commands of each type per user question unless clearly necessary.

## Skills workflow

Use the same CLI for Context7 skill management:

```bash
ctx7 skills search <keywords>
ctx7 skills install /owner/repo [skill-name]
ctx7 skills list
ctx7 skills remove <name>
```

## Authentication

Prefer the CLI's native stored authentication in `~/.context7/credentials.json`.

Documentation commands work without authentication but have lower limits. If native credentials are missing or expired, use:

```bash
ctx7 login
```

You can also use `CONTEXT7_API_KEY` when needed, but prefer the native CLI auth store so the user does not need to re-enter credentials for each use.
