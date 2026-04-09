"""
Tests for security anti-pattern detectors.

All pure logic tests — no DB, no external services, no tree-sitter.
Each detector is tested for: true positive, true negative, and
edge cases (placeholder values, comment lines, unsupported languages).
"""
from django.test import SimpleTestCase

from apps.security.detectors import (
    DangerousFunctionDetector,
    HardcodedSecretDetector,
    InsecureRandomDetector,
    SqlInjectionDetector,
)


# ---------------------------------------------------------------------------
# HardcodedSecretDetector
# ---------------------------------------------------------------------------

class TestHardcodedSecretDetector(SimpleTestCase):

    def setUp(self):
        self.detector = HardcodedSecretDetector()

    def _detect(self, content, language="python", path="config.py"):
        return self.detector.detect(path, content, language)

    def test_hardcoded_password_detected(self):
        findings = self._detect('password = "supersecret123"')
        self.assertTrue(any(f.detector == "HARDCODED_SECRET" for f in findings))

    def test_hardcoded_api_key_detected(self):
        findings = self._detect('api_key = "abcdefghijklmnop"')
        self.assertTrue(any(f.detector == "HARDCODED_SECRET" for f in findings))

    def test_hardcoded_secret_key_detected(self):
        findings = self._detect('secret_key = "my_super_secret_value"')
        self.assertTrue(any(f.detector == "HARDCODED_SECRET" for f in findings))

    def test_hardcoded_access_token_detected(self):
        findings = self._detect('access_token = "abcdefghijklmnopqrstuvwx"')
        self.assertTrue(any(f.detector == "HARDCODED_SECRET" for f in findings))

    def test_placeholder_value_not_flagged(self):
        findings = self._detect('password = "your_password_here"')
        regex_findings = [
            f for f in findings
            if f.detector == "HARDCODED_SECRET" and "password" in f.title.lower()
        ]
        self.assertEqual(len(regex_findings), 0)

    def test_change_me_placeholder_not_flagged(self):
        findings = self._detect('api_key = "change_me_in_production"')
        regex_findings = [f for f in findings if f.detector == "HARDCODED_SECRET"]
        self.assertEqual(len(regex_findings), 0)

    def test_comment_line_skipped(self):
        """Lines starting with # must not be flagged."""
        findings = self._detect('# password = "supersecret123"')
        self.assertEqual(findings, [])

    def test_env_var_lookup_not_flagged(self):
        """Reading from os.environ is safe and must not trigger."""
        findings = self._detect('password = os.environ.get("PASSWORD")')
        self.assertEqual(findings, [])

    def test_aws_access_key_detected(self):
        # Must not contain placeholder words (example, test, etc.) — they are filtered
        findings = self._detect("key = 'AKIABCDEFGHIJKLMNOP1234'")
        self.assertTrue(any(f.detector == "HARDCODED_SECRET" for f in findings))

    def test_finding_includes_line_number(self):
        content = "x = 1\npassword = 'hardcoded_secret_value'\ny = 2"
        findings = self._detect(content)
        secret_findings = [f for f in findings if f.detector == "HARDCODED_SECRET"]
        if secret_findings:
            self.assertEqual(secret_findings[0].line_number, 2)


# ---------------------------------------------------------------------------
# SqlInjectionDetector
# ---------------------------------------------------------------------------

class TestSqlInjectionDetector(SimpleTestCase):

    def setUp(self):
        self.detector = SqlInjectionDetector()

    def test_fstring_sql_detected_python(self):
        content = 'cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")'
        findings = self.detector.detect("db.py", content, "python")
        self.assertTrue(any(f.detector == "SQL_INJECTION" for f in findings))

    def test_string_concat_sql_detected_python(self):
        content = 'cursor.execute("SELECT * FROM users WHERE name = " + name)'
        findings = self.detector.detect("db.py", content, "python")
        self.assertTrue(any(f.detector == "SQL_INJECTION" for f in findings))

    def test_percent_format_sql_detected_python(self):
        content = 'cursor.execute("SELECT * FROM users WHERE id = %s" % (user_id,))'
        findings = self.detector.detect("db.py", content, "python")
        self.assertTrue(any(f.detector == "SQL_INJECTION" for f in findings))

    def test_parameterized_query_not_flagged(self):
        """Using %s with a tuple (parameterized) is safe — must not be flagged."""
        content = 'cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))'
        findings = self.detector.detect("db.py", content, "python")
        self.assertEqual(findings, [])

    def test_java_string_concat_sql_detected(self):
        content = 'stmt.executeQuery("SELECT * FROM users WHERE id = " + userId);'
        findings = self.detector.detect("Repo.java", content, "java")
        self.assertTrue(any(f.detector == "SQL_INJECTION" for f in findings))

    def test_php_variable_in_query_detected(self):
        content = '$result = mysql_query("SELECT * FROM users WHERE id = " . $_GET["id"]);'
        findings = self.detector.detect("db.php", content, "php")
        self.assertTrue(any(f.detector == "SQL_INJECTION" for f in findings))

    def test_unsupported_language_returns_empty(self):
        """Rust is not in the SQL detector's supported set."""
        content = 'let q = format!("SELECT * FROM users WHERE id = {}", id);'
        findings = self.detector.detect("main.rs", content, "rust")
        self.assertEqual(findings, [])

    def test_critical_severity_assigned(self):
        content = 'cursor.execute("SELECT * FROM users WHERE name = " + name)'
        findings = self.detector.detect("db.py", content, "python")
        sql_findings = [f for f in findings if f.detector == "SQL_INJECTION"]
        self.assertTrue(all(f.severity == "critical" for f in sql_findings))


