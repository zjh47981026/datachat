"""Transparent development checks; SQL regression is not model accuracy."""

from __future__ import annotations

import csv
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any


CASES = [
    {"id": "total-revenue", "question": "What was total revenue?", "sql": "SELECT SUM(revenue) AS total_revenue FROM data", "kind": "total"},
    {"id": "monthly-revenue", "question": "Show total revenue by month, earliest first.", "sql": "SELECT substr(date,1,7) AS month, SUM(revenue) AS revenue FROM data GROUP BY month ORDER BY month", "kind": "month"},
    {"id": "product-revenue", "question": "Show revenue by product, highest first.", "sql": "SELECT product, SUM(revenue) AS revenue FROM data GROUP BY product ORDER BY revenue DESC, product", "kind": "product"},
    {"id": "regional-revenue", "question": "Show revenue by region, alphabetically.", "sql": "SELECT region, SUM(revenue) AS revenue FROM data GROUP BY region ORDER BY region", "kind": "region"},
    {"id": "order-count", "question": "How many sales records are there?", "sql": "SELECT COUNT(*) AS sales_records FROM data", "kind": "count"},
    {"id": "top-units", "question": "Which product sold the most units? Return the product and its total units.", "sql": "SELECT product, SUM(units) AS units FROM data GROUP BY product ORDER BY units DESC, product LIMIT 1", "kind": "top_units"},
    {"id": "march-regions", "question": "Show March 2026 revenue by region, alphabetically.", "sql": "SELECT region, SUM(revenue) AS revenue FROM data WHERE date >= '2026-03-01' AND date < '2026-04-01' GROUP BY region ORDER BY region", "kind": "march_region"},
    {"id": "monthly-average", "question": "Show average revenue per sales record for each month, earliest first, rounded to two decimals.", "sql": "SELECT substr(date,1,7) AS month, ROUND(AVG(revenue),2) AS average_revenue FROM data GROUP BY month ORDER BY month", "kind": "average"},
    {"id": "largest-drop", "question": "Which product had the largest revenue drop from February to March 2026? Return product and positive revenue drop.", "sql": "SELECT product, SUM(CASE WHEN date >= '2026-02-01' AND date < '2026-03-01' THEN revenue ELSE 0 END) - SUM(CASE WHEN date >= '2026-03-01' AND date < '2026-04-01' THEN revenue ELSE 0 END) AS revenue_drop FROM data GROUP BY product HAVING revenue_drop > 0 ORDER BY revenue_drop DESC, product LIMIT 1", "kind": "drop"},
    {"id": "notebook-units", "question": "How many Notebook units sold in January 2026?", "sql": "SELECT SUM(units) AS units FROM data WHERE product = 'Notebook' AND date >= '2026-01-01' AND date < '2026-02-01'", "kind": "notebook"},
]

SAFETY_CASES = [
    {"id": "delete", "sql": "DELETE FROM data"},
    {"id": "update", "sql": "UPDATE data SET revenue = 0"},
    {"id": "stacked", "sql": "SELECT * FROM data; DROP TABLE data"},
    {"id": "attach", "sql": "ATTACH DATABASE '/tmp/datachat-other.db' AS other"},
    {"id": "pragma", "sql": "PRAGMA table_info(data)"},
    {"id": "extension", "sql": "SELECT load_extension('/tmp/untrusted')"},
]


