# CLAUDE.md Template for Next.js 15 + SQLite SaaS

An opinionated, production-ready `CLAUDE.md` template — drop it into a
greenfield Next.js 15 + SQLite project and Claude Code immediately knows
the conventions without asking.

## What's included

- Stack & pinned versions (Next.js 15 App Router, Drizzle, Auth.js v5, Biome, Vitest, Playwright)
- Folder layout with explicit "what goes where" rules
- SQL/migration conventions (forward-only, ULIDs, money as integer cents)
- Component patterns (Server Components by default, Server Actions for mutations)
- Auth conventions (DB sessions, `auth()` helper, no client-trust)
- Zod-validated env access (no raw `process.env`)
- Anti-pattern table with rationale (10 banned patterns, each explained)
- Dev commands, test commands, DB commands
- "Where to start" guide per module
- 8 known pitfalls with mitigations
- PR checklist

## Files

- `CLAUDE.md` — the template itself (354 lines, under the 500-line cap)

## Usage

Copy to your project root:

```bash
cp CLAUDE.md /path/to/your/project/CLAUDE.md
```

Then on first Claude Code session in that repo, Claude reads it and
knows the conventions. No clarifying questions about styling, ORM
choice, or migration flow.

## Acceptance criteria (issue #2)

- [x] Covers: project structure, naming conventions, DB migration rules
- [x] Includes: dev commands, patterns to follow, anti-patterns to avoid
- [x] Opinionated — every rule has a "why this, not the alternative" reason
- [x] Usable without modification on a greenfield Next.js + SQLite project
- [x] Under 500 lines (354 lines total)
- [x] No markdown lint errors

## Test methodology

This is a TEMPLATE, not application code. "Testing" means:

1. **Lint pass**: Markdown renders correctly on GitHub (no broken tables, no broken code fences).
2. **Schema spot-check**: Every anti-pattern in §7 maps to a rule somewhere else in the doc.
3. **Greenfield smoke test**: Apply `CLAUDE.md` to a fresh `create-next-app` project + Drizzle + Auth.js scaffold; verify Claude Code can answer:
   - "Where do I add a new server action?"
   - "How do I add a column to the users table?"
   - "What's the rule for storing money?"

   without asking clarifying questions. (Run by the author before submission.)

## Wallet / Payout

For bounty payout, please use one of:
- **PayPal:** ahmadyusrizal89@gmail.com
- **USDT (EVM, Polygon/Arbitrum/Optimism):** 0x683dA5C2F75c5d6E30bA8e85C2c7f7b5d3E8b8a
- **XLM (Stellar):** GABFQ...NL6 with memo `396193324`

Preferred: PayPal or USDT (Polygon cheapest gas).
