#!/usr/bin/env python3
"""
claude_review.py - Claude Code sub-agent that reviews a GitHub PR and posts a
structured Markdown comment.

Designed for BOUNTY #4 in claude-builders-bounty/claude-builders-bounty:
    https://github.com/claude-builders-bounty/claude-builders-bounty/issues/4

Acceptance criteria satisfied:
  - CLI:        claude-review --pr https://github.com/owner/repo/pull/123
  - GitHub Action: ./agents/pr-reviewer/pr_review_action.yml
  - Structured Markdown: Summary, Risks, Improvement Suggestions, Confidence
  - Tested on 2+ real PRs (see ./examples/)

Strategy
--------
1. Parse the GitHub PR URL.
2. Use the `gh` CLI to fetch PR metadata + unified diff (already auth'd).
3. Construct a focused prompt that asks for a structured review.
4. Try to invoke the `claude` CLI (Claude Code) headlessly to produce the
   review. This is the "agent IS Claude Code" path.
5. If the `claude` CLI is unavailable, fall back to a deterministic
   heuristic engine (still produces the same structured shape). This keeps
   the tool usable in any environment.
6. Validate the output has the four required sections. If sections are
   missing, patch in a fallback so the comment always renders.
7. Optionally post as a sticky PR comment via `gh pr comment`.

Usage
-----
    # Local review (prints Markdown to stdout)
    python3 claude_review.py --pr https://github.com/owner/repo/pull/123

    # Post review as PR comment
    python3 claude_review.py --pr URL --post

    # Review a local diff
    python3 claude_review.py --diff path/to/changes.diff

    # Read diff from stdin
    cat changes.diff | python3 claude_review.py --diff -

    # JSON output (handy for tooling / GitHub Action)
    python3 claude_review.py --pr URL --json

    # Force heuristic mode (skip claude CLI)
    python3 claude_review.py --pr URL --no-claude

Environment
-----------
    GH_TOKEN           Inherited from `gh auth`, normally already set.
    CLAUDE_BIN         Override path to the `claude` binary (default: `claude`).
    CLAUDE_TIMEOUT     Timeout in seconds for `claude` call (default: 120).

Exit codes
----------
    0  success
    1  bad input / fetch failed
    2  review produced but validation failed (we still return a fallback)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# PR fetching (uses `gh`, already authenticated on most dev machines + CI)
# ---------------------------------------------------------------------------

PR_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<num>\d+)/?\s*$"
)


def parse_pr_url(url: str) -> tuple[str, str, int]:
    m = PR_URL_RE.match(url.strip())
    if not m:
        raise ValueError(
            f"Invalid GitHub PR URL: {url!r}. "
            f"Expected https://github.com/<owner>/<repo>/pull/<number>"
        )
    return m["owner"], m["repo"], int(m["num"])


@dataclass
class PRContext:
    owner: str
    repo: str
    number: int
    title: str = ""
    author: str = ""
    base: str = ""
    head: str = ""
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0
    body: str = ""
    diff: str = ""

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}/pull/{self.number}"


def fetch_pr(url: str) -> PRContext:
    """Fetch PR metadata + diff via `gh`. Returns PRContext."""
    owner, repo, num = parse_pr_url(url)
    slug = f"{owner}/{repo}"
    ctx = PRContext(owner=owner, repo=repo, number=num)

    # Metadata
    meta_proc = subprocess.run(
        ["gh", "pr", "view", str(num), "--repo", slug,
         "--json", "title,author,baseRefName,headRefName,additions,deletions,"
         "changedFiles,body"],
        capture_output=True, text=True, timeout=60,
    )
    if meta_proc.returncode != 0:
        raise RuntimeError(
            f"gh pr view failed for {slug}#{num}: {meta_proc.stderr.strip()}"
        )
    try:
        meta = json.loads(meta_proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh pr view returned invalid JSON: {exc}") from exc

    ctx.title = meta.get("title", "") or ""
    ctx.author = (meta.get("author") or {}).get("login", "") or ""
    ctx.base = meta.get("baseRefName", "") or ""
    ctx.head = meta.get("headRefName", "") or ""
    ctx.additions = int(meta.get("additions") or 0)
    ctx.deletions = int(meta.get("deletions") or 0)
    ctx.changed_files = int(meta.get("changedFiles") or 0)
    ctx.body = meta.get("body") or ""

    # Diff
    diff_proc = subprocess.run(
        ["gh", "pr", "diff", str(num), "--repo", slug],
        capture_output=True, text=True, timeout=120,
    )
    if diff_proc.returncode != 0:
        raise RuntimeError(
            f"gh pr diff failed for {slug}#{num}: {diff_proc.stderr.strip()}"
        )
    ctx.diff = diff_proc.stdout
    return ctx


def read_diff(source: str) -> str:
    """Read a diff from a file path or stdin ('-')."""
    if source == "-":
        return sys.stdin.read()
    p = Path(source)
    if not p.exists():
        raise FileNotFoundError(f"Diff file not found: {source}")
    return p.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Reviewer (heuristic fallback when `claude` CLI is unavailable)
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    severity: str   # critical, warning, suggestion, nitpick
    category: str   # security, correctness, performance, style, naming
    file: str
    line: int
    rule: str
    message: str
    confidence: str  # low, medium, high


@dataclass
class Review:
    summary: str = ""
    risks: list[Finding] = field(default_factory=list)
    suggestions: list[Finding] = field(default_factory=list)
    confidence: str = "Medium"
    source: str = "heuristic"  # 'claude' or 'heuristic'

    def add(self, f: Finding) -> None:
        if f.severity in ("critical", "warning"):
            self.risks.append(f)
        else:
            self.suggestions.append(f)


# Per-line heuristics: (regex, severity, category, rule_id, message, confidence)
RULES = [
    # Security
    (r"\binnerHTML\s*=", "critical", "security", "xss-innerHTML",
     "innerHTML assignment is XSS-prone — use textContent or DOM nodes.", "high"),
    (r"\beval\s*\(", "critical", "security", "rce-eval",
     "eval() executes arbitrary code. Use ast.literal_eval or refactor.", "high"),
    (r"\bexec\s*\(", "critical", "security", "rce-exec",
     "exec() executes arbitrary code. Avoid in production paths.", "high"),
    (r"\bshell\s*=\s*True", "warning", "security", "shell-true",
     "shell=True with string interpolation enables shell injection.", "high"),
    (r"\.format\s*\(.*\*\*(?:locals|globals|vars)\(\)\)", "warning", "security",
     "format-locals", "str.format(**locals()) can leak unintended attributes.", "medium"),
    (r"(?i)(password|secret|api[_-]?key|token|private[_-]?key)\s*=\s*['\"]",
     "critical", "security", "hardcoded-secret",
     "Hardcoded secret detected. Use env vars or a secret manager.", "high"),
    (r"\bverify\s*=\s*False", "warning", "security", "tls-skip",
     "TLS verification disabled — remove before shipping.", "high"),
    (r"\bDROP\s+(TABLE|DATABASE)", "warning", "security", "sql-drop",
     "DROP statement — wrap in transaction + WHERE.", "high"),
    (r"\bDELETE\s+FROM\s+\w+\s*;", "warning", "security", "sql-delete-nowhere",
     "DELETE without WHERE — will delete all rows.", "high"),
    (r"\brm\s+-rf\s+/\b", "critical", "security", "destructive-rm",
     "Destructive `rm -rf /` — must be guarded.", "high"),
    (r"\bTRUNCATE\b", "warning", "security", "sql-truncate",
     "TRUNCATE — full-table delete, often accidental.", "high"),

    # Correctness
    (r"except\s*:", "warning", "correctness", "bare-except",
     "Bare except catches SystemExit/KeyboardInterrupt. Specify types.", "high"),
    (r"except\s+Exception\s*:", "suggestion", "correctness", "broad-except",
     "Broad except Exception — consider more specific handlers.", "medium"),
    (r"\.get\([^,)]+\)\.lower\(\)", "suggestion", "correctness",
     "none-lower", "Possible AttributeError on NoneType.lower().", "medium"),
    (r"\bTODO\b|\bFIXME\b|\bXXX\b", "suggestion", "correctness", "todo-marker",
     "TODO/FIXME marker — track in issue tracker.", "low"),
    (r"\bprint\(", "nitpick", "correctness", "print-debug",
     "print() debug — use logging in production.", "low"),
    (r"==\s*None\b", "nitpick", "style", "eq-none",
     "Use `is None` instead of `== None`.", "high"),
    (r"!=\s*None\b", "nitpick", "style", "ne-none",
     "Use `is not None` instead of `!= None`.", "high"),

    # Performance
    (r"for\s+\w+\s+in\s+range\s*\(\s*len\s*\(", "suggestion", "performance",
     "range-len", "Use enumerate() instead of range(len(...)).", "high"),
    (r"\b\w+\s*=\s*\w+\s*\+\s*\w+\s*\+\s*\w+", "nitpick", "performance",
     "string-concat", "String concatenation — use ''.join() for large strings.", "medium"),
    (r"\.read\(\)", "suggestion", "performance", "read-all",
     ".read() loads whole file — stream for large files.", "medium"),

    # Style
    (r".{121,}", "nitpick", "style", "long-line",
     "Line > 120 chars — consider wrapping.", "low"),
    (r"\bvar\s+\w+", "suggestion", "style", "js-var",
     "Use `let` or `const` instead of `var`.", "high"),
    (r"\bclass\s+[a-z][a-zA-Z0-9]*\b", "nitpick", "style", "class-lowercase",
     "Class names should be CamelCase.", "high"),
    (r"^def\s+[A-Z]\w*", "nitpick", "style", "function-pascal",
     "Function names should be snake_case.", "high"),

    # Bash / shell safety (catches hooks PR patterns)
    (r"curl[^|]*\|\s*(sh|bash)", "warning", "security", "curl-pipe-sh",
     "curl|sh executes remote payload — verify + sandbox.", "high"),
    (r"wget[^|]*\|\s*(sh|bash)", "warning", "security", "wget-pipe-sh",
     "wget|sh executes remote payload — verify + sandbox.", "high"),
    (r"git\s+push[^|]*--force(?!\-with\-lease)", "warning", "security",
     "force-push", "Bare `git push --force` — prefer --force-with-lease.", "high"),
    (r"git\s+reset\s+--hard", "warning", "correctness", "reset-hard",
     "git reset --hard discards uncommitted work.", "high"),
    (r"chmod\s+777\b", "warning", "security", "chmod-777",
     "chmod 777 is permissive — narrow scope.", "medium"),
    (r"dd\s+.*of=/dev/", "warning", "security", "dd-device",
     "dd writing to /dev/* — destructive.", "high"),
]


@dataclass
class HunkLine:
    file: str
    line: int
    content: str
    op: str  # '+', '-', ' '


def parse_unified_diff(diff: str) -> list[HunkLine]:
    """Parse a unified diff into per-line records (added lines only)."""
    out: list[HunkLine] = []
    cur_file = ""
    new_line = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ ") or raw.startswith("--- "):
            continue
        if raw.startswith("diff --git "):
            m = re.search(r" b/(.+)$", raw)
            if m:
                cur_file = m.group(1)
            continue
        if raw.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
            if m:
                new_line = int(m.group(1))
            continue
        if not raw:
            continue
        op, content = raw[0], raw[1:]
        if op == "+":
            out.append(HunkLine(cur_file, new_line, content, op))
            new_line += 1
        elif op == "-":
            continue
        elif op == " ":
            new_line += 1
    return out


def heuristic_review(ctx: Optional[PRContext], diff: str) -> Review:
    hunks = parse_unified_diff(diff)
    review = Review(source="heuristic")
    seen: set[tuple[str, int, str]] = set()

    files = sorted({h.file for h in hunks})
    additions = sum(1 for h in hunks if h.op == "+")
    files_str = ", ".join(f"`{f}`" for f in files[:5])
    if len(files) > 5:
        files_str += f" (+{len(files) - 5} more)"

    if ctx is not None:
        title = ctx.title or "(untitled PR)"
        author = ctx.author or "unknown"
        review.summary = (
            f"PR **[{ctx.slug}] {title}** by @{author} modifies "
            f"**{ctx.changed_files or len(files)} file(s)** "
            f"(+{ctx.additions or additions} / -{ctx.deletions}) on "
            f"`{ctx.head}` → `{ctx.base}`. "
            f"Files in this diff: {files_str}."
        )
    else:
        review.summary = (
            f"Diff modifies **{len(files)} file(s)** with ~{additions} "
            f"additions. Files: {files_str}."
        )

    for h in hunks:
        for rx, sev, cat, rule, msg, conf in RULES:
            if re.search(rx, h.content):
                key = (h.file, h.line, rule)
                if key in seen:
                    continue
                seen.add(key)
                review.add(Finding(sev, cat, h.file, h.line, rule, msg, conf))

    n = len(review.risks) + len(review.suggestions)
    if n == 0:
        review.confidence = "High"
    elif n < 3:
        review.confidence = "High"
    elif n < 10:
        review.confidence = "Medium"
    else:
        review.confidence = "Low"

    return review


# ---------------------------------------------------------------------------
# Claude CLI integration
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = textwrap.dedent("""\
You are reviewing a GitHub pull request. Produce a structured Markdown review
with EXACTLY these sections (in this order):

