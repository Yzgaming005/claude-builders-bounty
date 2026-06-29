#!/usr/bin/env python3
"""
Pre-tool-use hook for Claude Code.
Blocks destructive bash commands before execution.

Hook format: reads JSON from stdin, writes JSON to stdout.
Claude Code passes: {"tool_name": "Bash", "tool_input": {"command": "..."}, ...}
Hook exits with code 2 to block + send stderr back to Claude.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

LOG_FILE = Path.home() / ".claude" / "hooks" / "blocked.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# Patterns that require blocking. Each entry: (regex, reason)
DANGEROUS_PATTERNS = [
    # Filesystem destruction
    (r"\brm\s+(-[rfRF]+\s+)+(/|\.{2}/|~|\$)",
     "Recursive forced deletion of a sensitive path"),
    (r"\brm\s+-rf\s+",
     "Recursive forced deletion (rm -rf)"),
    (r"\bchmod\s+-R\s+777\b",
     "Recursive 777 chmod — world-writable everywhere"),
    (r"\bmv\s+.*\s+/dev/null\b",
     "Moving files to /destruction"),
    (r"\bdd\s+if=.*\bof=/dev/(sda|vda|xvda|nvme)\b",
     "Direct disk overwrite with dd"),

    # Database destruction
    (r"\bDROP\s+(TABLE|DATABASE)\b",
     "DROP TABLE/DATABASE detected"),
    (r"\bTRUNCATE\s+(TABLE\s+)?\w+\s*;?\s*$",
     "TRUNCATE TABLE detected"),
    (r"\bDELETE\s+FROM\s+\w+\s*;?\s*$",
     "DELETE FROM without WHERE clause"),

    # Git destruction
    (r"\bgit\s+push\s+(--force|-f)\b",
     "Force push detected"),
    (r"\bgit\s+push\s+--force\s+--thin\b",
     "Force push with thin pack"),
    (r"\bgit\s+checkout\s+--\s+(\.|\*)",
     "Discard all local changes"),
    (r"\bgit\s+reset\s+--hard\b",
     "Hard reset detected"),
    (r"\bgit\s+clean\s+-fd\b",
     "Force clean untracked files/dirs"),
    (r"\bgit\s+branch\s+-D\b",
     "Force-delete branch"),

    # Fork bombs & resource exhaustion
    (r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;:\s*$",
     "Fork bomb detected"),
    (r"\bwhile\s+true\b.*\bdo\b",
     "Infinite while loop"),

    # Privilege escalation
    (r"\bsudo\s+rm\s+-rf\b",
     "sudo rm -rf detected"),
    (r"\bsudo\s+chmod\s+-R\b",
     "sudo chmod -R detected"),
    (r"\bsudo\s+chown\s+-R\b",
     "sudo chown -R detected"),

    # Network attacks / data exfil
    (r"\bcurl\s+.*\|\s*(bash|sh|zsh)\b",
     "Piping curl to shell — potential code execution"),
    (r"\bwget\s+.*\|\s*(bash|sh|zsh)\b",
     "Piping wget to shell — potential code execution"),
    (r"\bnc\s+(-[a-z]*\s+)*-[lv]\b",
     "Netcat listener/connection detected"),
    (r"\bscp\s+.*@(root|admin)\b",
     "SCP to privileged remote user"),
]


def log_blocked(command: str, reason: str) -> None:
    """Append a blocked-attempt entry to the log file."""
    timestamp = datetime.utcnow().isoformat() + "Z"
    project = str(Path.cwd())
    entry = f"[{timestamp}] BLOCKED: {reason}\n  command: {command}\n  project: {project}\n"
    try:
        with LOG_FILE.open("a") as f:
            f.write(entry)
    except OSError:
        pass  # Never crash the hook because of a logging failure


def is_dangerous(command: str) -> tuple[bool, str]:
    """Return (blocked, reason) for a given command string."""
    # Strip leading/trailing whitespace
    cmd = command.strip()
    if not cmd:
        return False, ""

    for pattern, reason in DANGEROUS_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return True, reason

    return False, ""


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # Malformed input — allow through rather than break the session
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    # Only inspect Bash tool calls
    if tool_name != "Bash":
        sys.exit(0)

    command = tool_input.get("command", "")
    if not command:
        sys.exit(0)

    blocked, reason = is_dangerous(command)
    if not blocked:
        sys.exit(0)

    # Log the attempt
    log_blocked(command, reason)

    # Exit code 2 = block the tool use, stderr goes back to Claude
    message = (
        f"🚫 BLOCKED by pre_tool_use hook\n"
        f"Reason: {reason}\n"
        f"Claude, this command was intercepted because it matches a dangerous pattern.\n"
        f"Please choose a safer alternative or explain why this is necessary."
    )
    print(message, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
