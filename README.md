# Claude Code Pre-Tool-Use Hook — Destructive Command Blocker

Blocks dangerous bash commands before Claude Code executes them.

## How it works

Claude Code calls this hook via `pre-tool-use` on every `Bash` tool call.
The hook reads `stdin` (JSON from Claude), checks the command against a
blocklist of dangerous patterns, and:

- **exit 0** → command allowed
- **exit 2** → command blocked, stderr message sent back to Claude

Blocked attempts are logged to `~/.claude/hooks/blocked.log`.

## Blocked patterns

| Category | Patterns |
|----------|----------|
| Filesystem | `rm -rf`, `chmod -R 777`, `mv ... /dev/null`, `dd` to disk |
| Database | `DROP TABLE/DATABASE`, `TRUNCATE`, `DELETE FROM` (no WHERE) |
| Git | `git push --force`, `git reset --hard`, `git clean -fd`, `git branch -D` |
| System | Fork bombs, `sudo rm -rf`, `curl | bash`, `netcat` listeners |

## Installation (2 commands)

```bash
# 1. Copy the hook
cp hooks/pre_tool_use.py ~/.claude/hooks/pre_tool_use.py
chmod +x ~/.claude/hooks/pre_tool_use.py

# 2. Merge settings into your Claude Code config
# Add the hooks section from settings.json to your ~/.claude/settings.json
# or project-level .claude/settings.json
```

## Log format

```
[2026-06-29T20:30:00Z] BLOCKED: Recursive forced deletion (rm -rf)
  command: rm -rf /home/user/project/node_modules
  project: /home/user/project
```

## Testing

```bash
# Should be BLOCKED (exit code 2):
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}' | python3 hooks/pre_tool_use.py; echo "exit: $?"

# Should be ALLOWED (exit code 0):
echo '{"tool_name":"Bash","tool_input":{"command":"ls -la"}}' | python3 hooks/pre_tool_use.py; echo "exit: $?"
```

---

# claude-review: PR Review Agent for Claude Code

A simple command‑line tool that generates a structured review comment for a GitHub pull request.

## Features

- Takes a PR URL or `owner/repo#<num>` as input.
- Uses `gh` CLI to fetch PR metadata and file changes.
- Provides a markdown comment with:
  - Summary of changes
  - Detected risks (e.g., modifications to sensitive files)
  - Improvement suggestions
  - Confidence level (Low/Medium/High)
- No external API keys required; works with any repository where you have `gh` access.

## Installation

```bash
# 1. Clone this repository already contains the script
chmod +x claude-review.py

# (Optional) Add to your PATH for easy use
sudo ln -s $(pwd)/claude-review.py /usr/local/bin/claude-review
```

## Usage

```bash
# By URL
claude-review --pr https://github.com/owner/repo/pull/123

# By owner/repo#number
claude-review --pr owner/repo#42
```

The tool prints a ready‑to‑paste Markdown comment to stdout. Example output:

```
## PR Review by claude-review

**Summary**
PR #42 "Add user login" by @alice modifies 3 file(s) with 124 additions and 12 deletions.

**Risks**
- Changes touch sensitive files: src/auth/login.py, .env.example

**Improvement Suggestions**
- Consider adding tests for new or modified logic.
- Ensure environment variables are documented.

**Confidence:** Medium

*This review was generated automatically by claude-review.*
```

## How it works

1. Queries the GitHub REST API via `gh api` to obtain:
   - PR title, author, URL
   - List of changed files with addition/deletion counts
2. Runs simple heuristics:
   - Flags changes to files containing words like `auth`, `password`, `secret`, `.env`, `config`, `key`, `token`.
   - Suggests breaking large PRs, adding tests, etc.
   - Computes a confidence level based on size and risk factors.

## Requirements

- [GitHub CLI (`gh`](https://cli.github.com/) installed and authenticated.
- Python 3.6+

## License

MIT