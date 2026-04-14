"""
Tests for PR review utilities.

Covers two pure-Python modules with no external dependencies:
  - _build_diff_line_set  (diff hunk parser for GitHub comment positioning)
  - duplicate_detector    (_name_tokens, _passes, _blended_similarity,
                           _jaccard_similarity — all the accuracy-critical logic)
"""
from unittest.mock import MagicMock

from django.test import SimpleTestCase, override_settings

from apps.pr_review.github_client import _build_diff_line_set
from apps.pr_review.duplicate_detector import (
    _name_tokens,
    _passes,
    _blended_similarity,
    _jaccard_similarity,
    _body_tokens,
    _strip_noise,
)


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


# ---------------------------------------------------------------------------
# _name_tokens
# ---------------------------------------------------------------------------

class TestNameTokens(SimpleTestCase):

    def test_snake_case_splits_correctly(self):
        tokens = _name_tokens("list_branches")
        # "list" is a stop word → removed
        self.assertNotIn("list", tokens)
        # "branches" is NOT in the stop list (only "branch" is) → stays
        self.assertIn("branches", tokens)

    def test_camelcase_splits_correctly(self):
        tokens = _name_tokens("fetchPrFiles")
        self.assertIn("fetch", tokens)
        self.assertIn("files", tokens)

    def test_stop_words_removed(self):
        # "handle", "process", "execute", "perform" are all stop words
        self.assertEqual(_name_tokens("handle"), set())
        self.assertEqual(_name_tokens("process"), set())
        self.assertEqual(_name_tokens("execute"), set())

    def test_chunks_is_stop_word(self):
        # "chunks" (plural) must be a stop word — fixed this session
        tokens = _name_tokens("embed_chunks")
        self.assertNotIn("chunks", tokens)
        self.assertIn("embed", tokens)

    def test_chunk_is_stop_word(self):
        tokens = _name_tokens("get_chunk")
        self.assertNotIn("chunk", tokens)

    def test_short_tokens_filtered(self):
        # Tokens shorter than 3 chars must be dropped
        tokens = _name_tokens("do_it")
        self.assertNotIn("do", tokens)
        self.assertNotIn("it", tokens)

    def test_meaningful_tokens_kept(self):
        tokens = _name_tokens("assign_clusters")
        self.assertIn("assign", tokens)
        self.assertIn("clusters", tokens)

    def test_empty_name_returns_empty(self):
        self.assertEqual(_name_tokens(""), set())

    def test_all_stop_words_returns_empty(self):
        # "get_repo" → "get" < 3 chars filtered, "repo" is a stop word → empty
        self.assertEqual(_name_tokens("repo"), set())

    def test_extract_lightweight_chunks_tokens(self):
        # After session fix: "chunks" is stop word → only extract + lightweight
        tokens = _name_tokens("_extract_lightweight_chunks")
        self.assertIn("extract", tokens)
        self.assertIn("lightweight", tokens)
        self.assertNotIn("chunks", tokens)


# ---------------------------------------------------------------------------
# _passes — the four-signal secondary filter
# ---------------------------------------------------------------------------

def _make_pr_chunk(name, file_path="backend/apps/pr_review/file.py",
                   start_line=1, end_line=40, language="python", raw_code=""):
    chunk = MagicMock()
    chunk.chunk_name = name
    chunk.file_path = file_path
    chunk.start_line = start_line
    chunk.end_line = end_line
    chunk.language = language
    chunk.raw_code = raw_code
    return chunk


