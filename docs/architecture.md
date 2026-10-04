# Architecture

DataChat separates the model's interpretation from database authority and result rendering.

1. A UTF-8 CSV becomes a dedicated SQLite `data` table plus metadata. Column names normalize to safe identifiers. Every nonblank value participates in type inference; leading-zero identifiers stay text. Mixed numeric/text columns stay text.
2. The browser selects an opaque dataset ID. The server provides the trusted schema and at most 8,000 characters of recent questions/SQL from that dataset to the planner.
3. LangChain's `ChatPromptTemplate` and `ChatOllama.with_structured_output(Plan, method="json_schema")` produce a Pydantic plan containing SQL, methodology, an optional clarification, and a chart preference. Raw dataset cell contents are omitted.
4. LCEL `RunnableLambda` stages run schema lookup and bounded query execution. A clarification exits without running SQL. A validation failure can trigger one additional model plan; repeated failure returns a visible error.
5. The data engine validates SQL with SQLGlot, then executes the original statement on a fresh read-only SQLite connection with an authorizer. Parsing alone is not trusted. Time, expression, function, table, and result limits apply independently.
6. History persists SQL, exact returned results, trace, model/mode, and timestamp. A deterministic summary references those rows. Browser charts use numeric returned columns; no model-generated chart code is executed.

The stdlib threaded HTTP server permits one analysis/import task at a time. No cloud AI, database credentials, JavaScript build chain, or CDN is required. UI assets are served locally. Model evaluation is an explicit CLI action; ordinary CI never calls Ollama.

## Tradeoffs and limits

- This is a local single-user project, not a multi-tenant service. SQLite data files and results are not encrypted at rest by the application.
- CSV import supports one table per dataset, not relational joins across uploaded datasets. Dates remain ISO-style text; quoted numeric/currency strings are not cleaned automatically.
- Asking for categorical values the schema cannot reveal may require exact spelling or a manual data preview. Omitting raw cell values limits prompt injection exposure and improves privacy but sacrifices some model context.
- Follow-up context includes previous questions and SQL, not guaranteed semantic memory. Check filters and grouping carefully.
- A network timeout is bounded per call; there is at most one query repair. Structured outputs validate shape, not analytical correctness.
- Chart selection is based on numeric result columns. Line order follows SQL order; first 20 rows are shown. Null numeric entries are omitted from the chart and remain visible in the table.
- The small synthetic development benchmark can catch regressions but cannot establish production accuracy. Its independent Python reference answers verify returned values rather than SQL text equality.

## Primary implementation references

- [LangChain ChatOllama integration](https://docs.langchain.com/oss/python/integrations/chat/ollama)
- [LangChain Runnable API](https://reference.langchain.com/python/langchain_core/runnables/)
- [SQLite authorizer](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.set_authorizer)
- [SQLGlot](https://github.com/tobymao/sqlglot)
