const controllerOrder = ["fixed", "actuated", "genetic", "hybrid"];
const controllerColors = {
  fixed: "#9d3927",
  actuated: "#d08b2e",
  genetic: "#6f5ba7",
  hybrid: "#17624d",
};
const metricColors = {
  waiting: "#c05a36",
  queue: "#d08b2e",
  throughput: "#2f7d6a",
  reward: "#4f5f9a",
};

const state = { payload: null };

document.getElementById("run-dashboard").addEventListener("click", runDashboard);
document.getElementById("open-gui-btn").addEventListener("click", openGui);

loadLatest();

async function loadLatest() {
  setStatus("Loading latest image-demo analytics...");
  try {
    const response = await fetch("/api/image-demo/latest");
    if (!response.ok) {
      throw new Error("No generated image-demo analytics found yet.");
    }
    const payload = await response.json();
    state.payload = payload;
    renderDashboard(payload);
    setStatus("Loaded the latest benchmark bundle.");
  } catch (error) {
    renderEmptyState(error.message);
    setStatus("No cached analytics yet. Run the benchmark bundle to generate the charts.");
  }
}

async function runDashboard() {
  const button = document.getElementById("run-dashboard");
  button.disabled = true;
  setStatus("Running the full SUMO image benchmark bundle. This can take a few minutes because it also generates the journal-style analysis charts.");
  try {
    const response = await fetch("/api/image-demo/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        episode_seconds: Number(document.getElementById("episode-seconds").value),
        replications: Number(document.getElementById("replications").value),
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Benchmark generation failed.");
    }
    state.payload = payload;
    renderDashboard(payload);
    setStatus("Benchmark, comparison values, and final graphs were generated successfully.");
  } catch (error) {
    setStatus(error.message || "Benchmark generation failed.");
  } finally {
    button.disabled = false;
  }
}

async function openGui() {
  setStatus("Launching the SUMO GUI for the image-based scenario...");
  try {
    const response = await fetch("/api/image-demo/open-gui", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "SUMO GUI launch failed.");
    }
    setStatus(payload.message || "SUMO GUI launched.");
  } catch (error) {
    setStatus(error.message || "SUMO GUI launch failed.");
  }
}

function renderDashboard(payload) {
  document.getElementById("scenario-name").textContent = payload?.scenario?.name || "image_interchange_peak";
  renderArtifacts(payload?.artifacts || {});
  const summaryRows = orderedRows(normalizeSummaryRows(payload?.benchmark?.summary || []));
  renderSummaryCards(payload, summaryRows);
  renderComparisonTable(summaryRows);
  drawNetwork(payload?.preview, document.getElementById("network-preview"));
  drawMetricBarChart("chart-waiting", summaryRows, "avg_waiting_time_mean", "lower");
  drawMetricBarChart("chart-queue", summaryRows, "avg_queue_length_mean", "lower");
  drawMetricBarChart("chart-throughput", summaryRows, "throughput_mean", "higher");
  drawMetricBarChart("chart-reward", summaryRows, "reward_score_mean", "higher");
  drawGroupedBenchmark("chart-grouped", summaryRows);
  drawLineChart(
    document.getElementById("chart-time-wait"),
    [
      { name: "Hybrid", color: controllerColors.hybrid, data: payload?.charts?.time_series?.hybrid || [], xKey: "time_seconds", yKey: "avg_wait" },
      { name: "Fixed", color: controllerColors.fixed, data: payload?.charts?.time_series?.fixed || [], xKey: "time_seconds", yKey: "avg_wait" },
    ],
    "Average waiting time"
  );
  drawLineChart(
    document.getElementById("chart-time-queue"),
    [
      { name: "Hybrid", color: controllerColors.hybrid, data: payload?.charts?.time_series?.hybrid || [], xKey: "time_seconds", yKey: "avg_queue" },
      { name: "Fixed", color: controllerColors.fixed, data: payload?.charts?.time_series?.fixed || [], xKey: "time_seconds", yKey: "avg_queue" },
    ],
    "Average queue length"
  );
  drawHeatmap(document.getElementById("chart-heatmap"), payload?.preview, payload?.charts?.queue_heatmap || { junctions: [] });
}

