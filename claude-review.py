#!/usr/bin/env python3
"""
claude-review: A simple CLI tool to generate a structured review comment for a GitHub PR.
Usage:
  claude-review --pr <owner/repo>#<num>
  claude-review --pr https://github.com/owner/repo/pull/123
Outputs a Markdown review comment to stdout.
"""
import argparse
import json
import re
import subprocess
import sys

def run_cmd(cmd):
    """Run a shell command and return stdout as string."""
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {cmd}", file=sys.stderr)
        print(e, file=sys.stderr)
        sys.exit(1)

def parse_pr_arg(arg):
    """Accept either full URL or owner/repo#num."""
    if arg.startswith("http"):
        m = re.search(r"github\.com/([^/]+/[^/]+)/pull/(\\d+)", arg)
        if not m:
            raise ValueError("Invalid GitHub PR URL")
        repo, num = m.group(1), m.group(2)
    else:
        if "#" not in arg:
            raise ValueError("Expected format owner/repo#<num> or full URL")
        repo, num = arg.split("#")
    return repo, num

def get_pr_info(repo, num):
    """Fetch PR data using gh api."""
    # Get basic PR info
    cmd = f"gh api repos/{repo}/pulls/{num}"
    data = json.loads(run_cmd(cmd))
    # Get changed files list
    files_cmd = f"gh api repos/{repo}/pulls/{num}/files"
    files_data = json.loads(run_cmd(files_cmd))
    return data, files_data

def analyze_changes(files_data):
    """Simple analysis of changed files."""
    total_files = len(files_data)
    additions = sum(f.get("additions", 0) for f in files_data)
    deletions = sum(f.get("deletions", 0) for f in files_data)
    # Risk detection: look for sensitive paths
    risk_keywords = ["auth", "password", "secret", ".env", "config", "key", "token"]
    risky_files = []
    for f in files_data:
        path = f.get("filename", "").lower()
        if any(k in path for k in risk_keywords):
            risky_files.append(f["filename"])
    # Heuristics for suggestions
    suggestions = []
    if total_files > 10:
        suggestions.append("Consider breaking large changes into smaller, focused PRs.")
    if additions > 500:
        suggestions.append("Large number of additions; consider adding automated tests for new code.")
    # Check for missing tests
    test_files = [f for f in files_data if "test" in f["filename"].lower()]
    if not test_files and any(".py" in f["filename"] or ".js" in f["filename"] or ".ts" in f["filename"] for f in files_data):
        suggestions.append("Consider adding tests for new or modified logic.")
    return {
        "files_changed": total_files,
        "additions": additions,
        "deletions": deletions,
        "risky_files": risky_files,
        "suggestions": suggestions,
    }

def format_comment(pr_info, analysis):
    """Generate markdown comment."""
    title = pr_info.get("title", "No title")
    author = pr_info.get("user", {}).get("login", "unknown")
    html_url = pr_info.get("html_url", "")
    # Summary
    summary = f"PR #{pr_info['number']} \"{title}\" by @{author} modifies {analysis['files_changed']} file(s) with {analysis['additions']} additions and {analysis['deletions']} deletions."
    # Risks
    risks = []
    if analysis["risky_files"]:
        risks.append(f"Changes touch sensitive files: {', '.join(analysis['risky_files'])}")
    else:
        risks.append("No obvious risky file changes detected.")
    # Improvements
    if analysis["suggestions"]:
        improvements = analysis["suggestions"]
    else:
        improvements = ["Code changes look good; consider adding tests if applicable."]
    # Confidence (simple heuristic)
    confidence = "Medium"
    if analysis["risky_files"]:
        confidence = "Low"
    elif analysis["files_changed"] <= 5 and analysis["additions"] < 50:
        confidence = "High"
    # Build markdown
    md = f"""## PR Review by claude-review

**Summary**
{summary}

**Risks**
{chr(10).join(f"- {r}" for r in risks)}

**Improvement Suggestions**
{chr(10).join(f"- {s}" for s in analysis["suggestions"])}

**Confidence:** {confidence}

*This review was generated automatically by [claude-review](https://github.com/yourname/claude-review).*
"""
    return md

def main():
    parser = argparse.ArgumentParser(description="Generate a structured PR review comment.")
    parser.add_argument("--pr", required=True, help="GitHub PR URL or owner/repo#<num>")
    args = parser.parse_args()
    try:
        repo, num = parse_pr_arg(args.pr)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    pr_info, files_data = get_pr_info(repo, num)
    analysis = analyze_changes(files_data)
    comment = format_comment(pr_info, analysis)
    print(comment)

if __name__ == "__main__":
    main()