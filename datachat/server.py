"""Local-only UI and JSON API with request tokens and bounded analysis work."""
import csv
import io
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .data import DatasetStore
from .history import History, answer
from .planner import Planner, make_pipeline

STATIC = Path(__file__).parent / "static"
MAX_BODY = 4_000_000


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=8766, data_dir=None, planner=None):
        super().__init__(("127.0.0.1", port), Handler)
        root = Path(data_dir or os.environ.get("DATACHAT_DATA", ".datachat"))
        self.store = DatasetStore(root)
        self.history = History(root / "history.sqlite3")
        self.planner = planner or Planner()
        self.chain = make_pipeline(self.planner, self.store)
        self.token = secrets.token_urlsafe(32)
        self.work = threading.BoundedSemaphore(1)
        port = self.server_address[1]
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://{host}" for host in self.hosts}


class Handler(BaseHTTPRequestHandler):
    server_version = "DataChat/1.0"

    def log_message(self, *args):
        pass

    def reply(self, status, value, mime="application/json; charset=utf-8", download=None):
        if isinstance(value, (dict, list)):
            value = json.dumps(value, allow_nan=False).encode()
        if isinstance(value, str):
            value = value.encode()
        self.send_response(status)
        for key, content in {
            "Content-Type": mime, "Content-Length": str(len(value)), "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        }.items():
            self.send_header(key, content)
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        try:
            self.wfile.write(value)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def boundary(self, mutation=False):
        if self.headers.get("Host") not in self.server.hosts:
            self.reply(403, {"error": "Unexpected Host."})
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in self.server.origins:
            self.reply(403, {"error": "Cross-origin access is refused."})
            return False
        if mutation and not secrets.compare_digest(self.headers.get("X-DataChat-Token", ""), self.server.token):
            self.reply(403, {"error": "Reload the page to restore the local request token."})
            return False
        return True

    def do_GET(self):
        if not self.boundary():
            return
        try:
            path = urlsplit(self.path).path
            assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
            if path in assets:
                file, mime = assets[path]
                return self.reply(200, (STATIC / file).read_bytes(), mime + "; charset=utf-8")
            if path == "/api/config":
                return self.reply(200, {"token": self.server.token, "model": self.server.planner.model, "framework": "LangChain", "version": "1.0.0"})
            if path == "/api/datasets":
                return self.reply(200, self.server.store.list())
            if path == "/api/history":
                return self.reply(200, self.server.history.list())
            parts = path.split("/")
            if len(parts) == 4 and parts[1:3] == ["api", "datasets"]:
                return self.reply(200, self.server.store.get(parts[3]))
            if len(parts) in (4, 5) and parts[1:3] == ["api", "runs"]:
                run = self.server.history.get(parts[3])
                if len(parts) == 4:
                    return self.reply(200, run)
                if parts[4] == "csv":
                    return self.reply(200, export_csv(run), "text/csv; charset=utf-8", "datachat-results.csv")
                if parts[4] == "report":
                    return self.reply(200, export_report(run), "text/markdown; charset=utf-8", "datachat-report.md")
            return self.reply(404, {"error": "Not found."})
        except ValueError as exc:
            return self.reply(404, {"error": str(exc)})

    def do_POST(self):
        if not self.boundary(True):
            return
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.reply(415, {"error": "Use JSON request bodies."})
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if not 0 <= length <= MAX_BODY:
                return self.reply(413, {"error": "Request is too large. CSV files must be under 2 MB."})
            self.connection.settimeout(10)
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("JSON object required.")
        except (ValueError, TimeoutError):
            return self.reply(400, {"error": "Invalid JSON request."})
        if not self.server.work.acquire(blocking=False):
            return self.reply(429, {"error": "An analysis is running. Try again when it finishes."})
        try:
            path = urlsplit(self.path).path
            if path == "/api/demo":
                return self.reply(200, self.server.store.demo())
            if path == "/api/upload":
                return self.reply(200, self.server.store.import_csv(payload.get("csv"), payload.get("name", "Uploaded CSV")))
            if path == "/api/evaluate":
                from .evaluation import evaluate
                return self.reply(200, evaluate(self.server.store))
            if path == "/api/analyze":
                question = payload.get("question", "")
                mode = payload.get("mode", "ai")
                identifier = payload.get("dataset_id")
                dataset = self.server.store.get(identifier)
                if not isinstance(question, str) or len(question.strip()) == 0 or len(question) > 2000:
                    raise ValueError("Ask a question containing 1–2,000 characters.")
                if mode == "ai":
                    planned = self.server.chain.invoke({"dataset_id": identifier, "question": question, "history": self.server.history.context(identifier)})
                    if "clarification" in planned:
                        return self.reply(200, planned)
                elif mode == "sql":
                    sql = payload.get("sql")
                    result = self.server.store.query(identifier, sql)
                    planned = {"sql": sql, "rationale": "Executed the SQL you supplied, after the same read-only validation used for AI queries.", "chart": "bar", "result": result, "trace": [{"step": "manual", "sql": sql}]}
                elif mode == "example":
                    from .evaluation import CASES
                    example = payload.get("example_id")
                    if not isinstance(example, str):
                        raise ValueError("Choose an example.")
                    case = next((c for c in CASES if c["id"] == example), None)
                    if case is None or not dataset.get("is_demo"):
                        raise ValueError("Examples are only available on the synthetic sales dataset.")
                    question = case["question"]
                    sql = case["sql"]
                    planned = {"sql": sql, "rationale": "Prepared demo query. No AI model was called.", "chart": "line" if "month" in question.lower() and "drop" not in question.lower() else "bar", "result": self.server.store.query(identifier, sql), "trace": [{"step": "example", "sql": sql}]}
                else:
                    raise ValueError("Unknown analysis mode.")
                saved = self.server.history.save({**planned, "question": question.strip(), "dataset_id": identifier, "dataset_name": dataset["name"], "mode": mode, "answer": answer(planned["result"]), "model": self.server.planner.model if mode == "ai" else None})
                return self.reply(200, saved)
            return self.reply(404, {"error": "Not found."})
        except ValueError as exc:
            return self.reply(400, {"error": str(exc)})
        except Exception:
            return self.reply(500, {"error": "This task could not be completed. Please check your input and try again."})
        finally:
            self.server.work.release()


def export_csv(run):
    def cell(v):
        if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + v
        return v
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow([cell(v) for v in run["result"]["columns"]])
    writer.writerows([[cell(v) for v in row] for row in run["result"]["rows"]])
    return stream.getvalue()


def export_report(run):
    def safe(value):
        return str(value).replace("<", "&lt;").replace(">", "&gt;").replace("`", "\\`").replace("\n", " ")
    rows = run["result"]["rows"]
    lines = ["# DataChat analysis", "", f"Question: {safe(run['question'])}", f"Dataset: {safe(run['dataset_name'])}", f"Created: {run['created_at']}", f"Mode: {run['mode']}", "", safe(run["answer"]), "", "## Query", "", "    " + run["sql"].replace("\n", "\n    "), "", "## Returned data", "", " | ".join(safe(c).replace("|", "\\|") for c in run["result"]["columns"]), " | ".join("---" for _ in run["result"]["columns"])]
    lines.extend(" | ".join(safe(v).replace("|", "\\|") for v in row) for row in rows)
    lines.extend(["", "Results are from executed SQL. A valid query can still misunderstand a question; inspect the SQL.", "Rows were capped at 1,000." if run["result"]["truncated"] else "All returned rows are included."])
    return "\n".join(lines) + "\n"


def serve(port=8766, data_dir=None):
    server = AppServer(port, data_dir)
    print(f"DataChat ready at http://127.0.0.1:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