function renderEmptyState(message) {
  document.getElementById("summary-cards").innerHTML = `
    <div class="summary-card highlight">
      <span class="label">Status</span>
      <span class="value">${message}</span>
      <span class="subtext">Run the benchmark bundle once to generate controller values, plots, and website-ready analytics.</span>
    </div>`;
  document.getElementById("comparison-table").innerHTML = "<p>No results yet. Run the benchmark bundle to populate the controller table.</p>";
  [
    "network-preview",
    "chart-waiting",
    "chart-queue",
    "chart-throughput",
    "chart-reward",
    "chart-grouped",
    "chart-time-wait",
    "chart-time-queue",
    "chart-heatmap",
  ].forEach((id) => renderEmptySvg(document.getElementById(id), "No data yet"));
  document.getElementById("artifact-list").innerHTML = "";
}

function renderSummaryCards(payload, rows) {
  const host = document.getElementById("summary-cards");
  if (!rows.length) {
    host.innerHTML = "<div class='summary-card'>No benchmark summary is available yet.</div>";
    return;
  }
  const bestWait = bestBy(rows, "avg_waiting_time_mean", "lower");
  const bestReward = bestBy(rows, "reward_score_mean", "higher");
  const hybrid = rows.find((row) => row.controller === "hybrid");
  const scenario = payload?.scenario || {};
  host.innerHTML = [
    summaryCard(
      "Best Waiting Time",
      `${bestWait.controller.toUpperCase()} · ${formatNumber(bestWait.avg_waiting_time_mean)}`,
      "Lowest average waiting time in the controller benchmark.",
      bestWait.controller === "hybrid"
    ),
    summaryCard(
      "Best Reward",
      `${bestReward.controller.toUpperCase()} · ${formatNumber(bestReward.reward_score_mean)}`,
      "Positive reward score after converting the raw penalty-style reward into presentation-friendly form.",
      bestReward.controller === "hybrid"
    ),
    summaryCard(
      "Hybrid Snapshot",
      hybrid ? `${formatNumber(hybrid.throughput_mean)} throughput` : "Not available",
      hybrid
        ? `Wait ${formatNumber(hybrid.avg_waiting_time_mean)} · Queue ${formatNumber(hybrid.avg_queue_length_mean)}`
        : "Run the benchmark to inspect hybrid metrics.",
      true
    ),
    summaryCard(
      "Scenario Settings",
      `${scenario.episode_seconds || "-"}s · ${scenario.replications || "-"} reps`,
      "The full benchmark bundle also generates QAOA, horizon, scalability, and heatmap charts.",
      false
    ),
  ].join("");
}

function summaryCard(label, value, subtext, highlight) {
  return `<div class="summary-card${highlight ? " highlight" : ""}">
    <span class="label">${label}</span>
    <span class="value">${value}</span>
    <span class="subtext">${subtext}</span>
  </div>`;
}

function renderArtifacts(artifacts) {
  const host = document.getElementById("artifact-list");
  const entries = Object.entries(artifacts || {});
  if (!entries.length) {
    host.innerHTML = "";
    return;
  }
  host.innerHTML = entries
    .map(([label, path]) => `<span class="artifact-pill" title="${escapeHtml(String(path))}">${label.replaceAll("_", " ")}</span>`)
    .join("");
}

function renderComparisonTable(rows) {
  const host = document.getElementById("comparison-table");
  if (!rows.length) {
    host.innerHTML = "<p>No results yet.</p>";
    return;
  }
  const columns = [
    ["controller", "Controller"],
    ["avg_waiting_time_mean", "Wait Mean"],
    ["avg_queue_length_mean", "Queue Mean"],
    ["throughput_mean", "Throughput"],
    ["reward_score_mean", "Reward Score"],
    ["wait_ci95", "Wait CI95"],
  ];
  host.innerHTML = `
    <table>
      <thead>
        <tr>${columns.map(([, label]) => `<th>${label}</th>`).join("")}</tr>
      </thead>
      <tbody>
        ${rows
          .map(
            (row) => `<tr class="${row.controller === "hybrid" ? "highlight" : ""}">
              ${columns.map(([key]) => `<td>${formatCell(row[key], key === "controller")}</td>`).join("")}
            </tr>`
          )
          .join("")}
      </tbody>
    </table>`;
}