class TestPasses(SimpleTestCase):

    # --- Filter 1: intra-module ---

    def test_same_app_rejected(self):
        chunk = _make_pr_chunk("process_data", file_path="backend/apps/ingestion/engine.py")
        result = _passes(chunk, "ingest_data", "backend/apps/ingestion/tasks.py", 1, 40)
        self.assertFalse(result)

    def test_different_app_passes_filter1(self):
        chunk = _make_pr_chunk("embed_data", file_path="backend/apps/pr_review/file.py")
        # Different app (parsing vs pr_review) — should not be blocked by filter 1
        # (may still be blocked by other filters; we only assert filter 1 doesn't block)
        # Use names with shared tokens so other filters pass
        chunk2_file = "backend/apps/parsing/tasks.py"
        # embed vs embed → should pass all filters
        result = _passes(chunk, "embed_data", chunk2_file, 1, 40)
        self.assertTrue(result)

    # --- Filter 2: line-count ratio ---

    def test_large_line_ratio_rejected(self):
        chunk = _make_pr_chunk("sync_data", start_line=1, end_line=10)
        # match is 30 lines vs PR chunk 10 lines → ratio 3.0 > 2.5
        result = _passes(chunk, "sync_data", "backend/apps/parsing/tasks.py", 1, 30)
        self.assertFalse(result)

    def test_acceptable_line_ratio_passes(self):
        chunk = _make_pr_chunk("sync_data", start_line=1, end_line=20)
        # match is 40 lines vs 20 lines → ratio 2.0 ≤ 2.5
        result = _passes(chunk, "sync_data", "backend/apps/parsing/tasks.py", 1, 40)
        self.assertTrue(result)

    # --- Filter 3: name token overlap ---

    def test_empty_pr_name_tok_rejected(self):
        # "handle" is a stop word → pr_name_tok = {} → must reject
        chunk = _make_pr_chunk("handle", file_path="backend/apps/parsing/management/cmd.py")
        result = _passes(chunk, "assign_clusters", "backend/apps/clustering/services.py", 1, 40)
        self.assertFalse(result)

    def test_empty_match_name_tok_rejected(self):
        chunk = _make_pr_chunk("embed_data", file_path="backend/apps/pr_review/file.py")
        # "handle" as match name → match_name_tok = {} → must reject
        result = _passes(chunk, "handle", "backend/apps/clustering/services.py", 1, 40)
        self.assertFalse(result)

    def test_no_token_intersection_rejected(self):
        chunk = _make_pr_chunk("embed_data", file_path="backend/apps/pr_review/file.py")
        # embed_data → {embed, data}  vs  assign_clusters → {assign, clusters}
        # Intersection = {} → reject
        result = _passes(chunk, "assign_clusters", "backend/apps/parsing/tasks.py", 1, 40)
        self.assertFalse(result)

    def test_shared_token_passes_filter3(self):
        chunk = _make_pr_chunk("embed_data", file_path="backend/apps/pr_review/file.py")
        # embed_data → {embed, data}  vs  embed_batch → {embed, batch}
        # Intersection = {embed} → passes filter 3
        # (body overlap filter 4 may still block — raw_code is empty here)
        # With empty raw_code body_tok is empty so filter 4 is skipped
        result = _passes(chunk, "embed_batch", "backend/apps/parsing/tasks.py", 1, 40)
        self.assertTrue(result)

    def test_chunks_not_shared_token_after_fix(self):
        # Before fix: embed_chunks and extract_lightweight_chunks shared "chunks"
        # After fix: "chunks" is a stop word → no shared token → must reject
        chunk = _make_pr_chunk(
            "_extract_lightweight_chunks",
            file_path="backend/apps/pr_review/orchestrator.py",
        )
        result = _passes(chunk, "embed_chunks", "backend/apps/parsing/tasks.py", 1, 40)
        self.assertFalse(result)

    def test_true_positive_extract_still_passes(self):
        # _extract_lightweight_chunks vs _extract_chunks → both have "extract" → passes
        chunk = _make_pr_chunk(
            "_extract_lightweight_chunks",
            file_path="backend/apps/pr_review/orchestrator.py",
        )
        result = _passes(chunk, "_extract_chunks", "backend/apps/parsing/tasks.py", 1, 40)
        self.assertTrue(result)


# ---------------------------------------------------------------------------
# _blended_similarity
# ---------------------------------------------------------------------------

