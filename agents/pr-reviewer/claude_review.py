#!/usr/bin/env python3
"""
Claude Code PR-Reviewer sub-agent (issue #4 of claude-builders-bounty).

CLI usage:
    python claude_review.py --pr https://github.com/owner/repo/pull/123 [--post] [--dry-run]

What it does:
    1. Fetches PR metadata + diff via the GitHub CLI (`gh api` / `gh pr diff`).
    2. Sends the diff to a free LLM on OpenRouter (Llama 3.3 70B, with fallbacks).
    3. Parses the model output into a structured Markdown review:
         - Summary of changes (2-3 sentences)
         - Identified risks (bulleted list)
         - Improvement suggestions (bulleted list)
         - Confidence score: Low / Medium / High
    4. Prints to stdout, and (optionally) posts as a PR comment via `gh pr comment`.

Environment:
    OPENROUTER_API_KEY  (required to call the LLM)
    GH_TOKEN / gh auth  (required to fetch PR data and post comments)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_MAX_DIFF_CHARS = 40_000  # cap so we stay well inside the context window

# Free OpenRouter models in priority order. The first one that returns 200 wins.
MODEL_CHAIN = [
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-coder:free",
    "google/gemma-4-31b-it:free",
]

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PRData:
    """Raw data fetched from the GitHub PR."""

    url: str
    owner: str
    repo: str
    number: int
    title: str = ""
    author: str = ""
    base_ref: str = ""
    head_ref: str = ""
    body: str = ""
    state: str = ""
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0
    files: list[dict] = field(default_factory=list)
    diff: str = ""

    @property
    def short_ref(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"


# ---------------------------------------------------------------------------
# GitHub helpers — wrapped in a thin layer around `gh`
# ---------------------------------------------------------------------------


def parse_pr_url(url: str) -> tuple[str, str, int]:
    """Extract owner, repo, and PR number from a GitHub PR URL."""
    pattern = re.compile(
        r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<num>\d+)/?$"
    )
    m = pattern.match(url.strip())
    if not m:
        raise ValueError(
            f"Invalid PR URL: {url!r}. Expected "
            f"'https://github.com/<owner>/<repo>/pull/<number>'."
        )
    return m["owner"], m["repo"], int(m["num"])


def _run_gh(args: list[str], *, timeout: int = 60) -> str:
    """Run a `gh` command and return stdout. Raises on non-zero exit."""
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "gh CLI not found on PATH. Install it from https://cli.github.com/."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise RuntimeError(
            f"`gh {' '.join(args)}` failed (exit {exc.returncode}): {stderr}"
        ) from exc
    return result.stdout


def fetch_pr(url: str, max_diff_chars: int = DEFAULT_MAX_DIFF_CHARS) -> PRData:
    """Fetch PR metadata + diff + file list using `gh`."""
    owner, repo, number = parse_pr_url(url)
    data = PRData(url=url, owner=owner, repo=repo, number=number)

    # Metadata via `gh pr view --json`
    meta_json = _run_gh([
        "pr", "view", str(number),
        "--repo", f"{owner}/{repo}",
        "--json",
        "title,author,state,body,baseRefName,headRefName,additions,deletions,changedFiles,files",
    ])
    meta = json.loads(meta_json)

    data.title = meta.get("title", "")
    data.author = (meta.get("author") or {}).get("login", "")
    data.state = meta.get("state", "")
    data.body = meta.get("body") or ""
    data.base_ref = meta.get("baseRefName", "")
    data.head_ref = meta.get("headRefName", "")
    data.additions = int(meta.get("additions") or 0)
    data.deletions = int(meta.get("deletions") or 0)
    data.changed_files = int(meta.get("changedFiles") or 0)
    files = meta.get("files") or []
    data.files = [
        {
            "path": f.get("path", ""),
            "additions": int(f.get("additions") or 0),
            "deletions": int(f.get("deletions") or 0),
            "changeType": f.get("changeType", ""),
        }
        for f in files
    ]

    # Diff via `gh pr diff`
    diff = _run_gh(["pr", "diff", str(number), "--repo", f"{owner}/{repo}"])
    if len(diff) > max_diff_chars:
        truncated = diff[:max_diff_chars]
        truncated += (
            f"\n\n... [diff truncated from {len(diff):,} to {max_diff_chars:,} chars] ...\n"
        )
        data.diff = truncated
    else:
        data.diff = diff

    return data


# ---------------------------------------------------------------------------
# OpenRouter / LLM call
# ---------------------------------------------------------------------------


def call_openrouter(prompt: str, *, api_key: str, max_tokens: int = 1400) -> tuple[str, str]:
    """Call OpenRouter with the first working model from MODEL_CHAIN.

    Returns (model_used, content_text).
    """
    import urllib.error
    import urllib.request

    last_err: Optional[str] = None
    for model in MODEL_CHAIN:
        body = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a senior staff engineer performing a thorough, fair, and concise pull request review. You write valid Markdown only — no prose outside the requested sections."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }).encode("utf-8")

        req = urllib.request.Request(
            OPENROUTER_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/claude-builders-bounty/claude-builders-bounty",
                "X-Title": "claude-review PR reviewer",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            return model, content
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            try:
                err = json.loads(err_body).get("error", {}).get("message", err_body)
            except Exception:  # noqa: BLE001
                err = err_body
            last_err = f"{model}: HTTP {exc.code} — {err[:200]}"
            # 4xx other than 429: skip immediately
            if exc.code == 429 or exc.code >= 500:
                # retryable, try next model after a short backoff
                time.sleep(1.0)
                continue
            else:
                continue
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_err = f"{model}: {exc}"
            time.sleep(0.5)
            continue

    raise RuntimeError(
        "All OpenRouter models failed. Last error: " + (last_err or "unknown")
    )


# ---------------------------------------------------------------------------
# Response parsing & formatting
# ---------------------------------------------------------------------------


# Both Markdown heading style ("## Summary of changes") and bold-label style
# ("**Summary of changes**") are accepted, because different free models prefer
# different conventions. Order matters: try bold-label first because it's
# ambiguous (a paragraph can legitimately contain the word "Summary").
SECTION_HEADERS = {
    "summary": r"(?im)(?:^|\n)\s*(?:\*\*|#{1,4})\s*(?:\d+\.\s*)?summary(?:\s*of\s*(?:the\s*)?changes?)?\s*:?\s*(?:\*\*)",
    "risks": r"(?im)(?:^|\n)\s*(?:\*\*|#{1,4})\s*(?:\d+\.\s*)?(?:identified\s+)?risks?\s*:?\s*(?:\*\*)",
    "suggestions": r"(?im)(?:^|\n)\s*(?:\*\*|#{1,4})\s*(?:\d+\.\s*)?(?:improvement\s+)?suggestions?\s*(?:\([^)]*\))?\s*:?\s*(?:\*\*)",
    "confidence": r"(?im)(?:^|\n)\s*(?:\*\*|#{1,4})\s*(?:\d+\.\s*)?confidence(?:\s+score)?\s*:?\s*(?:\*\*)",
}

CONFIDENCE_RE = re.compile(r"\b(low|medium|high)\b", re.IGNORECASE)


def split_sections(text: str) -> dict[str, str]:
    """Split a model response into the four canonical sections.

    Falls back to heuristic matching if the model didn't follow the format exactly.
    """
    text = text.replace("\r\n", "\n").strip()

    # Find header positions
    positions = []
    for key, pattern in SECTION_HEADERS.items():
        for m in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
            positions.append((m.start(), m.end(), key, m.group(0)))
            break

    if len(positions) < 4:
        # Try a softer pass — find any of these tokens as headings
        return _fallback_parse(text)

    positions.sort()
    sections: dict[str, str] = {}
    for i, (start, end, key, header_text) in enumerate(positions):
        next_start = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        body = text[end:next_start].strip("\n ")
        sections[key] = body

    return sections


def _fallback_parse(text: str) -> dict[str, str]:
    """Best-effort split when the model didn't use proper section headers."""
    # Use line-based heuristics: split on bold lines or numbered headings.
    parts = {"summary": "", "risks": "", "suggestions": "", "confidence": ""}
    current = "summary"
    bucket: list[str] = []

    def flush() -> None:
        parts[current] = "\n".join(bucket).strip()

    for line in text.splitlines():
        low = line.strip().lower()
        # Heading style
        if re.match(r"^#{1,4}\s*(?:\d+\.\s*)?summary", low):
            flush(); bucket = []; current = "summary"; continue
        if re.match(r"^#{1,4}\s*(?:\d+\.\s*)?(?:identified\s+)?risks?", low):
            flush(); bucket = []; current = "risks"; continue
        if re.match(r"^#{1,4}\s*(?:\d+\.\s*)?(?:improvement\s+)?suggestions?", low):
            flush(); bucket = []; current = "suggestions"; continue
        if re.match(r"^#{1,4}\s*(?:\d+\.\s*)?confidence", low):
            flush(); bucket = []; current = "confidence"; continue
        # Bold-label style: **Summary of changes**, **Identified risks**, etc.
        if re.match(r"^\*\*(?:summary|identified\s+risks?|risks?)\b", low):
            flush(); bucket = []; current = "summary" if "summary" in low else "risks"; continue
        if re.match(r"^\*\*(?:improvement\s+)?suggestions?\b", low):
            flush(); bucket = []; current = "suggestions"; continue
        if re.match(r"^\*\*confidence\b", low):
            flush(); bucket = []; current = "confidence"; continue
        bucket.append(line)
    flush()
    return parts