function drawMetricBarChart(svgId, rows, key, direction) {
  const svg = document.getElementById(svgId);
  if (!rows.length) {
    renderEmptySvg(svg, "No metric data");
    return;
  }
  const { width, height } = getSvgSize(svg);
  const margin = { top: 24, right: 20, bottom: 54, left: 62 };
  const values = rows.map((row) => Number(row[key] ?? 0));
  const chartMin = Math.min(0, ...values);
  const chartMax = Math.max(...values, 0);
  const domainSpan = Math.max(1, chartMax - chartMin);
  const baselineY = scaleValue(0, chartMin, chartMax, height - margin.bottom, margin.top);
  const chartWidth = width - margin.left - margin.right;
  const barWidth = Math.min(70, chartWidth / rows.length - 18);
  const gap = (chartWidth - barWidth * rows.length) / Math.max(1, rows.length);

  const axisLines = buildHorizontalGrid({ width, height, margin, min: chartMin, max: chartMax, ticks: 4 });
  const bars = rows
    .map((row, index) => {
      const value = Number(row[key] ?? 0);
      const x = margin.left + gap / 2 + index * (barWidth + gap);
      const valueY = scaleValue(value, chartMin, chartMax, height - margin.bottom, margin.top);
      const rectY = value >= 0 ? valueY : baselineY;
      const barHeight = Math.max(4, Math.abs(valueY - baselineY));
      const outline = row.controller === "hybrid" ? "#113a2f" : "transparent";
      const arrow = bestBy(rows, key, direction).controller === row.controller ? "★ " : "";
      const labelY = value >= 0 ? rectY - 8 : rectY + barHeight + 14;
      return `
        <g>
          <rect x="${x}" y="${rectY}" width="${barWidth}" height="${barHeight}" rx="10" fill="${controllerColors[row.controller] || "#888"}" stroke="${outline}" stroke-width="2"></rect>
          <text x="${x + barWidth / 2}" y="${labelY}" text-anchor="middle" font-size="12" fill="#26312d">${formatNumber(value)}</text>
          <text x="${x + barWidth / 2}" y="${height - 18}" text-anchor="middle" font-size="12" fill="#4d5954">${arrow}${row.controller}</text>
        </g>`;
    })
    .join("");

  svg.innerHTML = `
    ${axisLines}
    <line x1="${margin.left}" y1="${baselineY}" x2="${width - margin.right}" y2="${baselineY}" stroke="#6c756e" stroke-width="1.2"></line>
    ${bars}`;
}

function drawGroupedBenchmark(svgId, rows) {
  const svg = document.getElementById(svgId);
  if (!rows.length) {
    renderEmptySvg(svg, "No grouped benchmark data");
    return;
  }
  const metrics = [
    { key: "avg_waiting_time_mean", label: "Waiting", direction: "lower" },
    { key: "avg_queue_length_mean", label: "Queue", direction: "lower" },
    { key: "throughput_mean", label: "Throughput", direction: "higher" },
    { key: "reward_score_mean", label: "Reward Score", direction: "higher" },
  ];
  const { width, height } = getSvgSize(svg);
  const margin = { top: 34, right: 24, bottom: 62, left: 56 };
  const clusterWidth = (width - margin.left - margin.right) / metrics.length;
  const barGap = 8;
  const barWidth = Math.min(34, (clusterWidth - 18 - barGap * (rows.length - 1)) / rows.length);

  const normalized = metrics.map((metric) => {
    const values = rows.map((row) => Number(row[metric.key] ?? 0));
    const min = Math.min(...values);
    const max = Math.max(...values);
    return {
      ...metric,
      scores: rows.map((row) => {
        const value = Number(row[metric.key] ?? 0);
        if (max === min) return 100;
        return metric.direction === "lower"
          ? ((max - value) / (max - min)) * 100
          : ((value - min) / (max - min)) * 100;
      }),
    };
  });

  const grid = buildHorizontalGrid({ width, height, margin, min: 0, max: 100, ticks: 4, suffix: "%" });
  const clusters = normalized
    .map((metric, metricIndex) => {
      const clusterLeft = margin.left + metricIndex * clusterWidth + 12;
      const bars = metric.scores
        .map((score, controllerIndex) => {
          const x = clusterLeft + controllerIndex * (barWidth + barGap);
          const y = scaleValue(score, 0, 100, height - margin.bottom, margin.top);
          const barHeight = height - margin.bottom - y;
          const controller = rows[controllerIndex].controller;
          return `<rect x="${x}" y="${y}" width="${barWidth}" height="${barHeight}" rx="8" fill="${controllerColors[controller]}"></rect>`;
        })
        .join("");
      return `
        <g>
          ${bars}
          <text x="${clusterLeft + clusterWidth / 2 - 18}" y="${height - 18}" text-anchor="middle" font-size="12" fill="#4d5954">${metric.label}</text>
        </g>`;
    })
    .join("");

  const legend = rows
    .map(
      (row, index) =>
        `<g transform="translate(${margin.left + index * 130}, 14)">
          <circle cx="0" cy="0" r="5" fill="${controllerColors[row.controller]}"></circle>
          <text x="12" y="4" font-size="12" fill="#4d5954">${row.controller}</text>
        </g>`
    )
    .join("");

  svg.innerHTML = `${grid}${clusters}${legend}`;
}

