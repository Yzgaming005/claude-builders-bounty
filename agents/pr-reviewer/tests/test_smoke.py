"""Smoke tests for claude-review.

These tests do NOT make network calls — they're safe to run in CI without
OPENROUTER_API_KEY or gh auth. They cover URL parsing, section splitting,
confidence normalization, and the build_review_markdown function.
"""

from __future__ import annotations

import os
import sys
import unittest

# Make sibling modules importable
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import claude_review  # noqa: E402
from claude_review import PRData, build_review_markdown, parse_pr_url, split_sections, normalize_confidence  # noqa: E402


class TestParsePRUrl(unittest.TestCase):
    def test_basic(self):
        owner, repo, num = parse_pr_url("https://github.com/octocat/Hello-World/pull/42")
        self.assertEqual(owner, "octocat")
        self.assertEqual(repo, "Hello-World")
        self.assertEqual(num, 42)

    def test_trailing_slash(self):
        owner, repo, num = parse_pr_url("https://github.com/octocat/Hello-World/pull/42/")
        self.assertEqual((owner, repo, num), ("octocat", "Hello-World", 42))

    def test_http(self):
        owner, repo, num = parse_pr_url("http://github.com/octocat/Hello-World/pull/42")
        self.assertEqual((owner, repo, num), ("octocat", "Hello-World", 42))

    def test_invalid(self):
        for bad in [
            "",
            "github.com/octocat/Hello-World/pull/42",
            "https://gitlab.com/octocat/Hello-World/pull/42",
            "https://github.com/octocat/Hello-World/issues/42",
        ]:
            with self.assertRaises(ValueError):
                parse_pr_url(bad)


class TestSplitSections(unittest.TestCase):
    def test_well_formed(self):
        text = """\
Some preamble.

## Summary of changes
Adds a thing.

## Identified risks
- bug 1
- bug 2

## Improvement suggestions
- fix it

## Confidence
High — looks good.
"""
        out = split_sections(text)
        self.assertIn("Adds a thing", out["summary"])
        self.assertIn("bug 1", out["risks"])
        self.assertIn("fix it", out["suggestions"])
        self.assertIn("High", out["confidence"])

    def test_with_numbered_headings(self):
        text = """\
## 1. Summary of changes
Stuff.

## 2. Identified risks
- r1

## 3. Improvement suggestions
- s1

## 4. Confidence
Medium.
"""
        out = split_sections(text)
        self.assertIn("Stuff", out["summary"])
        self.assertIn("r1", out["risks"])

    def test_fallback_when_missing_sections(self):
        text = "Just some prose, no headings at all.\nNothing parseable."
        out = split_sections(text)
        # All keys present, possibly empty, but no crash
        for key in ("summary", "risks", "suggestions", "confidence"):
            self.assertIn(key, out)

    def test_bold_label_style(self):
        text = """\
**Summary of changes**
Adds a thing.

**Identified risks**
- r1
- r2

**Improvement suggestions**
- s1

**Confidence**
Medium.
"""
        out = split_sections(text)
        self.assertIn("Adds a thing", out["summary"])
        self.assertIn("r1", out["risks"])
        self.assertIn("s1", out["suggestions"])
        self.assertIn("Medium", out["confidence"])


class TestNormalizeConfidence(unittest.TestCase):
    def test_low(self):
        self.assertEqual(normalize_confidence("Low — unclear"), "Low")
    def test_medium(self):
        self.assertEqual(normalize_confidence("Confidence: Medium."), "Medium")
    def test_high(self):
        self.assertEqual(normalize_confidence("HIGH"), "High")
    def test_fallback(self):
        self.assertEqual(normalize_confidence(""), "Medium")
        self.assertEqual(normalize_confidence("??? not sure"), "Medium")


class TestBuildReviewMarkdown(unittest.TestCase):
    def _pr(self):
        return PRData(
            url="https://github.com/foo/bar/pull/7",
            owner="foo", repo="bar", number=7,
            title="Test PR", author="alice", base_ref="main", head_ref="feature",
            body="", state="OPEN", additions=10, deletions=5, changed_files=2,
            files=[
                {"path": "a.py", "additions": 7, "deletions": 3, "changeType": "MODIFIED"},
                {"path": "b.py", "additions": 3, "deletions": 2, "changeType": "ADDED"},
            ],
            diff="diff --git ...",
        )

    def test_all_required_sections_present(self):
        pr = self._pr()
        raw = """\
## Summary of changes
Adds a tiny helper that does X.

## Identified risks
- risk 1
- risk 2

## Improvement suggestions
- suggestion 1

## Confidence
High — small and clear.
"""
        md = build_review_markdown(pr, raw, model_used="openai/gpt-oss-20b:free")
        for header in [
            "### 📝 Summary of changes",
            "### ⚠️ Identified risks",
            "### 💡 Improvement suggestions",
            "### ✅ Confidence:",
        ]:
            self.assertIn(header, md)
        # File list
        self.assertIn("`a.py`", md)
        self.assertIn("+10 / -5", md)
        # Confidence value present
        self.assertIn("High", md)
        # Raw response preserved
        self.assertIn("Raw model response", md)

    def test_handles_missing_sections(self):
        pr = self._pr()
        md = build_review_markdown(pr, "no sections here", model_used="x")
        # All four sections still present, even if empty
        for header in [
            "Summary of changes",
            "Identified risks",
            "Improvement suggestions",
            "Confidence",
        ]:
            self.assertIn(header, md)

    def test_handles_non_bulleted_risks(self):
        pr = self._pr()
        raw = """\
## Summary of changes
X.

## Identified risks
risk 1
risk 2

## Improvement suggestions
- s1

## Confidence
Medium.
"""
        md = build_review_markdown(pr, raw, model_used="x")
        # Should have been converted to bullets
        self.assertIn("- risk 1", md)
        self.assertIn("- risk 2", md)


class TestCLIHelp(unittest.TestCase):
    def test_help_runs(self):
        import subprocess
        script = os.path.join(os.path.dirname(HERE), "claude_review.py")
        proc = subprocess.run(
            ["python3", script, "--help"],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--pr", proc.stdout)
        self.assertIn("--post", proc.stdout)


if __name__ == "__main__":
    unittest.main()