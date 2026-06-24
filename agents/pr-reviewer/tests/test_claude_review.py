"""Smoke tests for the Claude Code PR Reviewer sub-agent."""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_DIR = HERE.parent
ROOT = AGENT_DIR  # module name is `claude_review`, lives in this dir


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "claude_review", AGENT_DIR / "claude_review.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["claude_review"] = mod
    spec.loader.exec_module(mod)
    return mod


cr = _load_module()


VALID_URL = "https://github.com/claude-builders-bounty/claude-builders-bounty/pull/3015"
VALID_URL_2 = "https://github.com/moorcheh-ai/memanto/pull/774"
BAD_URL = "https://gitlab.com/foo/bar/-/merge_requests/1"

CLEAN_DIFF = """\
diff --git a/src/util.py b/src/util.py
--- a/src/util.py
+++ b/src/util.py
@@ -1,3 +1,4 @@
 def add(a: int, b: int) -> int:
+    \"\"\"Add two integers.\"\"\"
     return a + b
"""

SECRET_DIFF = """\
diff --git a/config.py b/config.py
--- a/config.py
+++ b/config.py
@@ -1,2 +1,3 @@
+DB_PASSWORD = "supersecret123"
 def connect():
     pass
"""

SHELL_TRUE_DIFF = """\
diff --git a/run.py b/run.py
--- a/run.py
+++ b/run.py
@@ -1,2 +1,3 @@
+subprocess.run(f"echo {user_input}", shell=True)
 import os
"""

FORCE_PUSH_DIFF = """\
diff --git a/deploy.sh b/deploy.sh
--- a/deploy.sh
+++ b/deploy.sh
@@ -1,2 +1,3 @@
 #!/usr/bin/env bash
+git push --force origin main
 echo "deploying"
"""


class TestURLParsing(unittest.TestCase):
    def test_valid_pr_url(self):
        owner, repo, num = cr.parse_pr_url(VALID_URL)
        self.assertEqual(owner, "claude-builders-bounty")
        self.assertEqual(repo, "claude-builders-bounty")
        self.assertEqual(num, 3015)

    def test_valid_pr_url_with_trailing_slash(self):
        owner, repo, num = cr.parse_pr_url(VALID_URL + "/")
        self.assertEqual(num, 3015)

    def test_valid_pr_url_other_repo(self):
        owner, repo, num = cr.parse_pr_url(VALID_URL_2)
        self.assertEqual((owner, repo, num), ("moorcheh-ai", "memanto", 774))

    def test_invalid_url_raises(self):
        with self.assertRaises(ValueError):
            cr.parse_pr_url(BAD_URL)

    def test_non_pr_url_raises(self):
        with self.assertRaises(ValueError):
            cr.parse_pr_url("https://github.com/owner/repo")


class TestDiffParsing(unittest.TestCase):
    def test_simple_diff(self):
        lines = cr.parse_unified_diff(CLEAN_DIFF)
        added = [l for l in lines if l.op == "+"]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].file, "src/util.py")
        self.assertIn("Add two integers", added[0].content)

    def test_empty_diff(self):
        self.assertEqual(cr.parse_unified_diff(""), [])


class TestHeuristicReview(unittest.TestCase):
    def test_clean_diff_is_high_confidence(self):
        r = cr.heuristic_review(None, CLEAN_DIFF)
        self.assertEqual(r.confidence, "High")
        self.assertEqual(r.risks, [])
        self.assertEqual(r.source, "heuristic")

    def test_secret_detected(self):
        r = cr.heuristic_review(None, SECRET_DIFF)
        rule_ids = {f.rule for f in r.risks + r.suggestions}
        self.assertIn("hardcoded-secret", rule_ids)
        self.assertEqual(r.risks[0].severity, "critical")

    def test_shell_true_detected(self):
        r = cr.heuristic_review(None, SHELL_TRUE_DIFF)
        rule_ids = {f.rule for f in r.risks + r.suggestions}
        self.assertIn("shell-true", rule_ids)

    def test_force_push_detected(self):
        r = cr.heuristic_review(None, FORCE_PUSH_DIFF)
        rule_ids = {f.rule for f in r.risks + r.suggestions}
        self.assertIn("force-push", rule_ids)

    def test_summary_includes_file_count(self):
        r = cr.heuristic_review(None, SECRET_DIFF)
        self.assertIn("config.py", r.summary)


