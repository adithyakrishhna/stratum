"""
Tests for the YAML rule loader and rule evaluator.

All pure Python — no DB, no Redis, no filesystem access.
MagicMock stands in for CodeChunk ORM objects.
"""
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from apps.rules.evaluator import RuleViolationData, evaluate_chunk, evaluate_file_imports
from apps.rules.loader import _validate_and_fill_defaults


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(
    name="my_func",
    chunk_type="function",
    language="python",
    start_line=1,
    end_line=10,
    complexity=1.0,
    file_path="app.py",
):
    chunk = MagicMock()
    chunk.chunk_name = name
    chunk.chunk_type = chunk_type
    chunk.language = language
    chunk.start_line = start_line
    chunk.end_line = end_line
    chunk.complexity_score = complexity
    chunk.file_path = file_path
    return chunk


def _config(max_lines=50, max_complexity=10, forbidden=None, conventions=None):
    return {
        "rules": {
            "max_function_lines": max_lines,
            "max_complexity": max_complexity,
            "forbidden_imports": forbidden or {},
            "naming_conventions": conventions or {},
        }
    }


# ---------------------------------------------------------------------------
# Rule loader: _validate_and_fill_defaults
# ---------------------------------------------------------------------------

class TestValidateAndFillDefaults(SimpleTestCase):

    def test_empty_config_gets_all_defaults(self):
        cfg = _validate_and_fill_defaults({})
        self.assertEqual(cfg["rules"]["max_function_lines"], 50)
        self.assertEqual(cfg["rules"]["max_complexity"], 10)
        self.assertEqual(cfg["rules"]["forbidden_imports"], {})
        self.assertEqual(cfg["rules"]["naming_conventions"], {})
        self.assertAlmostEqual(cfg["scoring_weights"]["complexity"], 0.3)

    def test_custom_values_preserved(self):
        cfg = _validate_and_fill_defaults({
            "rules": {"max_function_lines": 30, "max_complexity": 5}
        })
        self.assertEqual(cfg["rules"]["max_function_lines"], 30)
        self.assertEqual(cfg["rules"]["max_complexity"], 5)

    def test_invalid_string_int_falls_back_to_default(self):
        cfg = _validate_and_fill_defaults({
            "rules": {"max_function_lines": "not-a-number"}
        })
        self.assertEqual(cfg["rules"]["max_function_lines"], 50)

    def test_zero_value_clamped_to_minimum_one(self):
        cfg = _validate_and_fill_defaults({
            "rules": {"max_function_lines": 0, "max_complexity": -5}
        })
        self.assertEqual(cfg["rules"]["max_function_lines"], 1)
        self.assertEqual(cfg["rules"]["max_complexity"], 1)

    def test_float_weight_above_one_falls_back(self):
        cfg = _validate_and_fill_defaults({
            "scoring_weights": {"complexity": 1.5}
        })
        self.assertAlmostEqual(cfg["scoring_weights"]["complexity"], 0.3)

    def test_float_weight_below_zero_falls_back(self):
        cfg = _validate_and_fill_defaults({
            "scoring_weights": {"complexity": -0.1}
        })
        self.assertAlmostEqual(cfg["scoring_weights"]["complexity"], 0.3)

    def test_valid_float_weight_preserved(self):
        cfg = _validate_and_fill_defaults({
            "scoring_weights": {"complexity": 0.5}
        })
        self.assertAlmostEqual(cfg["scoring_weights"]["complexity"], 0.5)

    def test_forbidden_imports_list_preserved(self):
        cfg = _validate_and_fill_defaults({
            "rules": {"forbidden_imports": {"python": ["pickle", "shelve"]}}
        })
        self.assertEqual(cfg["rules"]["forbidden_imports"]["python"], ["pickle", "shelve"])

    def test_forbidden_imports_not_a_dict_becomes_empty(self):
        cfg = _validate_and_fill_defaults({
            "rules": {"forbidden_imports": "bad-value"}
        })
        self.assertEqual(cfg["rules"]["forbidden_imports"], {})

    def test_naming_conventions_preserved(self):
        cfg = _validate_and_fill_defaults({
            "rules": {"naming_conventions": {"python": "snake_case", "java": "camelCase"}}
        })
        self.assertEqual(cfg["rules"]["naming_conventions"]["python"], "snake_case")
        self.assertEqual(cfg["rules"]["naming_conventions"]["java"], "camelCase")

    def test_none_values_fall_back_to_defaults(self):
        cfg = _validate_and_fill_defaults({
            "rules": {"max_function_lines": None, "max_complexity": None}
        })
        self.assertEqual(cfg["rules"]["max_function_lines"], 50)
        self.assertEqual(cfg["rules"]["max_complexity"], 10)


