# CLAUDE.md — Next.js 15 + SQLite SaaS Template

> **Read this first.** Every section exists because a previous engineer (probably you) lost an afternoon to the thing it warns about. If you change a rule, update the rationale. If you can't articulate the rationale, the rule shouldn't exist.

---

## 1. Stack & versions

| Layer | Choice | Pinned version | Why this, not the alternative |
|---|---|---|---|
| Framework | Next.js 15 App Router | `15.x` | Server Components + Server Actions; we don't need a separate API layer |
| Language | TypeScript | `5.4+` (strict) | Strict mode is non-negotiable; one `any` per file is the cap |
| Runtime | Node 20 LTS | `>=20.10` | Matches Vercel defaults; don't try Bun yet |
| DB | SQLite (better-sqlite3) | `>=11` | Synchronous API = simpler transactions; WAL mode for concurrency |
| ORM | Drizzle | `>=0.30` | We picked Drizzle over Prisma because generated clients add 80 MB and we want readable SQL |
| Auth | Auth.js (NextAuth v5) | `>=5.0.0-beta` | Sessions in DB, not JWT — see §5 |
| Validation | Zod | `>=3.23` | One schema source of truth; reused on client + server |
| Styling | Tailwind CSS | `>=3.4` | No CSS-in-JS. Period. |
| Lint/format | Biome | `>=1.8` | 10x faster than ESLint+Prettier, one config |
| Testing | Vitest + Playwright | latest | Vitest for units, Playwright for e2e |

> If you add a new dep over 50 KB, justify it in the PR description.

---

## 2. Folder structure

```
src/
├── app/                      # Next.js App Router (routes ONLY)
│   ├── (marketing)/          # public marketing pages, no auth
│   ├── (app)/                # authenticated app routes
│   │   ├── dashboard/
│   │   └── settings/
│   ├── api/                  # route handlers (only for webhooks/external)
│   └── layout.tsx            # root layout — keep it boring
├── server/                   # ALL server-side logic
│   ├── actions/              # 'use server' actions — one file per domain
│   ├── db/                   # schema, migrations, queries
│   │   ├── schema.ts         # Drizzle table definitions
│   │   ├── migrations/       # generated SQL files (commit these!)
│   │   └── queries/          # named query functions, not inline SQL
│   ├── auth/                 # Auth.js config, session helpers
│   └── services/             # business logic — pure functions where possible
├── components/               # React components (server + client)
│   ├── ui/                   # primitives (Button, Input, Card) — keep <50 lines each
│   └── features/             # composed feature components
├── lib/                      # framework-agnostic utilities
│   └── env.ts                # zod-validated env access (see §6)
└── styles/                   # global CSS only
```

**Rules:**

- `app/` contains route segments and `layout.tsx`. No business logic. Imports from `server/`, never the other way.
- `server/actions/*` is the ONLY place where mutations happen from the client. UI components call server actions; they never call `fetch('/api/...')` from a button.
- `server/db/queries/*` exports named functions like `getUserById(id)`, not raw Drizzle objects. Components must not import from `schema.ts` directly.

---

## 3. SQL & migration conventions

### Migrations

```bash
# Generate migration from schema changes
pnpm db:generate

# NEVER edit a migration after it's been committed to main
# If a migration is wrong, write a new one that fixes it
```

- One migration per logical change. "Add user table" + "Add posts table" = two migrations.
- Migrations are forward-only. No `down.sql`. Rollback = new migration.
- Every migration has a comment at the top explaining **why** it exists.
- All migrations run inside a transaction (Drizzle does this by default).

### Queries

- Use Drizzle's typed query builder. Don't write raw SQL strings unless you have to (CTEs, window functions).
- Every table has `id` (TEXT, ULID), `createdAt`, `updatedAt` columns. ULIDs sort by creation time and are URL-safe.
- Money columns are `INTEGER` (cents). Never `REAL` for currency.
- Every query that takes user input is parameterized via Drizzle. No string interpolation.
- All multi-step writes go through a transaction. Read-modify-write without a transaction is a bug, not a code smell.

### Schema

```ts
// src/server/db/schema.ts
import { sqliteTable, text, integer } from 'drizzle-orm/sqlite-core';

export const users = sqliteTable('users', {
  id: text('id').primaryKey(),
  email: text('email').notNull().unique(),
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull(),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull(),
});
```

- Add `.notNull()` unless you have a specific reason to allow null.
- Foreign keys always explicit: `.references(() => otherTable.id)`.
- Indexes on every column used in `WHERE` or `ORDER BY`. Don't add "just in case" indexes.

---

## 4. Component patterns

### Server Components (default)

```tsx
// src/app/(app)/dashboard/page.tsx
import { getDashboardData } from '@/server/queries/dashboard';

export default async function DashboardPage() {
  const data = await getDashboardData();
  return <Dashboard data={data} />;
}
```

- Default export is the page. Named exports for utilities.
- No `useEffect` for data fetching. Fetch in the server component.
- Pass data down via props, not context (unless truly global).

### Client Components (rare, opt-in)

```tsx
'use client';
// Only when you need: useState, useEffect, event handlers, browser APIs
```

- Top of file, in a comment: why this needs to be a client component.
- Co-locate state. Lifting state up is fine; context is for theme/auth only.

### Forms

- Use `react-hook-form` + `zodResolver` for all forms.
- Submit handler calls a server action. No `/api/form` endpoint unless it's called from a non-React client.
- All field validation rules are in a Zod schema shared with the server action.

