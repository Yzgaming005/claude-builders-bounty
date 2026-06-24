# claude-review

Claude Code PR-reviewer sub-agent for issue [#4](https://github.com/claude-builders-bounty/claude-builders-bounty/issues/4) of [claude-builders-bounty](https://github.com/claude-builders-bounty/claude-builders-bounty).

A small Python CLI + GitHub Action that fetches a Pull Request via `gh`, sends the diff to a free LLM on OpenRouter, and posts a structured Markdown review comment.

## What it produces

Every run produces (or posts) a Markdown comment with these **four required sections**:

1. **📝 Summary of changes** — 2-3 sentences describing what the PR does and why.
2. **⚠️ Identified risks** — bulleted list of bugs, security, performance, regression concerns.
3. **💡 Improvement suggestions** — bulleted list of concrete fixes, refactors, tests, docs.
4. **Confidence** — `Low` / `Medium` / `High` with a one-line justification.

Plus: file list, +/- stats, the model used, and a collapsible raw-response block for transparency.

See `sample_outputs/` for live examples against real PRs.

## Quick start

```bash
# 1. Install the only external dependency: the GitHub CLI (https://cli.github.com/)
gh auth login

# 2. Export a free OpenRouter API key (https://openrouter.ai/keys)
export OPENROUTER_API_KEY=sk-or-v1-...

# 3. Run against any PR — defaults to dry-run (prints to stdout)
python agents/pr-reviewer/claude_review.py \
  --pr https://github.com/owner/repo/pull/123

# 4. Add --post to actually comment on the PR
python agents/pr-reviewer/claude_review.py \
  --pr https://github.com/owner/repo/pull/123 \
  --post

# 5. Or write the markdown to a file
python agents/pr-reviewer/claude_review.py \
  --pr https://github.com/owner/repo/pull/123 \
  --output review.md
```

### CLI options

```
--pr URL          (required) GitHub PR URL
--post            Post the review as a PR comment via `gh pr comment`
--dry-run         Don't post (default — same as omitting --post)
--output PATH     Also write the markdown to this file
--max-diff-chars  Cap the diff sent to the model (default 40000)
--model           Override the OpenRouter model (default: priority chain)
```

### Models

Defaults to a free-model priority chain on OpenRouter (first one that returns 200 wins):

| # | Model | Notes |
|---|---|---|
| 1 | `openai/gpt-oss-120b:free` | strong default |
| 2 | `openai/gpt-oss-20b:free`  | fast fallback |
| 3 | `meta-llama/llama-3.3-70b-instruct:free` | sometimes rate-limited upstream |
| 4 | `qwen/qwen3-coder:free`    | code-specialised |
| 5 | `google/gemma-4-31b-it:free` | last-resort general |

Override with `--model <slug>` or set `OPENROUTER_API_KEY` to a paid key for higher rate limits.

## GitHub Action

Drop `claude_review_action.yml` into `.github/workflows/`. The workflow:

- Triggers on PR open / reopen / synchronize / ready_for_review (and `workflow_dispatch` for manual runs).
- Sets up Python 3.11.
- Runs `python agents/pr-reviewer/claude_review.py --pr <URL> --post`.
- Requires `OPENROUTER_API_KEY` as a repo secret.

```yaml
# .github/workflows/claude-review.yml — copy/paste minimal version
name: Claude PR Reviewer
on:
  pull_request:
    types: [opened, reopened, synchronize, ready_for_review]
permissions:
  contents: read
  pull-requests: write
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: gh --version
      - env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          python agents/pr-reviewer/claude_review.py \
            --pr "${{ github.event.pull_request.html_url }}" \
            --post \
            --output review.md
```

## How it works

```
+-------------+    gh api / gh pr diff    +-----------+
|   CLI / GH  | -------------------------> | GitHub    |
|   Action    | <------------------------- | (PR data) |
+-------------+                           +-----------+
        |
        | diff + metadata
        v
+-------------+    POST /chat/completions   +---------------+
|  Reviewer   | ---------------------------> | OpenRouter    |
|  (Python)   | <--------------------------- | (free LLM)    |
+-------------+                              +---------------+
        |
        | parsed Markdown
        v
+-------------+    gh pr comment --body-file -
|  stdout /   | ---------------------------> GitHub PR comment
|  PR comment |
+-------------+
```

## Requirements

- Python 3.11+
- [`gh`](https://cli.github.com/) CLI installed and authenticated (`gh auth login`)
- An OpenRouter API key (free tier is fine) → https://openrouter.ai/keys
- No `pip install` required — the script uses only the standard library plus `urllib`.

## Tests

```bash
python -m unittest discover agents/pr-reviewer/tests -v
```

The smoke tests cover URL parsing, section splitting, confidence normalization, and CLI help — they don't make network calls so they're safe in CI.

## Files

```
agents/pr-reviewer/
├── claude_review.py             # main CLI entrypoint
├── claude_review_action.yml     # GitHub Action workflow
├── prompts.py                   # LLM prompt templates
├── README.md                    # this file
├── requirements.txt             # (empty — stdlib only)
├── tests/
│   └── test_smoke.py            # unit tests
└── sample_outputs/
    ├── pr-3015-review.md        # live review of claude-builders-bounty#3015
    └── pr-774-review.md         # live review of moorcheh-ai/memanto#774
```

## License

MIT.