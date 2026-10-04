import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from datachat.data import DatasetStore


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = DatasetStore(Path(self.temporary.name))
        self.dataset = self.store.import_csv("Product,Units,Revenue,ZIP\nWidget,2,12.50,00123\nGadget,3,18.75,00987\nEmpty,,0,\n", "Sales")
        self.dataset_id = self.dataset["id"]

    def tearDown(self):
        self.temporary.cleanup()

    def test_inference_and_missing_values(self):
        self.assertEqual([c["type"] for c in self.dataset["columns"]], ["TEXT", "INTEGER", "REAL", "TEXT"])
        self.assertEqual(self.dataset["preview"][0]["zip"], "00123")
        self.assertIsNone(self.dataset["preview"][2]["units"])
        self.assertEqual(self.store.query(self.dataset_id, "SELECT SUM(units), ROUND(SUM(revenue), 2) FROM data")["rows"], [[5, 31.25]])

    def test_schema_contains_no_cell_values(self):
        schema = self.store.schema(self.dataset_id)
        self.assertIn('"product" TEXT', schema)
        self.assertNotIn("Widget", schema)
        self.assertEqual(self.store.get(self.dataset_id), self.dataset)
        self.assertEqual(len(self.store.list()), 1)

    def test_quoted_csv_and_header_normalization(self):
        item = self.store.import_csv('Order ID,Customer Name\n7,"Doe, Jane"\n', "Quoted")
        self.assertEqual(item["preview"], [{"order_id": 7, "customer_name": "Doe, Jane"}])

    def test_csv_rejections(self):
        for text in ["", "a,b\n", "a,\n1,2", "a,A\n1,2", "A-B,A B\n1,2", "a,b\n1", 'a,b\n"unterminated,2']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.store.import_csv(text, "Invalid")

    def test_csv_budgets(self):
        for text in ["a\n" + "x" * 4001, ",".join(f"c{i}" for i in range(41)) + "\n" + ",".join("1" for _ in range(41))]:
            with self.assertRaises(ValueError):
                self.store.import_csv(text, "Too large")
        with patch("datachat.data.MAX_ROWS", 2), self.assertRaises(ValueError):
            self.store.import_csv("a\n1\n2\n3", "Too many")
        with patch("datachat.data.MAX_CSV_BYTES", 4), self.assertRaises(ValueError):
            self.store.import_csv("a\n123", "Too large")

    def test_read_only_and_single_statement(self):
        forbidden = ["DROP TABLE data", "DELETE FROM data", "UPDATE data SET units=0", "INSERT INTO data VALUES ('x',1,1,'1')", "SELECT * FROM data; DROP TABLE data", "PRAGMA table_info(data)", "ATTACH DATABASE '/tmp/other' AS other", "SELECT * FROM sqlite_master", "SELECT * FROM main.data", "SELECT load_extension('/tmp/evil')", "SELECT readfile('/etc/passwd')", "SELECT * FROM pragma_table_info('data')", "WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x) SELECT * FROM x"]
        for sql in forbidden:
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                self.store.query(self.dataset_id, sql)
        self.assertEqual(self.store.query(self.dataset_id, "SELECT COUNT(*) FROM data")["rows"], [[3]])

    def test_cte_and_window(self):
        result = self.store.query(self.dataset_id, "WITH totals AS (SELECT product, SUM(units) AS n FROM data GROUP BY product) SELECT product, n FROM totals WHERE n > 1 ORDER BY n DESC")
        self.assertEqual(result["rows"], [["Gadget", 3], ["Widget", 2]])
        self.assertEqual(self.store.query(self.dataset_id, "SELECT row_number() OVER (ORDER BY product) FROM data")["row_count"], 3)

    def test_query_limits(self):
        with self.assertRaises(ValueError):
            self.store.query(self.dataset_id, " " * 12001)
        with patch("datachat.data.RESULT_LIMIT", 2):
            result = self.store.query(self.dataset_id, "SELECT * FROM data ORDER BY product")
            self.assertEqual(result["row_count"], 2)
            self.assertTrue(result["truncated"])
        with patch("datachat.data.QUERY_SECONDS", -1), self.assertRaisesRegex(ValueError, "budget"):
            self.store.query(self.dataset_id, "SELECT COUNT(*) FROM data a CROSS JOIN data b CROSS JOIN data c CROSS JOIN data d CROSS JOIN data e CROSS JOIN data f CROSS JOIN data g")

    def test_parameterized_ingestion(self):
        item = self.store.import_csv("name\n\"'); DROP TABLE data; --\"\n", "Injection")
        self.assertEqual(self.store.query(item["id"], "SELECT name FROM data")["rows"], [["'); DROP TABLE data; --"]])

    def test_output_byte_budget(self):
        with patch("datachat.data.RESULT_BYTES", 1000):
            result = self.store.query(self.dataset_id, "SELECT product || '" + "x" * 490 + "' FROM data ORDER BY product")
            self.assertTrue(result["truncated"])
            self.assertGreater(result["row_count"], 0)
            self.assertLess(result["row_count"], 3)

    def test_oversized_computed_value_is_rejected(self):
        with patch("datachat.data.RESULT_BYTES", 1000), self.assertRaises(ValueError):
            self.store.query(self.dataset_id, "SELECT replace('aaaaaaaaaa', 'a', '" + "x" * 200 + "')")

    def test_demo_reuse_and_name_cannot_spoof(self):
        uploaded = self.store.import_csv("a\n1", "Demo sales · Jan–Mar 2026")
        self.assertFalse(uploaded.get("is_demo", False))
        demo = self.store.demo()
        self.assertTrue(demo["is_demo"])
        self.assertEqual(self.store.demo()["id"], demo["id"])
        self.assertNotEqual(uploaded["id"], demo["id"])

    def test_name_validation(self):
        for name in [None, {}, "", " ", "x" * 121]:
            with self.assertRaises(ValueError):
                self.store.import_csv("a\n1", name)

    def test_dataset_id_validation(self):
        for value in ["../../etc", "a" * 31, "A" * 32, "f" * 32]:
            with self.assertRaises(ValueError):
                self.store.get(value)

    def test_nonfinite_and_integer_overflow_stay_text(self):
        item = self.store.import_csv("large,nan\n999999999999999999999999,NaN\n", "Limits")
        self.assertEqual([c["type"] for c in item["columns"]], ["TEXT", "TEXT"])
        self.assertIsNone(self.store.query(self.dataset_id, "SELECT 1e999")["rows"][0][0])


if __name__ == "__main__":
    unittest.main()