class TestRendering(unittest.TestCase):
    def test_markdown_has_required_sections(self):
        r = cr.heuristic_review(None, SECRET_DIFF)
        md = cr.render_markdown_from_review(r)
        self.assertIn("## Summary", md)
        self.assertIn("## Risks", md)
        self.assertIn("## Improvement Suggestions", md)
        self.assertIn("## Confidence", md)

    def test_markdown_passes_section_validator(self):
        r = cr.heuristic_review(None, SHELL_TRUE_DIFF)
        md = cr.render_markdown_from_review(r)
        self.assertTrue(cr.has_required_sections(md))

    def test_json_output_is_valid(self):
        r = cr.heuristic_review(None, SECRET_DIFF)
        j = json.loads(cr.render_json(r))
        self.assertIn("summary", j)
        self.assertIn("confidence", j)
        self.assertIn("risks", j)
        self.assertIn("suggestions", j)
        self.assertIsInstance(j["risks"], list)

    def test_fill_missing_sections(self):
        # When claude returns only `## Summary`, we should splice in the
        # missing sections from the fallback.
        fallback = cr.heuristic_review(None, SECRET_DIFF)
        partial = "## Summary\nTiny summary.\n"
        patched = cr.fill_missing_sections(partial, fallback)
        self.assertTrue(cr.has_required_sections(patched))


class TestRunReview(unittest.TestCase):
    def test_local_diff_with_no_claude(self):
        review, md = cr.run_review(
            diff_path="-" if False else None,
            use_claude=False,
        ) if False else (None, None)
        # Re-do properly using tmp file
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as f:
            f.write(SECRET_DIFF)
            tmp = f.name
        try:
            review, md = cr.run_review(diff_path=tmp, use_claude=False)
            self.assertEqual(review.source, "heuristic")
            self.assertTrue(cr.has_required_sections(md))
            self.assertIn("hardcoded-secret", {f.rule for f in review.risks})
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_stdin_diff_via_dash(self):
        import tempfile, os
        # Write diff to stdin by patching sys.stdin
        old_stdin = sys.stdin
        sys.stdin = type("S", (), {"read": staticmethod(lambda: SECRET_DIFF)})()
        try:
            review, md = cr.run_review(diff_path="-", use_claude=False)
            self.assertTrue(cr.has_required_sections(md))
            self.assertIn("hardcoded-secret", {f.rule for f in review.risks})
        finally:
            sys.stdin = old_stdin


class TestExampleOutputs(unittest.TestCase):
    """The bounty requires examples from 2 real PRs."""

    def test_example_pr_3015_exists_and_is_well_formed(self):
        path = AGENT_DIR / "examples" / "review-pr-3015.md"
        self.assertTrue(path.exists(), f"{path} missing")
        text = path.read_text()
        self.assertTrue(
            cr.has_required_sections(text),
            "review-pr-3015.md missing required sections",
        )
        # Should reference cbb-3015 by either its PR number or slug
        self.assertTrue(
            "3015" in text or "claude-builders-bounty/claude-builders-bounty" in text,
            "review-pr-3015.md missing PR identifier",
        )

    def test_example_pr_774_exists_and_is_well_formed(self):
        path = AGENT_DIR / "examples" / "review-pr-774.md"
        self.assertTrue(path.exists(), f"{path} missing")
        text = path.read_text()
        self.assertTrue(
            cr.has_required_sections(text),
            "review-pr-774.md missing required sections",
        )
        self.assertTrue(
            "774" in text or "memanto" in text,
            "review-pr-774.md missing PR identifier",
        )

    def test_examples_have_substantive_content(self):
        for name in ("review-pr-3015.md", "review-pr-774.md"):
            text = (AGENT_DIR / "examples" / name).read_text()
            self.assertGreater(
                len(text), 200,
                f"{name} looks empty ({len(text)} chars)",
            )


class TestCLI(unittest.TestCase):
    def test_help_exits_zero(self):
        with self.assertRaises(SystemExit) as cm:
            cr.main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_missing_source_arg_errors(self):
        with self.assertRaises(SystemExit) as cm:
            cr.main([])
        self.assertEqual(cm.exception.code, 2)  # argparse error

    def test_post_without_pr_errors(self):
        # main() returns 1 instead of calling sys.exit for this case
        rc = cr.main(["--diff", "x", "--post"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