# ---------------------------------------------------------------------------
# Rule evaluator: evaluate_chunk
# ---------------------------------------------------------------------------

class TestEvaluateChunkFunctionLength(SimpleTestCase):

    def test_clean_short_function_no_violations(self):
        chunk = _make_chunk(start_line=1, end_line=20)
        self.assertEqual(evaluate_chunk(chunk, _config(max_lines=50)), [])

    def test_function_exactly_at_limit_no_violation(self):
        chunk = _make_chunk(start_line=1, end_line=50)
        self.assertEqual(evaluate_chunk(chunk, _config(max_lines=50)), [])

    def test_function_one_over_limit_triggers_violation(self):
        chunk = _make_chunk(start_line=1, end_line=51)
        violations = evaluate_chunk(chunk, _config(max_lines=50))
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_name, "MAX_FUNCTION_LINES")
        self.assertEqual(violations[0].severity, "medium")

    def test_class_chunk_skips_length_check(self):
        chunk = _make_chunk(chunk_type="class", start_line=1, end_line=300)
        self.assertEqual(evaluate_chunk(chunk, _config(max_lines=50)), [])

    def test_module_chunk_skips_length_check(self):
        chunk = _make_chunk(chunk_type="module", start_line=1, end_line=999)
        self.assertEqual(evaluate_chunk(chunk, _config(max_lines=50)), [])


class TestEvaluateChunkComplexity(SimpleTestCase):

    def test_clean_complexity_no_violations(self):
        chunk = _make_chunk(complexity=5.0)
        self.assertEqual(evaluate_chunk(chunk, _config(max_complexity=10)), [])

    def test_complexity_exactly_at_limit_no_violation(self):
        chunk = _make_chunk(complexity=10.0)
        self.assertEqual(evaluate_chunk(chunk, _config(max_complexity=10)), [])

    def test_complexity_one_over_limit_medium_severity(self):
        chunk = _make_chunk(complexity=11.0)
        violations = evaluate_chunk(chunk, _config(max_complexity=10))
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_name, "MAX_COMPLEXITY")
        self.assertEqual(violations[0].severity, "medium")

    def test_complexity_double_limit_is_high_severity(self):
        """Score > 2× the limit escalates to high severity."""
        chunk = _make_chunk(complexity=21.0)
        violations = evaluate_chunk(chunk, _config(max_complexity=10))
        severity_list = [v.severity for v in violations if v.rule_name == "MAX_COMPLEXITY"]
        self.assertEqual(severity_list, ["high"])

    def test_non_function_chunk_skips_complexity_check(self):
        chunk = _make_chunk(chunk_type="class", complexity=100.0)
        self.assertEqual(evaluate_chunk(chunk, _config(max_complexity=10)), [])


