## Summary
PR **[moorcheh-ai/memanto#774] fix(security): close stored prompt injection + URL command injection (bounty findings #1 + #4)** by @Yzgaming005 modifies **2 file(s)** (+253 / -43) on `fix/security-hardening-and-bug-report` → `main`. Files in this diff: `memanto/app/services/memory_write_service.py`, `memanto/cli/commands/core.py`.

## Risks
- None identified.

## Improvement Suggestions
- `memanto/cli/commands/core.py:1014` [print-debug] — print() debug — use logging in production.

## Confidence
**High** — based on heuristic review.

