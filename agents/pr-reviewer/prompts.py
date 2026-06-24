"""
Prompt templates for the Claude Code PR-reviewer sub-agent.

Keeping them here (instead of inline in claude_review.py) makes them easy to
iterate on, version, and unit-test without touching the CLI plumbing.
"""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are a senior staff software engineer performing a thorough, fair, and concise
GitHub pull-request review. You prioritize correctness, security, performance,
test coverage, and readability.

Rules:
- Be specific. Cite file paths and (when possible) line numbers.
- Be concise. No filler, no platitudes, no "Great work!" openers.
- Use valid Markdown only. Do not write prose outside the requested sections.
- If the diff is large or unfamiliar, say so — confidence goes Low.
- If the diff is small and clearly correct, confidence goes High.
- Never invent code that isn't in the diff. Only comment on what you can see.
"""

# The user prompt template. {diff}, {title}, {author}, {base}, {head}, etc.
# are substituted at call time.
USER_PROMPT_TEMPLATE = """\
You are reviewing the following GitHub Pull Request.

PR: {short_ref}
Title: {title}
Author: @{author}
Base branch: {base}
Head branch: {head}
Files changed: {changed_files} (+{additions} / -{deletions})

Description:
---
{body}
---

Diff (unified):
```diff
{diff}
```

Write a structured review using EXACTLY these four sections, in this order.
Use Markdown headings (## ...) so a parser can extract each section.
Every section MUST be present and clearly labelled.

## Summary of changes
(2-3 sentences describing what this PR does and why.)

## Identified risks
(Bulleted list. Each bullet starts with "- ". Cover bugs, security, performance,
regressions, data-loss, and breaking changes. If there are none, write
"- No significant risks identified.")

## Improvement suggestions
(Bulleted list. Each bullet starts with "- ". Concrete fixes, refactors, test
additions, or documentation. If there are none, write "- No additional
suggestions — the change looks complete.")

## Confidence
(Exactly one of: **Low**, **Medium**, or **High**, with a one-line
justification on the next line.)

Be specific. Avoid filler.
"""


def build_user_prompt(pr) -> str:
    """Render the user prompt template against a PRData instance."""
    return USER_PROMPT_TEMPLATE.format(
        short_ref=pr.short_ref,
        title=pr.title,
        author=pr.author,
        base=pr.base_ref,
        head=pr.head_ref,
        changed_files=pr.changed_files,
        additions=pr.additions,
        deletions=pr.deletions,
        body=(pr.body or "(empty)")[:2000],
        diff=pr.diff,
    )