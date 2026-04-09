"""
Tests for PR review utilities.

_build_diff_line_set is pure Python with no external dependencies.
It parses unified diff patches to determine which lines accept
inline GitHub review comments — a subtle parser that's worth testing.
"""
from django.test import SimpleTestCase

from apps.pr_review.github_client import _build_diff_line_set


class TestBuildDiffLineSet(SimpleTestCase):

    def test_empty_patch_returns_empty_set(self):
        self.assertEqual(_build_diff_line_set(""), set())

    def test_single_added_line(self):
        patch = "@@ -1,3 +1,4 @@\n line1\n line2\n+added line\n line3"
        lines = _build_diff_line_set(patch)
        self.assertIn(3, lines)  # "added line" is the 3rd line in the new file

    def test_removed_lines_not_in_set(self):
        patch = "@@ -1,3 +1,2 @@\n line1\n-removed line\n line2"
        lines = _build_diff_line_set(patch)
        # Only "+" lines are valid comment targets; "-" lines are gone
        self.assertEqual(len(lines), 0)

    def test_context_lines_not_in_set(self):
        """Context lines (no prefix) advance the counter but are not diff lines."""
        patch = "@@ -1,3 +1,3 @@\n context1\n context2\n context3"
        lines = _build_diff_line_set(patch)
        self.assertEqual(lines, set())

    def test_multiple_added_lines(self):
        patch = "@@ -1,1 +1,3 @@\n existing\n+new1\n+new2"
        lines = _build_diff_line_set(patch)
        self.assertIn(2, lines)
        self.assertIn(3, lines)

    def test_multiple_hunks(self):
        patch = (
            "@@ -1,2 +1,3 @@\n ctx\n+added1\n ctx2\n"
            "@@ -10,2 +11,3 @@\n ctx\n+added2\n ctx2"
        )
        lines = _build_diff_line_set(patch)
        self.assertIn(2, lines)   # added1 is at new-file line 2
        self.assertIn(12, lines)  # added2 is at new-file line 12

    def test_hunk_starting_at_line_1(self):
        patch = "@@ -0,0 +1,2 @@\n+first line\n+second line"
        lines = _build_diff_line_set(patch)
        self.assertIn(1, lines)
        self.assertIn(2, lines)

    def test_hunk_starting_mid_file(self):
        patch = "@@ -50,3 +50,4 @@\n ctx\n ctx\n+new line here\n ctx"
        lines = _build_diff_line_set(patch)
        self.assertIn(52, lines)  # 50 + 2 context lines before the addition

    def test_mix_of_additions_and_removals(self):
        # "@@ -1,4 +1,4 @@": new file starts at line 1
        # line 1: ctx (context, not a diff target)
        # line 2: +new line (replaces -old line, lands at new-file line 2)
        # line 3: ctx (context)
        patch = "@@ -1,4 +1,4 @@\n ctx\n-old line\n+new line\n ctx"
        lines = _build_diff_line_set(patch)
        self.assertIn(2, lines)
        self.assertEqual(len(lines), 1)

    def test_patch_with_no_hunk_header_does_not_raise(self):
        """Malformed patch without @@ header must not raise (behavior is unspecified)."""
        patch = "+some added line\n-some removed line"
        try:
            _build_diff_line_set(patch)
        except Exception as exc:
            self.fail(f"_build_diff_line_set raised on malformed patch: {exc}")
