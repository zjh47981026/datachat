"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  token: "",
  datasets: [],
  dataset: null,
  run: null,
  busy: false,
};
const exampleQuestions = {
  "monthly-revenue": "Show total revenue by month, earliest first.",
  "product-revenue": "Show revenue by product, highest first.",
  "largest-drop":
    "Which product had the largest revenue drop from February to March 2026? Return product and positive revenue drop.",
};

function notice(text, error = false) {
  $("notice").textContent = text;
  $("notice").classList.toggle("error", error);
  $("notice").hidden = !text;
}

async function api(path, body) {
  const res = await fetch(
    path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-DataChat-Token": state.token,
          },
          body: JSON.stringify(body),
        },
  );
  const value = await res.json();
  if (!res.ok) throw new Error(value.error || "Request failed.");
  return value;
}

function busy(value) {
  state.busy = value;
  for (const id of [
    "ask",
    "run-sql",
    "run-manual",
    "evaluate",
    "load-demo",
    "upload-submit",
    "dataset",
  ])
    $(id).disabled = value;
  document
    .querySelectorAll("[data-example]")
    .forEach((el) => (el.disabled = value || !state.dataset?.is_demo));
  $("ask").textContent = value ? "Working…" : "Find an answer ↗";
}

async function task(action, message) {
  if (state.busy) return;
  busy(true);
  notice(message);
  try {
    await action();
  } catch (error) {
    notice(error.message, true);
  } finally {
    busy(false);
  }
}

function table(target, columns, rows) {
  target.replaceChildren();
  const grid = document.createElement("table");
  const head = grid.createTHead().insertRow();
  columns.forEach((c) => {
    const el = document.createElement("th");
    el.scope = "col";
    el.textContent = c;
    head.append(el);
  });
  const body = grid.createTBody();
  rows.forEach((row) => {
    const tr = body.insertRow();
    row.forEach((v) => {
      const cell = tr.insertCell();
      cell.textContent = v === null ? "—" : String(v);
    });
  });
  target.append(grid);
}

function selectDataset(identifier) {
  state.dataset = state.datasets.find((d) => d.id === identifier) || null;
  $("dataset").value = state.dataset?.id || "";
  state.run = null;
  $("analysis").hidden = true;
  $("empty").hidden = false;
  $("question").value = "";
  const d = state.dataset;
  $("active-name").textContent = d?.name || "No dataset selected";
  $("row-count").textContent = d ? d.rows.toLocaleString() : "—";
  $("column-count").textContent = d ? d.columns.length : "—";
  $("source-meta").textContent = d
    ? `${d.rows.toLocaleString()} records · ${d.columns.length} columns${d.is_demo ? " · synthetic" : ""}`
    : "Import a CSV to begin.";
  $("schema-note").textContent = d
    ? d.columns
        .map((c) => `${c.display_name} → ${c.name} (${c.type})`)
        .join(" · ")
    : "";
  if (d)
    table(
      $("preview-table"),
      d.columns.map((c) => c.name),
      d.preview.map((r) => d.columns.map((c) => r[c.name])),
    );
  document
    .querySelectorAll("[data-example]")
    .forEach((el) => (el.disabled = !d?.is_demo || state.busy));
  $("ask").disabled = !d || state.busy;
}

async function sources(identifier) {
  state.datasets = await api("/api/datasets");
  $("dataset").replaceChildren();
  state.datasets.forEach((d) => {
    const option = document.createElement("option");
    option.value = d.id;
    option.textContent = d.name;
    $("dataset").append(option);
  });
  selectDataset(identifier || state.datasets[0]?.id);
}

async function show(page) {
  document
    .querySelectorAll(".page")
    .forEach((el) => (el.hidden = el.id !== page));
  document
    .querySelectorAll(".nav")
    .forEach((el) => el.classList.toggle("active", el.dataset.page === page));
  $("breadcrumb").textContent = {
    workspace: "Explore",
    history: "Saved analyses",
    evaluation: "Evaluation lab",
  }[page];
  window.scrollTo({ top: 0, behavior: "instant" });
  if (page === "history") await history();
}

