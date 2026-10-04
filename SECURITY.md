# Security and privacy

DataChat is intended for one user on a trusted local machine. It is not an authenticated production server. Do not expose the port, reverse-proxy it to the internet, or use it for untrusted multi-user workloads.

## Query boundary

The AI model emits a structured plan; it is not granted filesystem, shell, network, or Python execution tools. User questions, prior questions/SQL, and CSV data are untrusted. Prompt rules help guide the model but are not the execution boundary.

SQLGlot parses a single SQLite query and restricts statement types and table references. Each query then opens a fresh SQLite connection in `mode=ro`, enables `query_only`, installs an authorizer allowing reads from only `data` and a fixed set of functions, and applies limits to execution time, expression depth, columns, and output size. Recursive CTEs, extension loading, metadata-table reads, external tables, ATTACH, and PRAGMA from model/user SQL are denied. These limits are defense in depth; SQLite progress callbacks enforce elapsed time while executing VM operations, not a hard OS process isolation boundary.

CSV ingestion uses parameterized inserts and quotes normalized identifiers. No uploaded file path is opened by the server. Dataset IDs are validated UUIDs; browser-provided paths are not accepted.

## Local HTTP boundary

The server binds only to `127.0.0.1`, validates Host and Origin, and requires a randomly generated local token for mutation requests. There is no permissive CORS. Static assets use a content security policy and DOM rendering uses text nodes for untrusted data. This does not protect against malicious software or another user already able to read this account's local files.

The local Ollama endpoint is fixed. Environment proxies and redirects are disabled. LangSmith tracing is disabled within the application process. Only question, schema identifiers/types, validation feedback, and bounded recent question/SQL context go to the local model; raw CSV cells are not put in the model prompt.

## Data retention

CSV copies are stored in local SQLite datasets. Recent analysis results and questions are stored in a local SQLite history database (latest 100 runs). Dataset files remain until you remove the chosen data directory. There is no telemetry or cloud upload. The app does not include a remote database connection feature. Do not commit `.datachat`, `.env`, credentials, or private datasets.

Exported CSV strings starting with common formula prefixes are prefixed with an apostrophe to reduce spreadsheet formula injection; numeric negative values remain numeric. Reports escape HTML from question/data text. Inspect exported artifacts before sharing them.

Please report issues privately through GitHub when available. Do not include private dataset rows or secrets in public issue reports.
