# DataChat

**Ask questions about a CSV. Inspect the SQL. Explore the answer.**

A local data analyst built with **LangChain**, **Ollama**, and **SQLite**. Upload a dataset, ask a question in plain English, and get an executed query result, an interactive chart, and downloadable evidence. No paid API key or frontend build step is required.

![DataChat workspace](docs/workspace.png)

## Try it

Requires Python 3.12+ and [Ollama](https://ollama.com/download). Install the local model:

```sh
ollama pull qwen3:4b
git clone https://github.com/zjh47981026/datachat.git
cd datachat
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
datachat serve
```

Open **http://127.0.0.1:8766**. On Windows, activate with `.venv\Scripts\activate` and use `python` to create the environment. Start the Ollama application, or run `ollama serve` if it isn't already running. The server binds to loopback only.

The included dataset contains 90 **synthetic** sales records for January–March 2026. Revenue is in USD. Try:

- “Show total revenue by month, earliest first.”
- “Which product sold the most units?”
- “Which product had the largest revenue drop from February to March 2026? Return product and positive revenue drop.”

**Find an answer** uses the local model through LangChain. **Example buttons** run prepared SQL and are clearly labeled; they work even when Ollama is unavailable. AI failures are shown, never disguised as demo answers.

## Features

- UTF-8 CSV import with header normalization, numeric type inference, null handling, and leading-zero identifier preservation.
- Natural-language SQL planning with structured outputs, clarification, and at most one validation repair.
- Read-only SQLite queries with multiple independent restrictions.
- Interactive bar/line charts and result tables; selectable grouping and numeric measure.
- Editable SQL, result CSV export, and Markdown reports.
- Persistent local history with dataset-specific question/SQL context for follow-up questions.
- A transparent evaluation lab with independent reference answers and separate SQL safety checks.
- Responsive UI, keyboard-accessible controls, no CDN scripts, and no cloud tracing.

## Where LangChain is used

This is an actual LangChain project, not a hand-written HTTP call wrapped in a framework label. [`datachat/planner.py`](datachat/planner.py) builds a `ChatPromptTemplate | ChatOllama.with_structured_output(Plan)` chain. The application composes schema lookup and guarded execution with `RunnableLambda` using LangChain Expression Language (LCEL).

```text
Question + dataset-specific context
          ↓
Schema lookup (no raw CSV cell contents)
          ↓
LangChain prompt → local ChatOllama → Pydantic Plan
          ↓
SQLGlot validation → read-only SQLite execution
          ↓                     ↘ invalid query: one bounded repair
Executed result → factual summary → chart / table / export
```

The model proposes SQL; it cannot execute arbitrary tools or Python. Result summaries are generated from executed rows so a second model cannot invent numbers. A valid query can still misunderstand your question—inspect the visible SQL. The LangChain package has LangGraph as a transitive dependency; this project focuses on LCEL rather than a custom LangGraph workflow.

## Configuration

```sh
# Use a different already-installed Ollama model:
DATACHAT_MODEL=qwen3:4b datachat serve --port 8766 --data-dir .datachat
```

The Ollama endpoint is fixed to `127.0.0.1:11434`. Redirects and environment proxies are disabled. Model calls use a 45-second network timeout; a repair may make a second call. Small models can miss complex questions. Configuration is environment-based, not an arbitrary URL field in the UI.

CSV limit: **2 MB / 20,000 rows / 40 columns / 4,000 characters per cell**. SQL limit: **12,000 characters / one statement / 2 seconds of SQLite execution**. Returned results: **1,000 rows / 1 MB**, with an explicit truncated indicator. Charts show the first 20 numeric result rows. Up to 100 analyses are kept in history. SQLite extensions, external tables, recursive CTEs, and write statements are refused. This is a local portfolio application, not a shared multi-user service.

Your uploaded datasets and history live under `.datachat/` by default and are ignored by Git. Only the synthetic fixture is committed. LangSmith/cloud tracing is disabled in this application process.

## Test and evaluate

```sh
python -m unittest discover -s tests -v
datachat evaluate > sql-regression.json
datachat evaluate --ai > model-evaluation.json
```

The default benchmark runs ten prepared SQL queries against answers computed independently in Python from the CSV, and separately checks six unsafe queries. **That is SQL regression, not AI accuracy.** `--ai` actually asks the configured local model each question and records wrong answers, invalid queries, or model failures without fallback. The model benchmark measures the planner's first attempt; the app may perform one repair. The set is small, public, and used during development, not held out.

See [validation results](docs/validation.md), [architecture](docs/architecture.md), and [security boundaries](SECURITY.md). GitHub Actions runs automated tests, JavaScript syntax validation, and the SQL regression benchmark without requiring a model server.

## Project layout

```text
datachat/
  planner.py      LangChain structured-output planning and LCEL pipeline
  data.py         CSV ingestion, SQL validation, bounded execution
  history.py      Local persistence and factual result summaries
  server.py       Loopback UI/API, request boundaries, exports
  evaluation.py   Independent reference answers and development checks
  static/         Responsive interface and interactive charts
  fixtures/       Synthetic sales data
tests/            Engine, LangChain pipeline, HTTP, and evaluation tests
docs/             Architecture, verification, and screenshots
```

MIT licensed. Built as an AI engineering portfolio project with inspectable evidence and measured limitations.