function render(run) {
  state.run = run;
  $("empty").hidden = true;
  $("analysis").hidden = false;
  $("result-title").textContent = run.question;
  $("mode-badge").textContent = {
    ai: "LOCAL AI · LANGCHAIN",
    sql: "YOUR SQL",
    example: "PREPARED EXAMPLE",
  }[run.mode];
  $("answer").textContent = run.answer;
  $("rationale").textContent = run.rationale;
  $("result-meta").textContent =
    `${run.dataset_name} · ${run.result.elapsed_ms} ms SQL execution · ${new Date(run.created_at).toLocaleString()}${run.model ? " · " + run.model : ""}`;
  $("sql").value = run.sql;
  $("download-csv").href = `/api/runs/${run.id}/csv`;
  $("download-report").href = `/api/runs/${run.id}/report`;
  $("returned-count").textContent =
    `${run.result.row_count.toLocaleString()} returned rows${run.result.truncated ? " · capped" : ""}`;
  table($("result-table"), run.result.columns, run.result.rows);
  $("trace").replaceChildren();
  run.trace.forEach((step) => {
    const li = document.createElement("li");
    li.textContent = `${step.step}: ${step.error || step.rationale || "query validated and executed"}`;
    $("trace").append(li);
  });
  const validNumeric = run.result.columns
    .map((_, i) =>
      run.result.rows.some((r) => typeof r[i] === "number") &&
      run.result.rows.every((r) => r[i] === null || typeof r[i] === "number")
        ? i
        : -1,
    )
    .filter((i) => i !== -1);
  for (const id of ["chart-x", "chart-y"]) {
    $(id).replaceChildren();
    run.result.columns.forEach((c, i) => {
      if (id === "chart-y" && !validNumeric.includes(i)) return;
      const op = document.createElement("option");
      op.value = i;
      op.textContent = c;
      $(id).append(op);
    });
  }
  const firstText = run.result.columns.findIndex(
    (_, i) => !validNumeric.includes(i),
  );
  $("chart-x").value = firstText >= 0 ? firstText : 0;
  $("chart-y").value =
    validNumeric.find((i) => i !== Number($("chart-x").value)) ??
    validNumeric[0] ??
    "";
  $("chart-type").value = run.chart === "line" ? "line" : "bar";
  chart();
  tab("chart");
}

function svg(tag, attrs, text) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs).forEach(([key, value]) =>
    el.setAttribute(key, String(value)),
  );
  if (text !== undefined) el.textContent = text;
  return el;
}

function chart() {
  $("chart").replaceChildren();
  if (!state.run) return;
  const result = state.run.result;
  const x = Number($("chart-x").value),
    y = Number($("chart-y").value);
  const rows = result.rows
    .filter((r) => typeof r[y] === "number" && Number.isFinite(r[y]))
    .slice(0, 20);
  if (!$("chart-y").options.length || !rows.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent =
      "No numeric series to chart. Open the table to inspect the result.";
    $("chart").append(p);
    $("chart-note").textContent = "";
    return;
  }
  const W = 540,
    H = 260,
    L = 110,
    R = 53,
    T = 15,
    B = 35;
  const node = svg("svg", {
    viewBox: `0 0 ${W} ${H}`,
    role: "img",
    "aria-label": `${result.columns[y]} by ${result.columns[x]}`,
  });
  const low = Math.min(0, ...rows.map((r) => r[y])),
    high = Math.max(0, ...rows.map((r) => r[y]));
  const range = high - low || 1;
  const formatted = (v) =>
    new Intl.NumberFormat(undefined, {
      maximumFractionDigits: 2,
      notation: Math.abs(v) >= 100000 ? "compact" : "standard",
    }).format(v);
  if ($("chart-type").value === "bar") {
    const rowH = (H - T - B) / rows.length;
    const scale = (value) => L + ((value - low) / range) * (W - L - R);
    [low, low + range / 2, high].forEach((v) => {
      node.append(
        svg("line", {
          x1: scale(v),
          x2: scale(v),
          y1: T,
          y2: H - B,
          class: "chart-grid",
        }),
      );
      node.append(
        svg(
          "text",
          {
            x: scale(v),
            y: H - 12,
            "text-anchor": "middle",
            class: "chart-axis",
          },
          formatted(v),
        ),
      );
    });
    rows.forEach((r, i) => {
      const label = String(r[x] ?? "empty");
      node.append(
        svg(
          "text",
          {
            x: L - 12,
            y: T + (i + 0.5) * rowH + 4,
            "text-anchor": "end",
            class: "chart-label",
          },
          label.length > 17 ? label.slice(0, 16) + "…" : label,
        ),
      );
      const rect = svg("rect", {
        x: Math.min(scale(0), scale(r[y])),
        y: T + i * rowH + rowH * 0.2,
        width: Math.max(1, Math.abs(scale(r[y]) - scale(0))),
        height: Math.max(2, rowH * 0.6),
        rx: 3,
        class: "chart-bar",
      });
      rect.append(svg("title", {}, `${label}: ${r[y]}`));
      node.append(rect);
      node.append(
        svg(
          "text",
          {
            x: scale(r[y]) + (r[y] < 0 ? -6 : 6),
            y: T + (i + 0.5) * rowH + 4,
            "text-anchor": r[y] < 0 ? "end" : "start",
            class: "chart-value",
          },
          formatted(r[y]),
        ),
      );
    });
  } else {
    const sx = (i) => 65 + (i * (W - 100)) / Math.max(1, rows.length - 1),
      sy = (v) => H - B - ((v - low) / range) * (H - T - B);
    [low, low + range / 2, high].forEach((v) => {
      node.append(
        svg("line", {
          x1: 65,
          x2: W - 35,
          y1: sy(v),
          y2: sy(v),
          class: "chart-grid",
        }),
      );
      node.append(
        svg(
          "text",
          { x: 53, y: sy(v) + 4, "text-anchor": "end", class: "chart-axis" },
          formatted(v),
        ),
      );
    });
    node.append(
      svg("polyline", {
        points: rows.map((r, i) => `${sx(i)},${sy(r[y])}`).join(" "),
        class: "chart-line",
      }),
    );
    rows.forEach((r, i) => {
      const point = svg("circle", {
        cx: sx(i),
        cy: sy(r[y]),
        r: 5,
        class: "chart-point",
      });
      point.append(svg("title", {}, `${r[x]}: ${r[y]}`));
      node.append(point);
      if (i % Math.max(1, Math.ceil(rows.length / 5)) === 0)
        node.append(
          svg(
            "text",
            {
              x: sx(i),
              y: H - 12,
              "text-anchor": "middle",
              class: "chart-axis",
            },
            String(r[x]).slice(0, 13),
          ),
        );
    });
  }
  $("chart").append(node);
  $("chart-note").textContent =
    `${result.columns[y]} by ${result.columns[x]} · ${rows.length} numeric rows shown${result.rows.length > 20 ? " (first 20 only)" : ""}. ${$("chart-type").value === "line" ? "Points follow the query result order." : ""}`;
}