function drawLineChart(svg, seriesDefs, yLabel) {
  const validSeries = seriesDefs.filter((series) => series.data && series.data.length);
  if (!validSeries.length) {
    renderEmptySvg(svg, "No time-series data");
    return;
  }
  const { width, height } = getSvgSize(svg);
  const margin = { top: 28, right: 22, bottom: 44, left: 56 };
  const xValues = validSeries.flatMap((series) => series.data.map((item) => Number(item[series.xKey] ?? 0)));
  const yValues = validSeries.flatMap((series) => series.data.map((item) => Number(item[series.yKey] ?? 0)));
  const xMin = Math.min(...xValues);
  const xMax = Math.max(...xValues, xMin + 1);
  const yMin = Math.min(0, ...yValues);
  const yMax = Math.max(...yValues, yMin + 1);
  const grid = buildHorizontalGrid({ width, height, margin, min: yMin, max: yMax, ticks: 4 });
  const verticals = buildVerticalGrid({ width, height, margin, min: xMin, max: xMax, ticks: 4 });

  const lines = validSeries
    .map((series) => {
      const points = series.data
        .map((item) => {
          const x = scaleValue(Number(item[series.xKey] ?? 0), xMin, xMax, margin.left, width - margin.right);
          const y = scaleValue(Number(item[series.yKey] ?? 0), yMin, yMax, height - margin.bottom, margin.top);
          return `${x},${y}`;
        })
        .join(" ");
      return `<polyline points="${points}" fill="none" stroke="${series.color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>`;
    })
    .join("");

  const legend = validSeries
    .map(
      (series, index) =>
        `<g transform="translate(${margin.left + index * 120}, 16)">
          <circle cx="0" cy="0" r="5" fill="${series.color}"></circle>
          <text x="12" y="4" font-size="12" fill="#4d5954">${series.name}</text>
        </g>`
    )
    .join("");

  svg.innerHTML = `
    ${grid}
    ${verticals}
    ${lines}
    ${legend}
    <text x="${margin.left}" y="${height - 8}" font-size="11" fill="#6c756e">Time (s)</text>
    <text x="${width - margin.right - 8}" y="${height - 8}" text-anchor="end" font-size="11" fill="#6c756e">${yLabel}</text>`;
}

function drawSingleSeriesLine(svg, rows, xKey, yKey, xLabel, yLabel) {
  if (!rows.length) {
    renderEmptySvg(svg, "No analysis data");
    return;
  }
  drawLineChart(svg, [{ name: yLabel, color: metricColors.reward, data: rows, xKey, yKey }], yLabel);
  const { width } = getSvgSize(svg);
  svg.innerHTML += `<text x="${width - 84}" y="20" font-size="11" fill="#6c756e">${xLabel}</text>`;
  svg.innerHTML += rows
    .map((row) => {
      const xValues = rows.map((item) => Number(item[xKey] ?? 0));
      const yValues = rows.map((item) => Number(item[yKey] ?? 0));
      const { width, height } = getSvgSize(svg);
      const margin = { top: 28, right: 22, bottom: 44, left: 56 };
      const x = scaleValue(Number(row[xKey] ?? 0), Math.min(...xValues), Math.max(...xValues, Math.min(...xValues) + 1), margin.left, width - margin.right);
      const y = scaleValue(Number(row[yKey] ?? 0), Math.min(0, ...yValues), Math.max(...yValues, Math.min(0, ...yValues) + 1), height - margin.bottom, margin.top);
      return `<text x="${x}" y="${y - 10}" text-anchor="middle" font-size="10" fill="#4d5954">${row[xKey]}</text>`;
    })
    .join("");
}

