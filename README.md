# PR Review Agent

A Claude Code agent that takes a GitHub PR diff URL, analyzes it, and returns a structured Markdown review comment.

## Usage

```
claude-review --pr https://github.com/owner/repo/pull/123
```

Or as a GitHub Action workflow.

## Output Format

- Summary of changes (2-3 sentences)
- Identified risks (list)
- Improvement suggestions (list)
- Confidence score: Low / Medium / High