function tab(name) {
  $("chart-content").hidden = name !== "chart";
  $("table-content").hidden = name !== "table";
  $("chart-tab").classList.toggle("selected", name === "chart");
  $("table-tab").classList.toggle("selected", name === "table");
}

async function analyze(mode = "ai", exampleId = null, manualSql = null) {
  if (!state.dataset) throw new Error("Import a CSV or load the demo first.");
  const run = await api("/api/analyze", {
    dataset_id: state.dataset.id,
    question:
      manualSql !== null
        ? "Manual SQL analysis"
        : $("question").value || "Inspect edited query",
    mode,
    sql: manualSql !== null ? manualSql : $("sql").value,
    example_id: exampleId,
  });
  if (run.clarification) {
    notice(run.clarification);
    return;
  }
  render(run);
  notice(
    mode === "ai"
      ? "Analysis complete. Inspect the SQL and the evidence."
      : mode === "example"
        ? "Prepared example complete. No AI model was called."
        : "Your SQL passed validation and ran successfully.",
  );
  $("analysis").scrollIntoView({ block: "start", behavior: "smooth" });
}

async function history() {
  const runs = await api("/api/history");
  $("history-list").replaceChildren();
  if (!runs.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent =
      "Your first analysis will appear here. Up to 100 recent runs are kept locally.";
    $("history-list").append(p);
  }
  runs.forEach((run) => {
    const card = document.createElement("article");
    card.className = "history-card";
    const info = document.createElement("div"),
      title = document.createElement("h3"),
      meta = document.createElement("p"),
      button = document.createElement("button");
    title.textContent = run.question;
    meta.textContent = `${run.dataset_name} · ${new Date(run.created_at).toLocaleString()} · ${run.mode === "ai" ? "local AI" : run.mode === "example" ? "prepared example" : "your SQL"}`;
    button.textContent = "Open ↗";
    button.addEventListener("click", () =>
      task(async () => {
        const saved = await api("/api/runs/" + run.id);
        selectDataset(saved.dataset_id);
        $("question").value = saved.question;
        await show("workspace");
        render(saved);
        notice("Opened the saved result.");
      }, "Opening analysis…"),
    );
    info.append(title, meta);
    card.append(info, button);
    $("history-list").append(card);
  });
}