class TestEvaluateChunkNaming(SimpleTestCase):

    def test_snake_case_compliant_name_passes(self):
        chunk = _make_chunk(name="my_function", language="python")
        violations = evaluate_chunk(chunk, _config(conventions={"python": "snake_case"}))
        self.assertEqual(violations, [])

    def test_camel_case_name_violates_snake_case(self):
        chunk = _make_chunk(name="myFunction", language="python")
        violations = evaluate_chunk(chunk, _config(conventions={"python": "snake_case"}))
        names = [v.rule_name for v in violations]
        self.assertIn("NAMING_CONVENTION", names)

    def test_pascal_case_name_violates_snake_case(self):
        chunk = _make_chunk(name="MyFunction", language="python")
        violations = evaluate_chunk(chunk, _config(conventions={"python": "snake_case"}))
        names = [v.rule_name for v in violations]
        self.assertIn("NAMING_CONVENTION", names)

    def test_camelcase_convention_compliant(self):
        chunk = _make_chunk(name="myMethod", language="java")
        violations = evaluate_chunk(chunk, _config(conventions={"java": "camelCase"}))
        self.assertEqual(violations, [])

    def test_camelcase_convention_violation(self):
        chunk = _make_chunk(name="my_method", language="java")
        violations = evaluate_chunk(chunk, _config(conventions={"java": "camelCase"}))
        names = [v.rule_name for v in violations]
        self.assertIn("NAMING_CONVENTION", names)

    def test_dunder_method_skips_naming_check(self):
        for dunder in ("__init__", "__str__", "__repr__", "__len__"):
            chunk = _make_chunk(name=dunder, language="python")
            violations = evaluate_chunk(chunk, _config(conventions={"python": "snake_case"}))
            self.assertEqual(violations, [], f"Dunder {dunder!r} should not be flagged")

    def test_no_convention_for_language_no_violation(self):
        chunk = _make_chunk(name="BadName", language="go")
        violations = evaluate_chunk(chunk, _config(conventions={"python": "snake_case"}))
        self.assertEqual(violations, [])

    def test_unknown_convention_name_no_violation(self):
        """Unknown convention key must not raise — just silently pass."""
        chunk = _make_chunk(name="anything", language="python")
        violations = evaluate_chunk(chunk, _config(conventions={"python": "unknown_style"}))
        self.assertEqual(violations, [])


# ---------------------------------------------------------------------------
# Rule evaluator: evaluate_file_imports
# ---------------------------------------------------------------------------

class TestEvaluateFileImports(SimpleTestCase):

    def test_forbidden_python_import_detected(self):
        content = "import pickle\n\ndef foo(): pass\n"
        violations = evaluate_file_imports(
            "app.py", content, "python",
            _config(forbidden={"python": ["pickle"]}),
        )
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_name, "FORBIDDEN_IMPORT")
        self.assertEqual(violations[0].severity, "high")
        self.assertEqual(violations[0].line_number, 1)

    def test_forbidden_python_from_import_detected(self):
        content = "from pickle import loads\n"
        violations = evaluate_file_imports(
            "app.py", content, "python",
            _config(forbidden={"python": ["pickle"]}),
        )
        self.assertEqual(len(violations), 1)

    def test_allowed_import_not_flagged(self):
        content = "import os\nimport sys\n"
        violations = evaluate_file_imports(
            "app.py", content, "python",
            _config(forbidden={"python": ["pickle"]}),
        )
        self.assertEqual(violations, [])

    def test_no_forbidden_list_for_language_no_violation(self):
        content = "import pickle\n"
        violations = evaluate_file_imports(
            "app.py", content, "python",
            _config(forbidden={"javascript": ["eval"]}),
        )
        self.assertEqual(violations, [])

    def test_forbidden_submodule_detected(self):
        """pickle.loads should be flagged when pickle is forbidden."""
        content = "import pickle.loads\n"
        violations = evaluate_file_imports(
            "app.py", content, "python",
            _config(forbidden={"python": ["pickle"]}),
        )
        self.assertEqual(len(violations), 1)

    def test_javascript_forbidden_import_detected(self):
        content = 'import "dangerous-pkg";\nconst x = 1;\n'
        violations = evaluate_file_imports(
            "app.js", content, "javascript",
            _config(forbidden={"javascript": ["dangerous-pkg"]}),
        )
        self.assertEqual(len(violations), 1)

    def test_java_forbidden_import_detected(self):
        content = "import java.io.ObjectInputStream;\npublic class Foo {}\n"
        violations = evaluate_file_imports(
            "Foo.java", content, "java",
            _config(forbidden={"java": ["java.io.ObjectInputStream"]}),
        )
        self.assertEqual(len(violations), 1)

    def test_duplicate_import_on_same_line_counted_once(self):
        """The same (package, line) pair must not produce duplicate violations."""
        content = "import pickle\n"
        violations = evaluate_file_imports(
            "app.py", content, "python",
            _config(forbidden={"python": ["pickle"]}),
        )
        self.assertEqual(len(violations), 1)
