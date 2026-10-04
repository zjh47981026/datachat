"""Bounded local query history. Each operation owns its SQLite connection."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone


class History:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, dataset_id TEXT, created_at TEXT, payload TEXT)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def save(self, payload):
        value = {**payload, "id": uuid.uuid4().hex, "created_at": datetime.now(timezone.utc).isoformat()}
        with self.connect() as con:
            con.execute("INSERT INTO runs VALUES (?,?,?,?)", (value["id"], value["dataset_id"], value["created_at"], json.dumps(value, allow_nan=False)))
            con.execute("DELETE FROM runs WHERE id NOT IN (SELECT id FROM runs ORDER BY created_at DESC LIMIT 100)")
        return value

    def get(self, identifier):
        if not isinstance(identifier, str):
            raise ValueError("Run ID must be a string.")
        with self.connect() as con:
            row = con.execute("SELECT payload FROM runs WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise ValueError("Analysis not found.")
        return json.loads(row[0])

    def list(self, dataset_id=None):
        with self.connect() as con:
            rows = con.execute("SELECT payload FROM runs ORDER BY created_at DESC LIMIT 100").fetchall()
        values = [json.loads(r[0]) for r in rows]
        return [{k: v[k] for k in ("id", "dataset_id", "dataset_name", "question", "created_at", "mode")} for v in values if dataset_id is None or v["dataset_id"] == dataset_id]

    def context(self, dataset_id):
        values = self.list(dataset_id)[:3]
        return json.dumps([{ "question": v["question"], "sql": self.get(v["id"])["sql"]} for v in reversed(values)])


def answer(result):
    """A factual summary directly from executed rows; no second model invents facts."""
    rows, cols = result["rows"], result["columns"]
    if not rows:
        return "No rows matched this query. Check the filters or try a broader question."
    if len(rows) == 1:
        return "; ".join(f"{col.replace('_', ' ')}: {value if value is not None else 'empty'}" for col, value in zip(cols, rows[0])) + "."
    first = "; ".join(f"{col.replace('_', ' ')}: {value if value is not None else 'empty'}" for col, value in zip(cols, rows[0]))
    return f"Returned {len(rows):,} rows{' (display limit reached)' if result['truncated'] else ''}. First row — {first}. See the chart and table for the full returned result."