---

## 5. Auth

- Sessions stored in DB, NOT JWT. JWT-based sessions can't be revoked.
- `auth()` helper from `@/server/auth` is the only way to get the current user. Don't import from `next-auth` directly.
- Protected routes live under `(app)/` route group. Root layout checks session; redirects to `/login` if missing.
- Server actions that mutate must call `auth()` first. Returning `null` from `auth()` = unauthorized.

```ts
// src/server/actions/posts.ts
'use server';
import { auth } from '@/server/auth';

export async function createPost(input: CreatePostInput) {
  const session = await auth();
  if (!session) throw new Error('Unauthorized');
  // ...
}
```

- Never trust `session.user.id` from the client. Always re-fetch from the DB on the server.
- Password hashing: `argon2id`, 64 MB memory cost. Don't roll your own.

---

## 6. Environment variables

```ts
// src/lib/env.ts
import { z } from 'zod';

const schema = z.object({
  DATABASE_URL: z.string().url(),
  AUTH_SECRET: z.string().min(32),
  STRIPE_SECRET_KEY: z.string().startsWith('sk_').optional(),
});

export const env = schema.parse(process.env);
```

- Import `env` from `@/lib/env`, never access `process.env` directly.
- Server-only vars (`*_SECRET`, `*_KEY`) prefixed conventionally. Add to schema.
- Client-accessible vars must be prefixed `NEXT_PUBLIC_` AND added to schema with `.optional()` if used conditionally.
- No defaults for secrets. The build fails if they're missing.

---

## 7. What we don't do (and why)

| Anti-pattern | Why banned |
|---|---|
| `useEffect` for data fetching | Server Components do this faster with no waterfall |
| API routes for internal client calls | Server Actions are type-safe and don't roundtrip HTTP |
| `any` type | Strict TS catches bugs that `any` papers over |
| CSS-in-JS (styled-components, emotion) | Tailwind is faster, smaller, and we can SSR without FOUC |
| Prisma | Drizzle is 10x smaller and produces readable SQL |
| JWT sessions | Can't be revoked; DB sessions can |
| Editing migrations after merge | Rewriting history breaks prod rollback |
| Default exports for non-pages | Named exports give better refactor support |
| `console.log` in committed code | Use `pino` logger with levels; logs go to Datadog |
| Direct `process.env` access | Bypasses validation; one typo = silent bug |
| `fetch` in client components | Server Actions; see above |
| Storing money as floats | Cents in `INTEGER` columns; no rounding errors |

---

## 8. Dev commands

```bash
# Install
pnpm install

# Dev server (Turbopack)
pnpm dev

# Build
pnpm build

# Typecheck + lint + format check
pnpm check

# DB
pnpm db:generate      # generate migration from schema diff
pnpm db:migrate       # apply migrations to local DB
pnpm db:studio        # Drizzle Studio (http://localhost:4983)
pnpm db:seed          # seed dev data

# Tests
pnpm test             # Vitest, single run
pnpm test:watch       # Vitest watch mode
pnpm test:e2e         # Playwright

# Logs
pnpm logs             # tail local app logs
```

**Always run `pnpm check && pnpm test` before opening a PR.** CI runs the same.

---

## 9. Where to start (per module)

| Module | Read first | Then |
|---|---|---|
| Auth flow | `src/server/auth/config.ts` | `src/app/(app)/layout.tsx`, `src/server/auth/session.ts` |
| Database | `src/server/db/schema.ts` | `src/server/db/queries/users.ts` (example of pattern) |
| Server Actions | `src/server/actions/users.ts` | `src/components/features/users/UserForm.tsx` (calls it) |
| API routes | `src/app/api/webhooks/stripe/route.ts` | `src/server/services/billing.ts` |
| Components | `src/components/ui/Button.tsx` | `src/components/features/dashboard/StatsCard.tsx` (composed) |
| Styling | `tailwind.config.ts` | `src/styles/globals.css` |

---

## 10. Known pitfalls

1. **SQLite locks on long writes.** Wrap multi-row inserts in a transaction; 1000 individual inserts can hang the app for 5 seconds.
2. **Server Actions need `revalidatePath` after mutation.** Forgetting it = stale UI on next render.
3. **Auth.js v5 is in beta.** Pin the version; minor upgrades have shipped breaking changes.
4. **Next.js 15 async cookies/headers.** `cookies()` returns a Promise. `await cookies()` or you'll get cryptic type errors.
5. **Turbopack is fast but not feature-complete.** If you see weird HMR bugs, fall back to webpack: `next dev --turbo=false`.
6. **Drizzle's `mode: 'timestamp'` stores seconds, not ms.** Use `mode: 'timestamp_ms'` if you need sub-second precision.
7. **Biome doesn't lint `.sql` files.** Run migrations through `pnpm db:lint` before committing.
8. **Tailwind 3.4 dynamic class names don't work.** No `bg-${color}-500`; use the safelist or explicit class strings.

---

## 11. PR checklist

- [ ] Branch is from `main`, latest commit pulled
- [ ] `pnpm check` passes (typecheck + lint + format)
- [ ] `pnpm test` passes; new tests for new logic
- [ ] Schema changes have a migration checked in
- [ ] Server Actions have authorization check (`await auth()`)
- [ ] New env vars added to `src/lib/env.ts`
- [ ] No `console.log`, `any`, or commented-out code
- [ ] Description explains **why**, not **what**

---

*Last reviewed: 2026-06-24 — if a section is more than 90 days stale, please open a PR.*
