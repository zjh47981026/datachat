"""Bounded CSV ingestion and defense-in-depth, read-only SQLite execution."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import quote

import sqlglot
from sqlglot import exp

MAX_CSV_BYTES = 2_000_000
MAX_ROWS = 20_000
MAX_COLUMNS = 40
RESULT_LIMIT = 1000
RESULT_BYTES = 1_000_000
QUERY_SECONDS = 2.0
SAFE_FUNCTIONS = frozenset("abs avg count min max sum total round coalesce ifnull nullif iif lower upper length substr substring trim ltrim rtrim replace instr unicode char hex typeof date time datetime julianday strftime unixepoch timediff ceiling ceil floor sqrt pow power mod sign concat concat_ws group_concat string_agg json_extract json_array_length row_number rank dense_rank percent_rank cume_dist ntile lag lead first_value last_value nth_value like glob".split())


def _identifier(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not value:
        raise ValueError("Each column header must contain an ASCII letter or number.")
    return "c_" + value if value[0].isdigit() else value


def _quoted(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _infer(values: list[str | None]) -> tuple[str, list]:
    present = [v for v in values if v is not None]
    # Identifiers such as postal codes must retain their leading zeros.
    if not present or any(re.fullmatch(r"[+-]?0\d+(?:\.\d+)?", v.strip()) for v in present):
        return "TEXT", values
    if all(re.fullmatch(r"[+-]?\d+", v.strip()) for v in present):
        converted = [int(v) if v is not None else None for v in values]
        if all(v is None or -(2**63) <= v < 2**63 for v in converted):
            return "INTEGER", converted
        return "TEXT", values
    try:
        converted = [float(v) if v is not None else None for v in values]
        if all(v is None or math.isfinite(v) for v in converted):
            return "REAL", converted
    except (ValueError, OverflowError):
        pass
    return "TEXT", values


class DatasetStore:
    def __init__(self, root: Path):
        self.root = Path(root) / "datasets"
        self.root.mkdir(parents=True, exist_ok=True)
        self._demo_lock = threading.Lock()

    def _path(self, dataset_id: str) -> Path:
        if not isinstance(dataset_id, str) or not re.fullmatch(r"[0-9a-f]{32}", dataset_id):
            raise ValueError("Invalid dataset ID.")
        path = self.root / dataset_id
        if not (path / "metadata.json").is_file():
            raise ValueError("Dataset was not found.")
        return path

    def import_csv(self, text: str, name: str) -> dict:
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError("Dataset name must contain 1–120 characters.")
        if not isinstance(text, str):
            raise ValueError("CSV content must be text.")
        try:
            size = len(text.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ValueError("CSV must contain valid UTF-8 text.") from exc
        if size > MAX_CSV_BYTES:
            raise ValueError("CSV exceeds the 2 MB limit.")
        reader = csv.reader(io.StringIO(text.lstrip("\ufeff"), newline=""), strict=True)
        try:
            headers = next(reader, [])
            if not headers or any(not h.strip() for h in headers):
                raise ValueError("CSV needs non-empty column headers.")
            if len(headers) > MAX_COLUMNS:
                raise ValueError("CSV exceeds the 40-column limit.")
            if len({h.strip().casefold() for h in headers}) != len(headers):
                raise ValueError("Column headers must be unique, ignoring case.")
            names = [_identifier(h.strip()) for h in headers]
            if len(set(names)) != len(names):
                raise ValueError("Column headers collide after normalization; rename them.")
            rows = []
            for row in reader:
                if not row:  # Empty physical lines carry no data.
                    continue
                if len(row) != len(headers):
                    raise ValueError(f"CSV row {reader.line_num} has a different number of columns.")
                if any(len(value) > 4000 for value in row):
                    raise ValueError("CSV cells must be at most 4,000 characters.")
                rows.append([v if v.strip() else None for v in row])
                if len(rows) > MAX_ROWS:
                    raise ValueError("CSV exceeds the 20,000-row limit.")
        except csv.Error as exc:
            raise ValueError(f"Invalid CSV: {exc}") from exc
        if not rows:
            raise ValueError("CSV needs at least one data row.")
        typed = [_infer([row[i] for row in rows]) for i in range(len(headers))]
        columns = [{"name": n, "display_name": h.strip(), "type": typed[i][0]} for i, (n, h) in enumerate(zip(names, headers))]
        converted = list(zip(*(entry[1] for entry in typed)))
        dataset_id = uuid.uuid4().hex
        path = self.root / dataset_id
        path.mkdir()
        try:
            with sqlite3.connect(path / "data.sqlite3") as connection:
                declarations = ", ".join(f"{_quoted(c['name'])} {c['type']}" for c in columns)
                connection.execute(f"CREATE TABLE data ({declarations})")
                connection.executemany(f"INSERT INTO data VALUES ({','.join('?' for _ in columns)})", converted)
            metadata = {"id": dataset_id, "name": name.strip(), "rows": len(rows), "columns": columns,
                        "preview": [dict(zip(names, row)) for row in converted[:10]]}
            temporary = path / "metadata.tmp"
            temporary.write_text(json.dumps(metadata, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            temporary.replace(path / "metadata.json")
            return metadata
        except Exception:
            for child in path.iterdir():
                child.unlink()
            path.rmdir()
            raise

    def demo(self) -> dict:
        with self._demo_lock:
            return self._demo()

    def _demo(self) -> dict:
        text = (Path(__file__).parent / "fixtures" / "sales.csv").read_text(encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        for dataset in self.list():
            if dataset.get("is_demo") is True and dataset.get("demo_digest") == digest:
                return dataset
        metadata = self.import_csv(text, "Demo sales · Jan–Mar 2026")
        metadata.update(is_demo=True, demo_digest=digest)
        path = self._path(metadata["id"])
        temporary = path / "metadata.tmp"
        temporary.write_text(json.dumps(metadata, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temporary.replace(path / "metadata.json")
        return metadata

    def get(self, dataset_id: str) -> dict:
        return json.loads((self._path(dataset_id) / "metadata.json").read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        return [self.get(path.name) for path in sorted(self.root.iterdir()) if re.fullmatch(r"[0-9a-f]{32}", path.name) and (path / "metadata.json").is_file()]

    def schema(self, dataset_id: str) -> str:
        columns = self.get(dataset_id)["columns"]
        return "CREATE TABLE data (" + ", ".join(f"{_quoted(c['name'])} {c['type']}" for c in columns) + ");"

    def query(self, dataset_id: str, sql: str) -> dict:
        path = self._path(dataset_id)
        if not isinstance(sql, str) or not sql.strip() or len(sql) > 12_000:
            raise ValueError("Enter one SELECT query, no longer than 12,000 characters.")
        try:
            statements = sqlglot.parse(sql, read="sqlite")
        except (sqlglot.errors.SqlglotError, RecursionError) as exc:
            raise ValueError("SQL could not be parsed as a SQLite SELECT query.") from exc
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union, exp.Intersect, exp.Except)):
            raise ValueError("Only one read-only SELECT query is allowed.")
        tree = statements[0]
        if any(isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Command, exp.Pragma, exp.Attach)) for node in tree.walk()):
            raise ValueError("Only read-only SELECT queries are allowed.")
        if any(node.args.get("recursive") for node in tree.find_all(exp.With)):
            raise ValueError("Recursive queries are not supported.")
        aliases = {cte.alias_or_name.casefold() for cte in tree.find_all(exp.CTE)}
        for table in tree.find_all(exp.Table):
            if table.db or table.catalog or not isinstance(table.this, exp.Identifier) or table.name.casefold() not in ({"data"} | aliases):
                raise ValueError("Queries can only read the uploaded data table and query-local CTEs.")
        started = time.monotonic()

        def authorize(action, arg1, arg2, db, source):
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ and arg1 == "data" and db in ("main", None):
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION and str(arg2 or arg1).lower() in SAFE_FUNCTIONS:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        uri = "file:" + quote(str((path / "data.sqlite3").resolve()), safe="/") + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=1)
        try:
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, RESULT_BYTES)
            connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 100)
            connection.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 100)
            connection.execute("PRAGMA query_only = ON")
            connection.set_authorizer(authorize)
            connection.set_progress_handler(lambda: int(time.monotonic() - started > QUERY_SECONDS), 1000)
            cursor = connection.execute(sql)
            columns = [item[0] for item in cursor.description]
            rows = []
            result_bytes = 0
            truncated = False
            for row in cursor:
                if len(rows) == RESULT_LIMIT:
                    truncated = True
                    break
                row = [None if isinstance(value, float) and not math.isfinite(value) else value for value in row]
                if any(isinstance(value, bytes) for value in row):
                    raise ValueError("Binary query results are not supported.")
                result_bytes += len(json.dumps(row, ensure_ascii=False, allow_nan=False).encode("utf-8"))
                if result_bytes > RESULT_BYTES:
                    if not rows:
                        raise ValueError("A result row exceeds the 1 MB output budget.")
                    truncated = True
                    break
                rows.append(row)
            return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated, "elapsed_ms": round((time.monotonic() - started) * 1000, 2)}
        except sqlite3.Error as exc:
            if "interrupted" in str(exc).lower():
                raise ValueError("Query exceeded the 2-second execution budget.") from exc
            raise ValueError(f"Query rejected: {exc}") from exc
        finally:
            connection.close()
