# Validation record

Verified locally on October 3, 2026 with Python 3.12.4, LangChain 1.4.3, langchain-ollama 1.1.0, SQLGlot 30.21.0, and local Ollama `qwen3:4b`.

## Automated checks

**35 tests passed.** They cover CSV types and malformed input, missing values, leading-zero identifiers, budgets, dataset IDs, parameterized ingestion, SQL write/extension/system-table refusal, CTE/window queries, output bounds, LangChain pipeline execution and bounded repair, clarification, provider failure, HTTP request boundaries, persistence, exports, and evaluation scoring.

The SQL regression benchmark passed **10/10 answer checks** and **6/6 unsafe-query rejection checks**. Reference answers are computed from the CSV in Python, separately from SQLite. This is not model accuracy.

## Actual local-model evaluation

The first complete `datachat evaluate --ai` run scored **6/10 correct answers (60%)** on the small public development set. Full queries, answers, and failures are committed in [model-evaluation.json](model-evaluation.json).

Successful first attempts: monthly revenue, product revenue, region revenue, record count, highest units by product, and March regional revenue.

Misses: empty SQL for total revenue and largest product decline; an invalid `re.venue` reference for monthly average; and `COUNT(units)` instead of `SUM(units)` for Notebook sales. The application can repair execution/validation failures once, but cannot automatically identify every semantically wrong query. The benchmark intentionally measures first attempts without that repair loop. A subsequent UI question for total revenue succeeded; it does not replace the recorded failed benchmark result.

This development set was used to build and debug the project. It is not held out, and a 60% score does not establish general performance. Local model/runtime variation can change results even at temperature zero. Do not present SQL regression results as AI accuracy.

## Interface verification

Verified prepared examples, editable SQL, standalone SQL before a first result, actual AI analysis, chart/table switching, query evidence, saved history, the evaluation dashboard, and a 390-pixel mobile viewport without page overflow. Desktop and mobile screenshots are committed. The CSV ingestion/API path is covered by integration tests; browser upload uses the native file picker.

The documented editable installation and `datachat` CLI were verified. GitHub Actions runs the model-free checks on Python 3.12 and 3.13.
