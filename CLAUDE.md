# CLAUDE.md - Claude Code Assistant Guidelines for Next.js + SQLite SaaS

## Project Overview

This document provides guidelines for using Claude Code assistant with a Next.js + SQLite SaaS project.

### Tech Stack
- **Frontend**: React 18, Next.js 14 (App Router), TypeScript, Tailwind CSS
- **Backend**: Node.js API routes (Next.js), SQLite with Prisma ORM
- **Authentication**: NextAuth.js (JWT strategy)
- **Payments**: Stripe Integration
- **Deployment**: Vercel (preview & production)

## Development Commands

```bash
# Install dependencies
npm install

# Development server
npm run dev

# Production build
npm run build

# Start production server
npm start

# Linting
npm run lint

# Tests
npm test

# Prisma DB operations
npx prisma generate          # Generate Prisma client
npx prisma migrate dev       # Apply migrations
npx prisma studio            # Open database GUI
```

## Code Style & Conventions

### File Organization
```
/app                 # Next.js app directory (App Router)
  /(dashboard)       # Protected routes
  /(auth)            # Public auth routes
  /api               # API routes
  /components        # Shared components
  /lib               # Utilities, Prisma client, etc.
  /public            # Static assets
  /styles            # Global styles
/hooks               # Claude Code hooks (if any)
/prisma              # Prisma schema & migrations
/scripts             # Scripts (seed, etc.)
/tests               # Test files
```

### Naming Conventions
- **Components**: PascalCase (e.g., `UserProfile.tsx`)
- **Functions & variables**: camelCase
- **Constants**: UPPER_SNAKE_CASE
- **Files**: kebab-case for new files, but follow existing convention
- **Pages**: Use App Router folder structure (`app/page.tsx`)

### TypeScript Rules
- Prefer interfaces for public API shapes, types for complex unions/intersections
- Avoid `any`; use `unknown` when type is uncertain and then narrow
- Enable `strict` in tsconfig.json

### Commit Messages
Use conventional commits:
```
<type>(<scope>): <subject>
```
Types: feat, fix, docs, style, refactor, perf, test, chore, ci

## Claude-Specific Instructions

### When asked to generate code:
1. Follow existing file patterns in the project
2. Import from `@/` alias for absolute paths (configured in jsconfig.json/tsconfig.json)
3. Use Tailwind CSS classes for styling (utility-first)
4. For API routes, use async handlers with proper error handling (try/catch)
5. When modifying Prisma schema, run `npx prisma generate` after changes

### When asked to debug:
1. Check console errors (both client and server)
2. Verify environment variables (.env.local)
3. Look at recent migrations if DB-related
4. Test API endpoints with curl or Postman

### When asked to add features:
1. Ensure component reusability and props typing
2. Add unit tests for new utility functions
3. Update README if needed
4. Consider accessibility (a11y) from the start

## Troubleshooting

### Common Issues
- **Module not found**: Check tsconfig paths, run `npm install`
- **DB connection errors**: Verify `DATABASE_URL` in .env, run `npx prisma migrate dev`
- **Build fails**: Look for lint errors first (`npm run lint`)

## Contributing
1. Fork the repo
2. Create feature branch (`git checkout -b feature/amazing`)
3. Make changes, commit with conventional commits
4. Push and open Pull Request
5. Ensure CI passes

## License
MIT