function drawScalabilityChart(svg, rows) {
  if (!rows.length) {
    renderEmptySvg(svg, "No scalability data");
    return;
  }
  drawLineChart(
    svg,
    [
      { name: "Hybrid", color: controllerColors.hybrid, data: rows.filter((row) => row.controller === "hybrid"), xKey: "junction_count", yKey: "avg_waiting_time" },
      { name: "Fixed", color: controllerColors.fixed, data: rows.filter((row) => row.controller === "fixed"), xKey: "junction_count", yKey: "avg_waiting_time" },
    ],
    "Average waiting time"
  );
}

function drawHeatmap(svg, preview, heatmap) {
  if (!preview || !heatmap?.junctions?.length) {
    renderEmptySvg(svg, "No heatmap data");
    return;
  }
  const { width, height } = getSvgSize(svg);
  const transform = buildNetworkTransform(preview, width, height, 28);
  const queues = heatmap.junctions.map((item) => Number(item.avg_queue ?? 0));
  const minQueue = Math.min(...queues);
  const maxQueue = Math.max(...queues, minQueue + 1);
  const edges = preview.edges
    .map((edge) => {
      const points = edge.shape.map((point) => `${transform.x(point.x)},${transform.y(point.y)}`).join(" ");
      return `<polyline points="${points}" fill="none" stroke="#d9d0c0" stroke-width="${Math.max(2, edge.lanes)}" stroke-linecap="round" stroke-linejoin="round"></polyline>`;
    })
    .join("");
  const nodes = heatmap.junctions
    .map((item) => {
      const intensity = (Number(item.avg_queue ?? 0) - minQueue) / Math.max(1e-6, maxQueue - minQueue);
      const color = interpolateColor("#f1d98f", "#9d3927", intensity);
      const radius = 9 + intensity * 14;
      return `
        <g>
          <circle cx="${transform.x(item.x)}" cy="${transform.y(item.y)}" r="${radius}" fill="${color}" fill-opacity="0.82" stroke="#ffffff" stroke-width="1.5"></circle>
          <text x="${transform.x(item.x) + radius + 4}" y="${transform.y(item.y) - 2}" font-size="11" fill="#37423e">${item.id} · ${formatNumber(item.avg_queue)}</text>
        </g>`;
    })
    .join("");
  svg.innerHTML = `${edges}${nodes}`;
}

function drawNetwork(preview, svg) {
  if (!preview) {
    renderEmptySvg(svg, "No network preview");
    return;
  }
  const { width, height } = getSvgSize(svg);
  const transform = buildNetworkTransform(preview, width, height, 34);
  const edges = preview.edges
    .map((edge) => {
      const points = edge.shape.map((point) => `${transform.x(point.x)},${transform.y(point.y)}`).join(" ");
      return `<polyline points="${points}" fill="none" stroke="#c9bca7" stroke-width="${Math.max(2, edge.lanes)}" stroke-linecap="round" stroke-linejoin="round"></polyline>`;
    })
    .join("");
  const nodes = preview.nodes
    .map(
      (node) => `
        <g>
          <circle cx="${transform.x(node.x)}" cy="${transform.y(node.y)}" r="7" fill="#17624d"></circle>
          <text x="${transform.x(node.x) + 10}" y="${transform.y(node.y) - 4}" font-size="11" fill="#37423e">${node.id}</text>
        </g>`
    )
    .join("");
  svg.innerHTML = `${edges}${nodes}`;
}

function buildNetworkTransform(preview, width, height, padding) {
  const bounds = preview.bounds || { min_x: 0, max_x: 1, min_y: 0, max_y: 1 };
  return {
    x(value) {
      return padding + ((value - bounds.min_x) / Math.max(1, bounds.max_x - bounds.min_x)) * (width - padding * 2);
    },
    y(value) {
      return height - padding - ((value - bounds.min_y) / Math.max(1, bounds.max_y - bounds.min_y)) * (height - padding * 2);
    },
  };
}