def _expected() -> dict[str, list[list[Any]]]:
    """Compute reference answers directly from CSV in Python, without SQL."""
    path = Path(__file__).parent / "fixtures" / "sales.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        records = list(csv.DictReader(handle))
    sums: dict[str, dict[str, Decimal]] = {k: defaultdict(Decimal) for k in ("month", "product", "region", "units", "march_region", "feb_product", "march_product")}
    counts: dict[str, int] = defaultdict(int)
    notebook = 0
    for row in records:
        month = row["date"][:7]
        revenue = Decimal(row["revenue"])
        for key, value in (("month", month), ("product", row["product"]), ("region", row["region"])):
            sums[key][value] += revenue
        sums["units"][row["product"]] += Decimal(row["units"])
        counts[month] += 1
        if month == "2026-03":
            sums["march_region"][row["region"]] += revenue
            sums["march_product"][row["product"]] += revenue
        if month == "2026-02":
            sums["feb_product"][row["product"]] += revenue
        if month == "2026-01" and row["product"] == "Notebook":
            notebook += int(row["units"])
    drops = [(p, v - sums["march_product"][p]) for p, v in sums["feb_product"].items() if v > sums["march_product"][p]]
    return {
        "total": [[sum(sums["month"].values())]],
        "month": [[k, v] for k, v in sorted(sums["month"].items())],
        "product": [[k, v] for k, v in sorted(sums["product"].items(), key=lambda x: (-x[1], x[0]))],
        "region": [[k, v] for k, v in sorted(sums["region"].items())],
        "count": [[len(records)]],
        "top_units": [[k, v] for k, v in sorted(sums["units"].items(), key=lambda x: (-x[1], x[0]))[:1]],
        "march_region": [[k, v] for k, v in sorted(sums["march_region"].items())],
        "average": [[k, (v / counts[k]).quantize(Decimal("0.01"))] for k, v in sorted(sums["month"].items())],
        "drop": [[k, v] for k, v in sorted(drops, key=lambda x: (-x[1], x[0]))[:1]],
        "notebook": [[notebook]],
    }


def _json_rows(rows: list[list[Any]]) -> list[list[Any]]:
    return [[float(v) if isinstance(v, Decimal) else v for v in row] for row in rows]


def _matches(actual: list[list[Any]], expected: list[list[Any]]) -> bool:
    if len(actual) != len(expected):
        return False
    for left, right in zip(actual, expected):
        if len(left) != len(right):
            return False
        for a, b in zip(left, right):
            if isinstance(b, (int, float, Decimal)):
                try:
                    if abs(Decimal(str(a)) - Decimal(str(b))) > Decimal("0.005"):
                        return False
                except Exception:
                    return False
            elif a != b:
                return False
    return True


def evaluate(store: Any, planner: Any = None) -> dict[str, Any]:
    """Run known SQL, or actually ask a supplied planner, and report modes honestly."""
    dataset = store.demo()
    dataset_id = dataset["id"]
    schema = store.schema(dataset_id)
    expected = _expected()
    cases = []
    for case in CASES:
        sql = case["sql"] if planner is None else None
        item: dict[str, Any] = {"id": case["id"], "question": case["question"], "expected": _json_rows(expected[case["kind"]]), "passed": False}
        try:
            if planner is not None:
                plan = planner.invoke(case["question"], schema)
                sql = plan["sql"] if isinstance(plan, dict) else plan.sql
            item["sql"] = sql
            result = store.query(dataset_id, sql)
            item["actual"] = result["rows"]
            item["passed"] = not result.get("truncated", False) and _matches(result["rows"], expected[case["kind"]])
        except Exception as error:
            item["error"] = str(error)[:500]
        cases.append(item)
    safety = []
    for case in SAFETY_CASES:
        item = {**case, "passed": False}
        try:
            store.query(dataset_id, case["sql"])
        except ValueError as error:
            item["passed"] = True
            item["error"] = str(error)[:300]
        except Exception as error:
            item["error"] = str(error)[:300]
        safety.append(item)
    passed = sum(item["passed"] for item in cases)
    return {
        "mode": "model" if planner is not None else "sql-regression",
        "label": "Model answer accuracy on development fixtures" if planner is not None else "SQL regression checks (not AI accuracy)",
        "dataset": "90 synthetic sales records; January–March 2026; revenue in USD",
        "limitations": "Small public development set, not held-out or production accuracy. Equivalent results must preserve requested ordering and output fields. Safety checks measure the SQL guard, not model behavior.",
        "passed": passed,
        "total": len(cases),
        "accuracy": passed / len(cases) if planner is not None else None,
        "cases": cases,
        "safety": {"passed": sum(item["passed"] for item in safety), "total": len(safety), "cases": safety},
    }
