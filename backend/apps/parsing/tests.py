"""
Tests for the language router: extension detection and skip-list logic.

No DB, no tree-sitter initialization (parsers are not tested here —
they require the grammar packages which are only in Docker).
"""
from django.test import SimpleTestCase

from apps.parsing.language_router import get_language, should_skip


class TestGetLanguage(SimpleTestCase):

    def test_python_extensions(self):
        self.assertEqual(get_language("utils.py"), "python")
        self.assertEqual(get_language("script.pyw"), "python")

    def test_javascript_extensions(self):
        self.assertEqual(get_language("app.js"), "javascript")
        self.assertEqual(get_language("App.jsx"), "javascript")
        self.assertEqual(get_language("module.mjs"), "javascript")
        self.assertEqual(get_language("module.cjs"), "javascript")

    def test_typescript_extensions(self):
        self.assertEqual(get_language("types.ts"), "typescript")
        self.assertEqual(get_language("Component.tsx"), "tsx")

    def test_java(self):
        self.assertEqual(get_language("Main.java"), "java")

    def test_go(self):
        self.assertEqual(get_language("main.go"), "go")

    def test_rust(self):
        self.assertEqual(get_language("lib.rs"), "rust")

    def test_c_and_cpp(self):
        self.assertEqual(get_language("main.c"), "c")
        self.assertEqual(get_language("header.h"), "c")
        self.assertEqual(get_language("impl.cpp"), "cpp")
        self.assertEqual(get_language("impl.cc"), "cpp")
        self.assertEqual(get_language("impl.cxx"), "cpp")
        self.assertEqual(get_language("header.hpp"), "cpp")

    def test_ruby(self):
        self.assertEqual(get_language("app.rb"), "ruby")
        self.assertEqual(get_language("task.rake"), "ruby")

    def test_php(self):
        self.assertEqual(get_language("index.php"), "php")
        self.assertEqual(get_language("page.phtml"), "php")

    def test_unsupported_returns_none(self):
        self.assertIsNone(get_language("README.md"))
        self.assertIsNone(get_language("data.json"))
        self.assertIsNone(get_language("Dockerfile"))
        self.assertIsNone(get_language("styles.css"))
        self.assertIsNone(get_language("image.png"))
        self.assertIsNone(get_language("no_extension"))

    def test_case_insensitive_extension(self):
        self.assertEqual(get_language("FILE.PY"), "python")
        self.assertEqual(get_language("App.TS"), "typescript")

    def test_path_with_directories(self):
        self.assertEqual(get_language("src/auth/utils.py"), "python")
        self.assertEqual(get_language("frontend/components/Button.tsx"), "tsx")


class TestShouldSkip(SimpleTestCase):

    # --- skip directories ---

    def test_vendor_directory_skipped(self):
        self.assertTrue(should_skip("vendor/lodash/lodash.js"))

    def test_node_modules_skipped(self):
        self.assertTrue(should_skip("node_modules/react/index.js"))

    def test_pycache_skipped(self):
        self.assertTrue(should_skip("__pycache__/views.cpython-312.pyc"))

    def test_venv_skipped(self):
        self.assertTrue(should_skip("venv/lib/python3.12/site.py"))
        self.assertTrue(should_skip(".venv/lib/python3.12/site.py"))

    def test_dist_build_skipped(self):
        self.assertTrue(should_skip("dist/bundle.js"))
        self.assertTrue(should_skip("build/output.js"))

    def test_git_directory_skipped(self):
        self.assertTrue(should_skip(".git/COMMIT_EDITMSG"))

    # --- skip patterns ---

    def test_django_migration_skipped(self):
        self.assertTrue(should_skip("apps/auth/migrations/0001_initial.py"))
        self.assertTrue(should_skip("apps/users/migrations/0023_alter_user_email.py"))

    def test_alembic_migration_skipped(self):
        self.assertTrue(should_skip("alembic/versions/abc123_add_users.py"))

    def test_minified_js_skipped(self):
        self.assertTrue(should_skip("static/bundle.min.js"))

    def test_protobuf_python_skipped(self):
        self.assertTrue(should_skip("generated/user_pb2.py"))

    def test_protobuf_go_skipped(self):
        self.assertTrue(should_skip("proto/user.pb.go"))

    def test_lock_files_skipped(self):
        self.assertTrue(should_skip("package-lock.json"))
        self.assertTrue(should_skip("yarn.lock"))
        self.assertTrue(should_skip("Gemfile.lock"))
        self.assertTrue(should_skip("Cargo.lock"))

    def test_generated_files_skipped(self):
        self.assertTrue(should_skip("src/schema.generated.ts"))
        self.assertTrue(should_skip("models.auto.py"))

    # --- normal files should NOT be skipped ---

    def test_normal_python_not_skipped(self):
        self.assertFalse(should_skip("apps/auth/views.py"))
        self.assertFalse(should_skip("backend/config/settings.py"))

    def test_normal_typescript_not_skipped(self):
        self.assertFalse(should_skip("src/components/Button.tsx"))

    def test_normal_go_not_skipped(self):
        self.assertFalse(should_skip("cmd/server/main.go"))

    # --- content-based minification check ---

    def test_minified_content_skipped(self):
        long_line = "var x=" + ("a" * 501)
        self.assertTrue(should_skip("app.js", content=long_line))

    def test_normal_content_not_skipped(self):
        content = "def hello():\n    return 'world'\n"
        self.assertFalse(should_skip("utils.py", content=content))

    def test_empty_content_not_skipped(self):
        self.assertFalse(should_skip("utils.py", content=""))

    def test_migration_in_deeper_path_skipped(self):
        """Migration pattern must match regardless of how deep the path is."""
        self.assertTrue(should_skip("backend/apps/auth/migrations/0005_auto_20230101.py"))

    def test_test_files_skipped(self):
        """Test files contain dangerous-looking fixture strings — skip to avoid false positives."""
        self.assertTrue(should_skip("apps/security/tests.py"))
        self.assertTrue(should_skip("tests.py"))
        self.assertTrue(should_skip("apps/auth/test_views.py"))
        self.assertTrue(should_skip("apps/auth/views_test.py"))
        self.assertTrue(should_skip("apps/auth/views_tests.py"))
        self.assertTrue(should_skip("backend/apps/rules/tests.py"))

    def test_jest_test_files_skipped(self):
        """Jest-style test files also skipped."""
        self.assertTrue(should_skip("src/components/Button.test.tsx"))
        self.assertTrue(should_skip("src/api/client.spec.ts"))
        self.assertTrue(should_skip("src/__tests__/utils.js"))

    def test_normal_files_with_test_in_name_not_skipped(self):
        """Files that contain 'test' in name but aren't test files must not be skipped."""
        self.assertFalse(should_skip("apps/auth/attestation.py"))
        self.assertFalse(should_skip("src/contest/views.py"))
