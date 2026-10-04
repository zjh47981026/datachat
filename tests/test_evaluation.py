import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from datachat.data import DatasetStore
from datachat.evaluation import CASES, _expected, _matches, evaluate


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = DatasetStore(Path(self.directory.name))

    def test_reference_answers_and_sql_regression_are_distinct_from_ai(self):
        result = evaluate(self.store)
        self.assertEqual(result["mode"], "sql-regression")
        self.assertIsNone(result["accuracy"])
        self.assertEqual(result["passed"], 10, result["cases"])
        self.assertEqual(result["safety"]["passed"], 6, result["safety"])
        reference = _expected()
        self.assertEqual(reference["total"], [[65400]])
        self.assertEqual(reference["count"], [[90]])
        self.assertEqual(reference["drop"], [["Notebook", 1000]])
        self.assertEqual(reference["month"], [["2026-01", 19800], ["2026-02", 21600], ["2026-03", 24000]])

    def test_model_evaluation_invokes_planner_and_checks_executed_answers(self):
        queries = {case["question"]: case["sql"] for case in CASES}
        calls = []

        class Planner:
            def invoke(self, question, schema):
                calls.append(question)
                if "CREATE TABLE data" not in schema:
                    raise AssertionError("Planner needs actual schema")
                return SimpleNamespace(sql=queries[question])

        result = evaluate(self.store, Planner())
        self.assertEqual(result["mode"], "model")
        self.assertEqual(result["accuracy"], 1.0)
        self.assertEqual(len(calls), 10)

    def test_incorrect_model_answers_never_fall_back_to_reference_sql(self):
        class Planner:
            def invoke(self, question, schema):
                return {"sql": "SELECT 0 AS incorrect"}

        result = evaluate(self.store, Planner())
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["accuracy"], 0)
        self.assertTrue(all(case["actual"] == [[0]] for case in result["cases"]))

    def test_unavailable_model_counts_failed_cases(self):
        class Planner:
            def invoke(self, question, schema):
                raise ValueError("Model unavailable")

        result = evaluate(self.store, Planner())
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["accuracy"], 0)
        self.assertTrue(all(case["error"] == "Model unavailable" for case in result["cases"]))
        self.assertEqual(result["safety"]["passed"], 6)

    def test_comparison_checks_shape_order_and_numeric_tolerance(self):
        self.assertTrue(_matches([["A", 100.001]], [["A", 100]]))
        self.assertFalse(_matches([["A", 100.1]], [["A", 100]]))
        self.assertFalse(_matches([["A", 100], ["B", 50]], [["B", 50], ["A", 100]]))
        self.assertFalse(_matches([[100, "extra"]], [[100]]))


if __name__ == "__main__":
    unittest.main()