function buildHorizontalGrid({ width, height, margin, min, max, ticks, suffix = "" }) {
  const values = [];
  for (let index = 0; index <= ticks; index += 1) {
    values.push(min + ((max - min) * index) / ticks);
  }
  return values
    .map((value) => {
      const y = scaleValue(value, min, max, height - margin.bottom, margin.top);
      return `
        <line x1="${margin.left}" y1="${y}" x2="${width - margin.right}" y2="${y}" stroke="#ece4d8" stroke-width="1"></line>
        <text x="${margin.left - 10}" y="${y + 4}" text-anchor="end" font-size="11" fill="#6c756e">${formatNumber(value)}${suffix}</text>`;
    })
    .join("");
}

function buildVerticalGrid({ width, height, margin, min, max, ticks }) {
  const values = [];
  for (let index = 0; index <= ticks; index += 1) {
    values.push(min + ((max - min) * index) / ticks);
  }
  return values
    .map((value) => {
      const x = scaleValue(value, min, max, margin.left, width - margin.right);
      return `
        <line x1="${x}" y1="${margin.top}" x2="${x}" y2="${height - margin.bottom}" stroke="#f2ede4" stroke-width="1"></line>
        <text x="${x}" y="${height - margin.bottom + 18}" text-anchor="middle" font-size="11" fill="#6c756e">${formatNumber(value)}</text>`;
    })
    .join("");
}

function renderEmptySvg(svg, message) {
  const { width, height } = getSvgSize(svg);
  svg.innerHTML = `
    <rect x="0" y="0" width="${width}" height="${height}" fill="transparent"></rect>
    <text x="${width / 2}" y="${height / 2}" text-anchor="middle" font-size="16" fill="#6c756e">${message}</text>`;
}

function orderedRows(rows) {
  return [...rows].sort((left, right) => controllerOrder.indexOf(left.controller) - controllerOrder.indexOf(right.controller));
}

function normalizeSummaryRows(rows) {
  return rows.map((row) => {
    if (row.reward_score_mean !== undefined && row.reward_score_mean !== null) {
      return row;
    }
    const rawReward = Number(row.avg_reward_mean ?? 0);
    return {
      ...row,
      reward_score_mean: rewardScoreFromRaw(rawReward),
    };
  });
}

function rewardScoreFromRaw(rawReward) {
  const penalty = Math.max(0, -Number(rawReward || 0));
  return 100 / (1 + penalty / 1000);
}

function bestBy(rows, key, direction) {
  return [...rows].sort((left, right) => {
    const a = Number(left[key] ?? 0);
    const b = Number(right[key] ?? 0);
    return direction === "lower" ? a - b : b - a;
  })[0];
}

function scaleValue(value, domainMin, domainMax, rangeMin, rangeMax) {
  if (domainMax === domainMin) return (rangeMin + rangeMax) / 2;
  const ratio = (value - domainMin) / (domainMax - domainMin);
  return rangeMin + ratio * (rangeMax - rangeMin);
}

function getSvgSize(svg) {
  const box = svg.viewBox.baseVal;
  return { width: box.width || 600, height: box.height || 320 };
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(2);
}

function formatCell(value, isText = false) {
  if (isText) return String(value ?? "-");
  return formatNumber(value);
}

function setStatus(message) {
  document.getElementById("run-status").textContent = message;
}

function interpolateColor(start, end, amount) {
  const startRgb = hexToRgb(start);
  const endRgb = hexToRgb(end);
  const mix = (a, b) => Math.round(a + (b - a) * amount);
  return `rgb(${mix(startRgb.r, endRgb.r)}, ${mix(startRgb.g, endRgb.g)}, ${mix(startRgb.b, endRgb.b)})`;
}

function hexToRgb(hex) {
  const normalized = hex.replace("#", "");
  return {
    r: Number.parseInt(normalized.slice(0, 2), 16),
    g: Number.parseInt(normalized.slice(2, 4), 16),
    b: Number.parseInt(normalized.slice(4, 6), 16),
  };
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