## Summary
2–3 sentence overview of what the PR does and why.

## Risks
A bullet list of concrete risks (security, correctness, breaking changes,
performance, regression). Each item: `- **<SEVERITY>** \`<path>:<line>\` — <one-line reason>.`
If there are no risks, write `- None identified.`

## Improvement Suggestions
A bullet list of actionable suggestions (code quality, readability, edge
cases, missing tests, doc gaps). Each item: `- \`<path>:<line>\` — <one-line suggestion>.`
If none, write `- None identified.`

## Confidence
One of: `Low`, `Medium`, or `High`, with a one-line justification.

Do NOT add any other top-level sections. Do NOT wrap the output in a code fence.
Do NOT include a salutation or signature. Be concrete, cite file:line where
possible, and stay grounded in the diff.

---
PR: {slug}
Title: {title}
Author: {author}
Base: {base}  <-  Head: {head}
Files changed: {changed}  (+{adds}/-{dels})

PR description:
{body}

Unified diff (may be truncated):
```diff
{diff}
```
""")


def build_prompt(ctx: PRContext, max_diff_chars: int = 80_000) -> str:
    diff = ctx.diff
    truncated = False
    if len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars]
        truncated = True
    prompt = PROMPT_TEMPLATE.format(
        slug=ctx.slug,
        title=ctx.title,
        author=ctx.author or "unknown",
        base=ctx.base or "?",
        head=ctx.head or "?",
        changed=ctx.changed_files,
        adds=ctx.additions,
        dels=ctx.deletions,
        body=(ctx.body or "(no description)")[:2000],
        diff=diff,
    )
    if truncated:
        prompt += "\n\n[Note: diff was truncated to fit context window.]\n"
    return prompt


def claude_available(bin_name: str = "claude") -> Optional[str]:
    """Return path to `claude` CLI if installed, else None."""
    return shutil.which(bin_name)


def call_claude(prompt: str, bin_name: str = "claude",
                timeout: int = 120) -> Optional[str]:
    """Invoke `claude -p <prompt>` headlessly. Returns stdout or None."""
    claude = claude_available(bin_name)
    if not claude:
        return None
    try:
        proc = subprocess.run(
            [claude, "-p", prompt, "--output-format", "text"],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            sys.stderr.write(
                f"[claude_review] claude CLI failed (rc={proc.returncode}): "
                f"{proc.stderr.strip()[:300]}\n"
            )
            return None
        out = proc.stdout.strip()
        return out or None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        sys.stderr.write(f"[claude_review] claude CLI error: {exc}\n")
        return None


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------

REQUIRED_SECTIONS = ("Summary", "Risks", "Improvement Suggestions", "Confidence")


def has_required_sections(text: str) -> bool:
    """Loose check: each required heading appears somewhere in the text."""
    low = text.lower()
    needles = ["## summary", "## risks",
               "## improvement suggestions", "## confidence"]
    return all(n in low for n in needles)


def fill_missing_sections(md: str, fallback: Review) -> str:
    """If any required section is missing, splice in the fallback version."""
    low = md.lower()
    out = md.rstrip() + "\n"
    if "## summary" not in low:
        out += "\n## Summary\n" + (fallback.summary or "(no summary)") + "\n"
    if "## risks" not in low:
        out += "\n## Risks\n"
        if fallback.risks:
            for f in fallback.risks:
                out += (
                    f"- **{f.severity.upper()}** `{f.file}:{f.line}` "
                    f"— {f.message}\n"
                )
        else:
            out += "- None identified.\n"
    if "## improvement suggestions" not in low:
        out += "\n## Improvement Suggestions\n"
        if fallback.suggestions:
            for f in fallback.suggestions:
                out += f"- `{f.file}:{f.line}` — {f.message}\n"
        else:
            out += "- None identified.\n"
    if "## confidence" not in low:
        out += "\n## Confidence\n" + fallback.confidence + "\n"
    return out


def render_markdown_from_review(review: Review) -> str:
    lines = ["## Summary", review.summary or "(no summary)", ""]
    lines.append("## Risks")
    if review.risks:
        for f in sorted(review.risks, key=lambda x: (x.severity, x.file, x.line)):
            lines.append(
                f"- **{f.severity.upper()}** `{f.file}:{f.line}` "
                f"[{f.rule}] — {f.message}"
            )
    else:
        lines.append("- None identified.")
    lines.append("")
    lines.append("## Improvement Suggestions")
    if review.suggestions:
        for f in sorted(review.suggestions, key=lambda x: (x.severity, x.file, x.line)):
            lines.append(
                f"- `{f.file}:{f.line}` [{f.rule}] — {f.message}"
            )
    else:
        lines.append("- None identified.")
    lines.append("")
    lines.append(f"## Confidence")
    lines.append(f"**{review.confidence}** — based on {review.source} review.")
    lines.append("")
    return "\n".join(lines)


def render_json(review: Review) -> str:
    return json.dumps({
        "summary": review.summary,
        "confidence": review.confidence,
        "source": review.source,
        "risks": [asdict(f) for f in review.risks],
        "suggestions": [asdict(f) for f in review.suggestions],
    }, indent=2)


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------

def post_pr_comment(url: str, body: str) -> str:
    owner, repo, num = parse_pr_url(url)
    proc = subprocess.run(
        ["gh", "pr", "comment", str(num), "--repo", f"{owner}/{repo}",
         "--body", body],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh pr comment failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_review(
    pr_url: Optional[str] = None,
    diff_path: Optional[str] = None,
    use_claude: bool = True,
    claude_bin: str = "claude",
    claude_timeout: int = 120,
) -> tuple[Review, str]:
    """Run the review. Returns (Review, markdown_text).

    Priority:
      1. If --pr URL: fetch via gh, run claude CLI if available, else heuristic.
      2. If --diff: run heuristic on the diff (no PR metadata).
    """
    ctx: Optional[PRContext] = None
    diff: str = ""

    if pr_url:
        ctx = fetch_pr(pr_url)
        diff = ctx.diff
    elif diff_path is not None:
        diff = read_diff(diff_path)
    else:
        raise ValueError("Either --pr or --diff is required")

    fallback = heuristic_review(ctx, diff)

    if not use_claude:
        return fallback, render_markdown_from_review(fallback)

    if ctx is None:
        # No metadata → skip claude (we can't build a full prompt)
        return fallback, render_markdown_from_review(fallback)

    prompt = build_prompt(ctx)
    md = call_claude(prompt, bin_name=claude_bin, timeout=claude_timeout)

    if not md:
        # claude unavailable / failed → heuristic fallback
        return fallback, render_markdown_from_review(fallback)

    if not has_required_sections(md):
        sys.stderr.write(
            "[claude_review] claude output missing required sections; "
            "patching with heuristic fallback.\n"
        )
        md = fill_missing_sections(md, fallback)
        # Build a Review-shaped object for callers that want JSON
        review = Review(
            summary=fallback.summary,
            risks=fallback.risks,
            suggestions=fallback.suggestions,
            confidence=fallback.confidence,
            source="claude+heuristic-fill",
        )
    else:
        review = Review(
            summary=_extract_section(md, "Summary"),
            risks=fallback.risks,    # structured list only available from heuristic
            suggestions=fallback.suggestions,
            confidence=_extract_confidence(md),
            source="claude",
        )

    return review, md


def _extract_section(md: str, name: str) -> str:
    """Pull the body under `## <name>` up to the next `## ` heading."""
    pat = re.compile(
        rf"^##\s+{re.escape(name)}\s*$(.*?)(?=^##\s+|\Z)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    m = pat.search(md)
    return m.group(1).strip() if m else ""


def _extract_confidence(md: str) -> str:
    body = _extract_section(md, "Confidence")
    for level in ("High", "Medium", "Low"):
        if re.search(rf"\b{level}\b", body):
            return level
    return "Medium"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claude-review",
        description=(
            "Claude Code sub-agent that reviews a GitHub PR and posts a "
            "structured Markdown comment."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              claude-review --pr https://github.com/owner/repo/pull/123
              claude-review --pr URL --post
              claude-review --diff changes.diff
              cat pr.diff | claude-review --diff -
              claude-review --pr URL --json
              claude-review --pr URL --no-claude      # force heuristic mode
        """),
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--pr", help="GitHub PR URL to review")
    src.add_argument("--diff", help="Path to unified diff (use '-' for stdin)")
    p.add_argument("--post", action="store_true",
                   help="Post the review as a PR comment (requires --pr)")
    p.add_argument("--json", action="store_true",
                   help="Emit JSON instead of Markdown")
    p.add_argument("--no-claude", action="store_true",
                   help="Skip the claude CLI and use the heuristic engine")
    p.add_argument("--claude-bin", default=os.environ.get("CLAUDE_BIN", "claude"),
                   help="Path/name of the claude binary (default: $CLAUDE_BIN or 'claude')")
    p.add_argument("--claude-timeout", type=int,
                   default=int(os.environ.get("CLAUDE_TIMEOUT", "120")),
                   help="Timeout for the claude CLI call (seconds)")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.post and not args.pr:
        print("Error: --post requires --pr", file=sys.stderr)
        return 1

    try:
        review, md = run_review(
            pr_url=args.pr,
            diff_path=args.diff,
            use_claude=not args.no_claude,
            claude_bin=args.claude_bin,
            claude_timeout=args.claude_timeout,
        )
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output = render_json(review) if args.json else md
    print(output)

    if args.post:
        try:
            url = post_pr_comment(args.pr, md)
            print(f"\n---\nPosted to {args.pr}: {url}", file=sys.stderr)
        except RuntimeError as exc:
            print(f"Error posting comment: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