def normalize_confidence(raw: str) -> str:
    """Extract a single Low/Medium/High token from the confidence section."""
    if not raw:
        return "Medium"
    m = CONFIDENCE_RE.search(raw)
    if not m:
        return "Medium"
    word = m.group(1).capitalize()
    return word if word in {"Low", "Medium", "High"} else "Medium"


def _ensure_bullets(section: str, fallback_line: str) -> str:
    """Ensure a section is bulleted. Wrap a single-line section as '- line'."""
    s = section.strip()
    if not s:
        return f"- {fallback_line}"
    if not re.search(r"^\s*[-*+]\s", s, re.MULTILINE):
        # Wrap each non-empty line as a bullet
        lines = [ln for ln in s.splitlines() if ln.strip()]
        if not lines:
            return f"- {fallback_line}"
        return "\n".join(f"- {ln.lstrip('-* ').strip()}" for ln in lines)
    return s


def build_review_markdown(pr: PRData, raw_response: str, model_used: str) -> str:
    """Build the final Markdown review from the model output."""
    # Strip leading/trailing whitespace and de-indent so textwrap.dedent works
    # even when the model returns leading newlines or extra indentation.
    cleaned_response = textwrap.dedent(raw_response.strip("\n")).strip()
    sections = split_sections(cleaned_response)

    summary = sections.get("summary", "").strip()
    risks = sections.get("risks", "")
    suggestions = sections.get("suggestions", "")
    confidence = normalize_confidence(sections.get("confidence", ""))
    confidence_justification = sections.get("confidence", "").strip()
    # Strip the leading "Low/Medium/High" token out of the justification body
    confidence_justification = re.sub(
        r"^\s*(?:\*\*)?\s*(?:Low|Medium|High)\s*(?:\*\*)?\s*[-–—:]*\s*",
        "",
        confidence_justification,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    if not confidence_justification:
        confidence_justification = "_(no justification provided by the model)_"

    # Guarantee all four required sections are non-empty
    if not summary:
        summary = (
            f"Changes touch {pr.changed_files} file(s) across "
            f"`{pr.short_ref}`. Detailed analysis could not be extracted from the model "
            f"response; see raw output below."
        )
    risks = _ensure_bullets(risks, "No specific risks identified — review the diff manually.")
    suggestions = _ensure_bullets(suggestions, "No specific suggestions generated.")

    confidence_emoji = {"Low": "🟠", "Medium": "🟡", "High": "🟢"}[confidence]

    file_list = "\n".join(
        f"- `{f['path']}` (+{f['additions']} / -{f['deletions']})"
        for f in pr.files[:25]
    ) or "- _(no file metadata available)_"

    # Build the body without leading template indentation so textwrap.dedent
    # doesn't matter — every inserted value is already at column 0.
    body = f"""<!-- claude-review (issue #4) — generated by agents/pr-reviewer/claude_review.py -->
## 🔍 Claude Code PR Review — `{pr.short_ref}`

**{pr.title}**

**Author:** @{pr.author} &nbsp;·&nbsp; **Base:** `{pr.base_ref}` &nbsp;·&nbsp; **Head:** `{pr.head_ref}`
**Files changed:** {pr.changed_files} &nbsp;·&nbsp; **+{pr.additions} / -{pr.deletions}** &nbsp;·&nbsp; **State:** {pr.state}
**Model:** `{model_used}` &nbsp;·&nbsp; **Confidence:** {confidence_emoji} **{confidence}**

---

### 📝 Summary of changes

{summary}

### ⚠️ Identified risks

{risks}

### 💡 Improvement suggestions

{suggestions}

### ✅ Confidence: **{confidence}**

{confidence_justification}

---

### 📂 Files in this PR

{file_list}

<sub>Generated by `agents/pr-reviewer/claude_review.py` from `{pr.url}`. Model output below is preserved verbatim for transparency.</sub>

<details><summary>Raw model response</summary>

```text
{cleaned_response}
```

</details>
"""
    return body.strip("\n")


# ---------------------------------------------------------------------------
# Posting the review
# ---------------------------------------------------------------------------


def post_review(pr: PRData, markdown: str) -> None:
    """Post the review as a PR comment via `gh pr comment`."""
    _run_gh([
        "pr", "comment", str(pr.number),
        "--repo", f"{pr.owner}/{pr.repo}",
        "--body-file", "-",
    ], timeout=120)
    # `gh pr comment --body-file -` reads from stdin
    try:
        result = subprocess.run(
            [
                "gh", "pr", "comment", str(pr.number),
                "--repo", f"{pr.owner}/{pr.repo}",
                "--body-file", "-",
            ],
            input=markdown,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        print(result.stdout.strip(), file=sys.stderr)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Failed to post comment: {(exc.stderr or '').strip()}"
        ) from exc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _make_prompt(pr: PRData) -> str:
    """Build the LLM prompt from PR metadata + diff."""
    files_brief = ", ".join(f["path"] for f in pr.files[:30]) or "(none)"
    return textwrap.dedent(f"""\
        You are reviewing the following GitHub Pull Request.

        PR: {pr.short_ref}
        Title: {pr.title}
        Author: @{pr.author}
        Base branch: {pr.base_ref}
        Head branch: {pr.head_ref}
        Files ({pr.changed_files}): {files_brief}
        +{pr.additions} / -{pr.deletions}

        Description:
        ---
        {pr.body[:2000] or "(empty)"}
        ---

        Diff (unified):
        ```diff
        {pr.diff}
        ```

        Write a structured review using EXACTLY these four sections, in this order.
        Use Markdown headings or bold labels — but every section MUST be present and
        clearly labelled so a parser can extract them.

        ## Summary of changes
        (2-3 sentences describing what this PR does and why)

        ## Identified risks
        (bulleted list — bugs, security, performance, regressions, data-loss. Use "- " prefix.)

        ## Improvement suggestions
        (bulleted list — concrete fixes, refactors, tests, docs. Use "- " prefix.)

        ## Confidence
        (one of: Low, Medium, High — with a one-line justification)

        Be specific. Cite file paths or symbols where relevant. Avoid filler.
        """)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="claude-review",
        description="Claude Code PR-reviewer sub-agent (issue #4 of claude-builders-bounty).",
    )
    parser.add_argument("--pr", required=True, help="URL of the PR to review, e.g. https://github.com/owner/repo/pull/123")
    parser.add_argument("--post", action="store_true", help="Post the review as a PR comment via `gh pr comment`")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and analyse but do NOT post (default if --post is omitted)")
    parser.add_argument("--output", "-o", default=None, help="Also write the markdown review to this file")
    parser.add_argument("--max-diff-chars", type=int, default=DEFAULT_MAX_DIFF_CHARS,
                        help=f"Cap diff at this many characters (default {DEFAULT_MAX_DIFF_CHARS})")
    parser.add_argument("--model", default=None, help="Override the OpenRouter model (default: priority chain)")
    args = parser.parse_args(argv)

    try:
        pr = fetch_pr(args.pr, max_diff_chars=args.max_diff_chars)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"Loaded {pr.short_ref}: '{pr.title}' "
        f"({pr.changed_files} files, +{pr.additions}/-{pr.deletions})",
        file=sys.stderr,
    )

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print(
            "error: OPENROUTER_API_KEY environment variable is not set.",
            file=sys.stderr,
        )
        return 3

    prompt = _make_prompt(pr)
    try:
        model_used, raw = call_openrouter(prompt, api_key=api_key)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4

    markdown = build_review_markdown(pr, raw, model_used=model_used)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(markdown)
        print(f"Wrote review markdown to {args.output}", file=sys.stderr)

    print(markdown)

    if args.post and not args.dry_run:
        try:
            post_review(pr, markdown)
            print(f"Posted review to {pr.url}", file=sys.stderr)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 5

    return 0


if __name__ == "__main__":
    raise SystemExit(main())