# ---------------------------------------------------------------------------
# DangerousFunctionDetector
# ---------------------------------------------------------------------------

class TestDangerousFunctionDetector(SimpleTestCase):

    def setUp(self):
        self.detector = DangerousFunctionDetector()

    def test_eval_detected_python(self):
        findings = self.detector.detect("app.py", "result = eval(user_input)", "python")
        self.assertTrue(any("eval" in f.title.lower() for f in findings))
        self.assertTrue(any(f.severity == "critical" for f in findings))

    def test_exec_detected_python(self):
        findings = self.detector.detect("app.py", "exec(code)", "python")
        self.assertTrue(any("exec" in f.title.lower() for f in findings))

    def test_pickle_loads_detected(self):
        findings = self.detector.detect("app.py", "obj = pickle.loads(data)", "python")
        self.assertTrue(any("pickle" in f.title.lower() for f in findings))

    def test_subprocess_shell_true_detected(self):
        findings = self.detector.detect("app.py", "subprocess.run(cmd, shell=True)", "python")
        self.assertTrue(any("shell=True" in f.title for f in findings))

    def test_subprocess_shell_false_not_flagged(self):
        findings = self.detector.detect("app.py", 'subprocess.run(["ls", "-la"])', "python")
        subprocess_findings = [f for f in findings if "shell=True" in f.title]
        self.assertEqual(subprocess_findings, [])

    def test_yaml_load_without_safeloader_detected(self):
        findings = self.detector.detect("app.py", "data = yaml.load(stream)", "python")
        self.assertTrue(any("yaml" in f.title.lower() for f in findings))

    def test_eval_detected_javascript(self):
        findings = self.detector.detect("app.js", "eval(userCode);", "javascript")
        self.assertTrue(any("eval" in f.title.lower() for f in findings))

    def test_inner_html_assignment_detected(self):
        findings = self.detector.detect("app.js", "element.innerHTML = userContent;", "javascript")
        self.assertTrue(any("innerHTML" in f.title for f in findings))

    def test_new_function_detected_javascript(self):
        findings = self.detector.detect("app.js", "const f = new Function(code);", "javascript")
        self.assertTrue(any("Function" in f.title for f in findings))

    def test_finding_has_file_path(self):
        findings = self.detector.detect("src/utils.py", "eval(x)", "python")
        for f in findings:
            self.assertEqual(f.file_path, "src/utils.py")


# ---------------------------------------------------------------------------
# InsecureRandomDetector
# ---------------------------------------------------------------------------

class TestInsecureRandomDetector(SimpleTestCase):

    def setUp(self):
        self.detector = InsecureRandomDetector()

    def test_random_random_detected(self):
        content = "token = random.random()"
        findings = self.detector.detect("auth.py", content, "python")
        self.assertTrue(any(f.detector == "INSECURE_RANDOM" for f in findings))

    def test_math_random_detected_javascript(self):
        content = "const token = Math.random();"
        findings = self.detector.detect("auth.js", content, "javascript")
        self.assertTrue(any(f.detector == "INSECURE_RANDOM" for f in findings))

    def test_secrets_module_not_flagged(self):
        content = "token = secrets.token_hex(32)"
        findings = self.detector.detect("auth.py", content, "python")
        insecure = [f for f in findings if f.detector == "INSECURE_RANDOM"]
        self.assertEqual(insecure, [])

    def test_crypto_random_not_flagged_javascript(self):
        content = "const token = crypto.getRandomValues(new Uint8Array(32));"
        findings = self.detector.detect("auth.js", content, "javascript")
        insecure = [f for f in findings if f.detector == "INSECURE_RANDOM"]
        self.assertEqual(insecure, [])