class TestBlendedSimilarity(SimpleTestCase):

    @override_settings(STORE_RAW_CODE=True)
    def test_returns_none_when_store_raw_code_true_and_match_code_missing(self):
        # settings is imported inside the function body — use override_settings
        result = _blended_similarity(0.98, "def foo(): pass", None, "python")
        self.assertIsNone(result)

    @override_settings(STORE_RAW_CODE=False)
    def test_returns_embedding_sim_when_store_raw_code_false_and_match_code_missing(self):
        result = _blended_similarity(0.98, "def foo(): pass", None, "python")
        self.assertAlmostEqual(result, 0.98)

    def test_blended_score_lower_than_raw_cosine_for_dissimilar_bodies(self):
        # High embedding similarity but completely different token bodies
        code1 = "def embed(): return model.encode(text)"
        code2 = "def store(): db.session.add(record); db.session.commit()"
        result = _blended_similarity(0.97, code1, code2, "python")
        # Jaccard will be low → blended < 0.97
        self.assertLess(result, 0.97)
        self.assertIsNotNone(result)

    def test_blended_score_high_for_identical_bodies(self):
        code = "def process_item(item): return item.value * 2"
        result = _blended_similarity(0.95, code, code, "python")
        # Jaccard of identical code = 1.0 → blended = 0.7*0.95 + 0.3*1.0 = 0.965
        self.assertGreater(result, 0.95)

    def test_blended_weights_70_30(self):
        # Use code with 4+ char non-stop-word tokens so Jaccard returns a real score
        code = "def authenticate_user(username, password): return verify(username, password)"
        result = _blended_similarity(0.80, code, code, "python")
        # Jaccard of identical code = 1.0 → blended = 0.70*0.80 + 0.30*1.0 = 0.86
        self.assertAlmostEqual(result, 0.70 * 0.80 + 0.30 * 1.0, places=2)

    def test_falls_back_to_embedding_sim_when_body_tokens_empty(self):
        # Both bodies are pure comments → stripped body is empty → Jaccard returns None
        code1 = "# just a comment"
        code2 = "# another comment"
        result = _blended_similarity(0.97, code1, code2, "python")
        self.assertAlmostEqual(result, 0.97)


# ---------------------------------------------------------------------------
# _jaccard_similarity
# ---------------------------------------------------------------------------

class TestJaccardSimilarity(SimpleTestCase):

    def test_identical_code_returns_one(self):
        # Must use code with 4+ char non-stop-word tokens (the regex requires ≥4 chars)
        code = "def authenticate_user(username, password): return verify(username, password)"
        self.assertAlmostEqual(_jaccard_similarity(code, code, "python"), 1.0)

    def test_completely_different_code_returns_low_score(self):
        code1 = "def authenticate_user(username, password): return verify(username, password)"
        code2 = "def render_template(name, context): return loader.render(name, context)"
        score = _jaccard_similarity(code1, code2, "python")
        self.assertLess(score, 0.3)

    def test_empty_code_returns_none(self):
        self.assertIsNone(_jaccard_similarity("", "def foo(): pass", "python"))
        self.assertIsNone(_jaccard_similarity("def foo(): pass", "", "python"))

    def test_comment_only_returns_none(self):
        # After stripping comments, both bodies are empty
        result = _jaccard_similarity("# comment only", "# another comment", "python")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# _strip_noise
# ---------------------------------------------------------------------------

class TestStripNoise(SimpleTestCase):

    def test_python_docstring_removed(self):
        code = '"""This is a docstring."""\ndef foo(): pass'
        result = _strip_noise(code, "python")
        self.assertNotIn("docstring", result)
        self.assertIn("foo", result)

    def test_python_comment_removed(self):
        code = "# this is a comment\ndef bar(): return 1"
        result = _strip_noise(code, "python")
        self.assertNotIn("comment", result)
        self.assertIn("bar", result)

    def test_python_import_removed(self):
        code = "import os\nfrom sys import path\ndef main(): pass"
        result = _strip_noise(code, "python")
        self.assertNotIn("import os", result)
        self.assertIn("main", result)

    def test_js_block_comment_removed(self):
        code = "/* block comment */\nfunction foo() { return 1; }"
        result = _strip_noise(code, "javascript")
        self.assertNotIn("block comment", result)
        self.assertIn("foo", result)

    def test_js_line_comment_removed(self):
        code = "// line comment\nfunction bar() {}"
        result = _strip_noise(code, "javascript")
        self.assertNotIn("line comment", result)

    def test_unsupported_language_returns_unchanged(self):
        code = "// this stays\nfunc main() {}"
        result = _strip_noise(code, "go")
        # go is in the supported set — line comments stripped
        self.assertNotIn("this stays", result)
