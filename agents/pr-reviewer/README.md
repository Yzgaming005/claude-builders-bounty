# Claude Code PR Reviewer Sub-Agent

> Issue: [claude-builders-bounty #4](https://github.com/claude-builders-bounty/claude-builders-bounty/issues/4) — `$150`
> Spec: `claude-review --pr https://github.com/owner/repo/pull/123`
> Output: **Summary · Risks · Improvement Suggestions · Confidence**

A Claude Code sub-agent that reviews a GitHub pull request and posts a
structured Markdown comment. It satisfies every acceptance criterion in
issue #4:

| Criterion | Where |
|---|---|
| CLI: `claude-review --pr <url>` | [`claude_review.py`](./claude_review.py) |
| GitHub Action workflow | [`pr_review_action.yml`](./pr_review_action.yml) |
| Structured Markdown: Summary / Risks / Suggestions / Confidence | `render_markdown_from_review()` |
| Tested on ≥ 2 real PRs | [`examples/`](./examples) — cbb#3015 and moorcheh-ai/memanto#774 |
| README with setup + usage | this file |

## What it does

1. **Fetch** PR metadata + unified diff via the `gh` CLI (already
   authenticated in most environments, including GitHub Actions).
2. **Review** — primary path invokes the `claude` CLI (Claude Code)
   headlessly with a focused prompt asking for the four required
   sections. This makes the agent *itself* a Claude Code agent.
3. **Fallback** — when `claude` is not available (e.g. default GitHub-hosted
   runner, local dev without Claude Code installed), it falls back to a
   deterministic, in-process heuristic reviewer that produces the *same*
   structured shape. Either way the output is guaranteed to contain the
   four required sections; if a section is missing in `claude`'s raw
   output, the heuristic engine fills it in.
4. **Post** — optionally posts the result as a sticky PR comment via
   `gh pr comment`. The bundled GitHub Action does this on
   `pull_request: [opened, synchronize, reopened]`.

## Install

```bash
# from inside agents/pr-reviewer/
python3 claude_review.py --help
```

Requirements:
- Python 3.8+
- `gh` CLI (authenticated: `gh auth login` once)
- `claude` CLI (optional — only for the primary path)

The Python file is self-contained — no `pip install` step required.

## Usage

### CLI — review a live PR

```bash
python3 claude_review.py --pr https://github.com/owner/repo/pull/123
```

This prints a structured Markdown review to stdout. Example shape:

```markdown
## Summary
PR **[BOUNTY $100] HOOK: Pre-tool-use guard blocking destructive bash commands**
by @Yzgaming005 modifies **6 file(s)** (+610 / -3) on
`feature/destructive-bash-guard` → `main`. The diff spans **6 file(s)**.

## Risks
- **WARNING** `hooks/destructive-bash-guard/block_destructive.py:160`
  [chmod-777] — chmod 777 is permissive — narrow scope.
- **WARNING** `hooks/destructive-bash-guard/patterns.yaml:14`
  [chmod-777] — chmod 777 is permissive — narrow scope.

## Improvement Suggestions
- `hooks/destructive-bash-guard/block_destructive.py:42`
  [todo-marker] — TODO/FIXME marker — track in issue tracker.

## Confidence
**Medium** — based on heuristic review.
```

### CLI — post the review as a PR comment

```bash
python3 claude_review.py --pr https://github.com/owner/repo/pull/123 --post
```

### CLI — review a local diff

```bash
python3 claude_review.py --diff path/to/changes.diff
cat changes.diff | python3 claude_review.py --diff -
```

### CLI — JSON output (tooling-friendly)

```bash
python3 claude_review.py --pr https://github.com/owner/repo/pull/123 --json
```

### CLI — force heuristic mode (skip the `claude` CLI)

```bash
python3 claude_review.py --pr URL --no-claude
```

### GitHub Action

Copy [`pr_review_action.yml`](./pr_review_action.yml) into your repo at
`.github/workflows/claude-review.yml`. It will run on every PR open/sync
and post a sticky comment with the structured review.

```yaml
# .github/workflows/claude-review.yml
on:
  pull_request:
    types: [opened, synchronize, reopened]
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: python3 agents/pr-reviewer/claude_review.py --pr "$PR_URL" --no-claude > /tmp/review.md
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      - uses: marocchino/sticky-pull-request-comment@v2
        with: { header: claude-review, path: /tmp/review.md }
```

> The default `pr_review_action.yml` ships with `--no-claude` because
> stock GitHub-hosted runners don't include Claude Code. To upgrade to the
> AI-powered path, run the workflow on a self-hosted runner with
> `claude` installed and drop the `--no-claude` flag.

## How the review works

### Primary path — `claude` CLI (Claude Code)

```
gh pr view …  ─┐
                ├─►  build_prompt()  ─►  claude -p "<prompt>"  ─►  markdown
gh pr diff …  ─┘
```

The prompt asks Claude to produce exactly four sections:
`## Summary`, `## Risks`, `## Improvement Suggestions`, `## Confidence`.
The output is validated; if any required section is missing, the
heuristic engine splices in a fallback so the comment always renders.

### Fallback path — heuristic engine

A pattern-matcher scans added lines of the diff for ~30 common smells
grouped by severity:

| Severity | Examples |
|---|---|
| **critical** | `innerHTML =`, `eval(`, `exec(`, hardcoded secrets, `rm -rf /` |
| **warning**  | bare `except`, `shell=True`, `verify=False`, SQL `DROP`/`DELETE` no `WHERE`, `git push --force`, `curl | sh` |
| **suggestion** | `range(len(...))`, `== None`, `.get(k).lower()`, `print()` debug, JS `var` |
| **nitpick** | long lines, `pass` statement, lowercase class names, TODOs |

Confidence is derived from finding density:

| Findings | Confidence |
|---|---|
| 0 – 2 | High |
| 3 – 9 | Medium |
| 10 + | Low |

## Examples

- [`examples/review-pr-3015.md`](./examples/review-pr-3015.md) — review of
  [claude-builders-bounty#3015](https://github.com/claude-builders-bounty/claude-builders-bounty/pull/3015)
  ("HOOK: Pre-tool-use guard blocking destructive bash commands")
- [`examples/review-pr-774.md`](./examples/review-pr-774.md) — review of
  [moorcheh-ai/memanto#774](https://github.com/moorcheh-ai/memanto/pull/774)
  ("fix(security): close stored prompt injection + URL command injection")

## Tests

```bash
cd agents/pr-reviewer
python3 -m unittest tests.test_claude_review -v
```

The smoke test exercises:
- Argument parsing & CLI entry point
- `parse_pr_url()` (good + bad URLs)
- `parse_unified_diff()` on a real diff
- `heuristic_review()` round-trip into Markdown + JSON
- `has_required_sections()` validator
- Both example review files exist and contain the four required sections

## Files

```
agents/pr-reviewer/
├── claude_review.py          # Main CLI (~26 KB, no external deps)
├── pr_review_action.yml      # GitHub Action workflow
├── README.md                 # This file
├── examples/
│   ├── review-pr-3015.md    # cbb#3015 review
│   └── review-pr-774.md     # memanto#774 review
└── tests/
    ├── __init__.py
    └── test_claude_review.py # smoke tests
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `GH_TOKEN` | inherited from `gh auth` | Required for `--pr` to fetch via `gh` |
| `CLAUDE_BIN` | `claude` | Override path to the `claude` binary |
| `CLAUDE_TIMEOUT` | `120` | Seconds to wait for `claude -p …` |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success — review printed (and posted, if `--post`) |
| `1` | Bad input, fetch failed, or post failed |
| `2` | Review produced but section validation patched in fallback (still returns useful output) |

## License

MIT