async function evaluation() {
  const e = await api("/api/evaluate", {});
  $("eval-results").replaceChildren();
  const summary = document.createElement("div");
  summary.className = "eval-summary";
  [
    [`${e.passed}/${e.total}`, "SQL answer checks"],
    [`${e.safety.passed}/${e.safety.total}`, "Blocked unsafe queries"],
  ].forEach(([count, label]) => {
    const box = document.createElement("div"),
      n = document.createElement("strong"),
      p = document.createElement("p");
    n.textContent = count;
    p.textContent = label;
    box.append(n, p);
    summary.append(box);
  });
  const note = document.createElement("p");
  note.className = "tiny";
  note.textContent = e.limitations;
  const wrap = document.createElement("div");
  wrap.className = "panel table-scroll";
  table(
    wrap,
    ["Question", "Expected answer", "Returned answer", "Check"],
    e.cases.map((c) => [
      c.question,
      JSON.stringify(c.expected),
      c.error || JSON.stringify(c.actual),
      c.passed ? "Pass" : "Fail",
    ]),
  );
  $("eval-results").append(summary, note, wrap);
  notice(
    "SQL regression checks complete. These results do not measure AI accuracy.",
  );
}

document
  .querySelectorAll("[data-page]")
  .forEach((el) =>
    el.addEventListener("click", () =>
      show(el.dataset.page).catch((e) => notice(e.message, true)),
    ),
  );
$("dataset").addEventListener("change", () => {
  selectDataset($("dataset").value);
  notice("Dataset selected. Ask a new question.");
});
$("load-demo").addEventListener("click", () =>
  task(async () => {
    const d = await api("/api/demo", {});
    await sources(d.id);
    await show("workspace");
    notice("Loaded 90 synthetic sales records. Revenue is in USD.");
  }, "Loading demo…"),
);
$("show-preview").addEventListener("click", () => {
  $("preview-panel").open = !$("preview-panel").open;
});
$("ask-form").addEventListener("submit", (e) => {
  e.preventDefault();
  task(
    () => analyze(),
    "Your local model is planning a query. The query will be validated before it runs…",
  );
});
document.querySelectorAll("[data-example]").forEach((el) =>
  el.addEventListener("click", () => {
    if (state.busy) return;
    $("question").value = exampleQuestions[el.dataset.example];
    task(
      () => analyze("example", el.dataset.example),
      "Running the prepared demo query…",
    );
  }),
);
$("run-sql").addEventListener("click", () =>
  task(() => analyze("sql"), "Validating your SQL…"),
);
$("evaluate").addEventListener("click", () =>
  task(
    evaluation,
    "Checking prepared SQL against independent CSV calculations…",
  ),
);
$("chart-tab").addEventListener("click", () => tab("chart"));
$("table-tab").addEventListener("click", () => tab("table"));
["chart-x", "chart-y", "chart-type"].forEach((id) =>
  $(id).addEventListener("change", chart),
);
["add-source", "header-import"].forEach((id) =>
  $(id).addEventListener("click", () => {
    $("upload-error").textContent = "";
    $("upload-dialog").showModal();
  }),
);
$("close-upload").addEventListener("click", () => $("upload-dialog").close());
$("csv-file").addEventListener("change", () => {
  const file = $("csv-file").files[0];
  if (file)
    $("dataset-name").value = file.name.replace(/\.csv$/i, "").slice(0, 120);
});
$("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (state.busy) return;
  const file = $("csv-file").files[0];
  if (!file || file.size > 2000000) {
    $("upload-error").textContent = "Choose a CSV smaller than 2 MB.";
    return;
  }
  busy(true);
  $("upload-error").textContent = "";
  try {
    const buffer = await file.arrayBuffer();
    const text = new TextDecoder("utf-8", { fatal: true }).decode(buffer);
    const d = await api("/api/upload", {
      csv: text,
      name: $("dataset-name").value,
    });
    await sources(d.id);
    $("upload-dialog").close();
    await show("workspace");
    notice(
      "Dataset imported. Inspect the column mapping, then ask a question.",
    );
  } catch (error) {
    $("upload-error").textContent = error.message;
  } finally {
    busy(false);
  }
});

async function init() {
  const config = await api("/api/config");
  state.token = config.token;
  $("model-name").textContent = config.model + " · local Ollama";
  const datasets = await api("/api/datasets");
  if (!datasets.length) {
    await api("/api/demo", {});
  }
  await sources();
}
init().catch((error) => notice(error.message, true));

$("run-manual").addEventListener("click", () =>
  task(
    () => analyze("sql", null, $("manual-sql").value),
    "Validating your SQL…",
  ),
);
