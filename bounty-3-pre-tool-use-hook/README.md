# Bounty #3: Pre-Tool-Use Hook — Block Destructive Bash Commands

**Reward:** $100  
**Issue:** [#3](https://github.com/claude-builders-bounty/claude-builders-bounty/issues/3)

A [Claude Code](https://docs.anthropic.com/claude-code) `pre-tool-use` hook that intercepts
and blocks dangerous bash commands before they can execute.

## What it blocks

| Pattern | Example | Why |
|---------|---------|-----|
| `rm -rf` | `rm -rf /project` | Recursive force remove — permanent data loss |
| `DROP TABLE` | `DROP TABLE users;` | Destroys entire database tables |
| `git push --force` | `git push origin main --force` | Rewrites remote history, can destroy teammates' work |
| `TRUNCATE` | `TRUNCATE users;` | Deletes all rows in a table without recovery |
| `DELETE FROM` (no `WHERE`) | `DELETE FROM users;` | Removes every row — `DELETE FROM users WHERE id=5` is fine |

## Installation

In 2 commands:

```bash
mkdir -p ~/.claude/hooks
cp bounty-3-pre-tool-use-hook/hooks/pre-tool-use ~/.claude/hooks/pre-tool-use
```

Make sure it's executable:

```bash
chmod +x ~/.claude/hooks/pre-tool-use
```

> **Note:** This hook requires Python 3.6+. Most systems have it pre-installed.

## How it works

1. Claude Code runs the hook **before every tool call**
2. The hook inspects `CLAUDE_TOOL_NAME` and `CLAUDE_TOOL_INPUT` environment variables
3. If the tool is a bash/terminal tool, the command is checked against block rules
4. **Safe commands** → exit 0 (allowed)
5. **Dangerous commands** → logged to `~/.claude/hooks/blocked.log`, clear message printed, exit 1 (blocked)

## Logging

Every blocked attempt is logged to `~/.claude/hooks/blocked.log` with:

```
[2026-06-23T12:34:56Z] BLOCKED: rm -rf
  Command: rm -rf /project/data
  Project: /home/user/my-project
  Reason:  BLOCKED: 'rm -rf' (recursive force remove) is destructive...
------------------------------------------------------------------------
```

## Testing

Run the hook manually to verify:

```bash
# Should block
CLAUDE_TOOL_NAME=Bash CLAUDE_TOOL_INPUT='{"command":"rm -rf /tmp"}' python3 hooks/pre-tool-use
echo $?   # → 1

# Should allow
CLAUDE_TOOL_NAME=Bash CLAUDE_TOOL_INPUT='{"command":"ls -la"}' python3 hooks/pre-tool-use
echo $?   # → 0
```

## Files

```
bounty-3-pre-tool-use-hook/
├── README.md
└── hooks/
    └── pre-tool-use    # The hook script (executable)
```

## License

MIT
