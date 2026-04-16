const STORAGE_KEY = "traffic_quantum_dashboard_state";
const state = { polygon: null, runId: null, preview: null, trace: null, selectedNode: null };

const map = L.map("map").setView([13.0827, 80.2707], 13);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  crossOrigin: "anonymous",
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

const drawnItems = new L.FeatureGroup();
map.addLayer(drawnItems);
map.addControl(
  new L.Control.Draw({
    draw: { polyline: false, circle: false, circlemarker: false, marker: false },
    edit: { featureGroup: drawnItems },
  })
);

map.on(L.Draw.Event.CREATED, (event) => {
  drawnItems.clearLayers();
  drawnItems.addLayer(event.layer);
  state.polygon = event.layer.getLatLngs()[0].map((point) => ({ lat: point.lat, lng: point.lng }));
  persistState();
  setStatus("prepare-status", `Area selected with ${state.polygon.length} points.`);
});

document.getElementById("prepare-area").addEventListener("click", async () => {
  if (!state.polygon) return setStatus("prepare-status", "Draw an area first.");
  setStatus("prepare-status", "Capturing selected map roads...");
  let imageData = null;
  try {
    imageData = await captureSelectedMapRegion();
  } catch (error) {
    console.warn("Map capture failed, falling back to abstract preparation.", error);
  }
  setStatus("prepare-status", "Preparing SUMO area...");
  const response = await fetch("/api/areas", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ polygon: state.polygon, image_data: imageData }),
  });
  const payload = await response.json();
  if (!response.ok) return setStatus("prepare-status", payload.detail || "Failed to prepare area.");
  state.runId = payload.run_id;
  state.preview = payload.preview;
  state.trace = null;
  state.selectedNode = null;
  persistState();
  drawNetwork(payload.preview, document.getElementById("network-preview"), null);
  document.getElementById("run-simulation").disabled = false;
  document.getElementById("open-gui-btn").disabled = false;
  clearRunPanels();
  setStatus("prepare-status", payload.user_message || "Scenario ready.");
});

document.getElementById("run-simulation").addEventListener("click", async () => {
  if (!state.runId) return;
  setStatus("run-status", "Running SUMO benchmark...");
  const runMode = document.getElementById("run-mode").value;
  setStatus("run-status", runMode === "full" ? "Running full SUMO benchmark..." : "Running quick SUMO simulation...");
  const response = await fetch(`/api/runs/${state.runId}/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      controller: document.getElementById("controller").value,
      episode_seconds: Number(document.getElementById("episode-seconds").value),
      open_gui: document.getElementById("open-gui").checked,
      mode: runMode,
    }),
  });
  const payload = await response.json();
  if (!response.ok) return setStatus("run-status", payload.detail || "Simulation failed.");
  renderComparison(payload.summary);
  renderArtifacts(payload.artifacts);
  state.trace = payload.trace;
  state.selectedNode = null;
  persistState();
  if (state.trace && state.trace.steps.length) {
    const timeline = document.getElementById("timeline");
    timeline.disabled = false;
    timeline.min = 0;
    timeline.max = String(state.trace.steps.length - 1);
    timeline.value = 0;
    updateReplayStep(0);
  }
  setStatus("run-status", runMode === "full" ? "Full benchmark completed successfully." : "Quick simulation completed successfully.");
});

document.getElementById("open-gui-btn").addEventListener("click", async () => {
  if (!state.runId) return;
  const response = await fetch(`/api/runs/${state.runId}/open-gui`, { method: "POST" });
  const payload = await response.json();
  setStatus("run-status", payload.message || payload.detail || "SUMO GUI request finished.");
});

document.getElementById("timeline").addEventListener("input", (event) => {
  updateReplayStep(Number(event.target.value));
});

restoreState();

function renderComparison(rows) {
  const host = document.getElementById("comparison-table");
  if (!rows || !rows.length) return (host.innerHTML = "<p>No results yet. Run the simulation to compare controllers.</p>");
  const columns = [
    ["controller", "Controller"],
    ["avg_waiting_time_mean", "Wait Mean"],
    ["avg_queue_length_mean", "Queue Mean"],
    ["throughput_mean", "Throughput"],
    ["avg_reward_mean", "Reward"],
  ];
  host.innerHTML = `<table><thead><tr>${columns.map(([, label]) => `<th>${label}</th>`).join("")}</tr></thead><tbody>${rows
    .map((row) => `<tr>${columns.map(([key]) => `<td>${formatValue(row[key])}</td>`).join("")}</tr>`)
    .join("")}</tbody></table>`;
}

function renderArtifacts(artifacts) {
  if (!artifacts || !Object.keys(artifacts).length) {
    document.getElementById("artifacts").innerHTML = "";
    return;
  }
  document.getElementById("artifacts").innerHTML = Object.entries(artifacts)
    .map(([label, url]) => `<a href="${url}" target="_blank" rel="noopener">${label.replaceAll("_", " ")}</a>`)
    .join("");
}

function updateReplayStep(index) {
  if (!state.trace || !state.trace.steps[index]) return;
  const step = state.trace.steps[index];
  document.getElementById("timeline-label").textContent = `Step ${index + 1} / ${state.trace.steps.length} at t = ${step.time_seconds}s`;
  drawNetwork(state.preview, document.getElementById("replay-network"), step);
  if (!state.selectedNode) state.selectedNode = Object.keys(step.intersections)[0] || null;
  if (state.selectedNode) showJunctionDetail(step, state.selectedNode);
  persistState();
}

function drawNetwork(preview, svg, step) {
  if (!preview) return;
  const width = 900;
  const height = 500;
  const padding = 36;
  const bounds = preview.bounds;
  const scaleX = (x) => padding + ((x - bounds.min_x) / Math.max(1, bounds.max_x - bounds.min_x)) * (width - padding * 2);
  const scaleY = (y) => height - padding - ((y - bounds.min_y) / Math.max(1, bounds.max_y - bounds.min_y)) * (height - padding * 2);
  const edges = preview.edges
    .map((edge) => {
      const points = edge.shape.map((point) => `${scaleX(point.x)},${scaleY(point.y)}`).join(" ");
      return `<polyline points="${points}" fill="none" stroke="#c2b7a3" stroke-width="${Math.max(2, edge.lanes)}" stroke-linecap="round" stroke-linejoin="round" />`;
    })
    .join("");
  const nodes = preview.nodes
    .map((node) => {
      const intersection = step?.intersections?.[node.id];
      const queue = intersection?.total_queue ?? 0;
      const color = queue > 14 ? "#9e2a2b" : queue > 7 ? "#d36f36" : "#17624d";
      const radius = 9 + Math.min(queue, 20) * 0.8;
      const label = intersection ? `${node.id} · ${intersection.decision.chosen_action}` : node.id;
      return `<g class="junction-node" data-node="${node.id}">
        <circle cx="${scaleX(node.x)}" cy="${scaleY(node.y)}" r="${radius}" fill="${color}" opacity="0.9"></circle>
        <text x="${scaleX(node.x) + radius + 6}" y="${scaleY(node.y) - 4}" font-size="12" fill="#26312d">${label}</text>
      </g>`;
    })
    .join("");
  svg.innerHTML = edges + nodes;
  svg.querySelectorAll(".junction-node").forEach((node) =>
    node.addEventListener("click", () => {
      state.selectedNode = node.getAttribute("data-node");
      persistState();
      if (step) showJunctionDetail(step, state.selectedNode);
    })
  );
}

function showJunctionDetail(step, nodeId) {
  const item = step.intersections[nodeId];
  if (!item) return;
  const decision = item.decision;
  const approaches = Object.entries(item.approaches)
    .map(([approach, values]) => `<div class="metric-row"><span>${approach}</span><span>queue ${values.queue_length}, wait ${values.waiting_time}, occ ${values.occupancy}</span></div>`)
    .join("");
  const rewards = Object.entries(decision.action_rewards || {})
    .map(([action, value]) => `<span class="badge">${action}: ${formatValue(value)}</span>`)
    .join("");
  document.getElementById("junction-detail").innerHTML = `
    <h3>${nodeId}</h3>
    <p>${decision.message}</p>
    <div class="metric-row"><span>Chosen action</span><strong>${decision.chosen_action}</strong></div>
    <div class="metric-row"><span>Optimizer action</span><strong>${decision.optimizer_action ?? "-"}</strong></div>
    <div class="metric-row"><span>Current phase</span><strong>${item.current_phase}</strong></div>
    <div class="metric-row"><span>Total queue</span><strong>${formatValue(item.total_queue)}</strong></div>
    <div class="metric-row"><span>Total wait</span><strong>${formatValue(item.total_wait)}</strong></div>
    <div class="metric-row"><span>North-south pressure</span><strong>${formatValue(decision.ns_pressure)}</strong></div>
    <div class="metric-row"><span>East-west pressure</span><strong>${formatValue(decision.ew_pressure)}</strong></div>
    <div class="metric-row"><span>Forecast score</span><strong>${decision.forecast_score ?? "-"}</strong></div>
    <div class="metric-row"><span>One-hot penalty</span><strong>${decision.one_hot_penalty ?? "-"}</strong></div>
    <div class="metric-row"><span>Coordination bonus</span><strong>${decision.coordination_bonus ?? "-"}</strong></div>
    <div style="margin-top:12px;"><strong>Action rewards</strong><div style="margin-top:6px;">${rewards || "No reward breakdown for this controller."}</div></div>
    <div style="margin-top:12px;"><strong>Approach metrics</strong>${approaches}</div>`;
}

async function captureSelectedMapRegion() {
  if (!window.html2canvas) throw new Error("html2canvas is not available.");
  const bounds = getSelectionPixelBounds();
  const sourceCanvas = await html2canvas(document.getElementById("map"), {
    useCORS: true,
    logging: false,
    backgroundColor: "#efe8d9",
  });
  const cropCanvas = document.createElement("canvas");
  cropCanvas.width = Math.max(1, Math.round(bounds.width));
  cropCanvas.height = Math.max(1, Math.round(bounds.height));
  const context = cropCanvas.getContext("2d");
  context.drawImage(
    sourceCanvas,
    bounds.left,
    bounds.top,
    bounds.width,
    bounds.height,
    0,
    0,
    cropCanvas.width,
    cropCanvas.height
  );
  return cropCanvas.toDataURL("image/png");
}

function getSelectionPixelBounds() {
  const points = state.polygon.map((point) => map.latLngToContainerPoint([point.lat, point.lng]));
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const left = Math.max(0, Math.floor(Math.min(...xs)));
  const top = Math.max(0, Math.floor(Math.min(...ys)));
  const right = Math.min(document.getElementById("map").clientWidth, Math.ceil(Math.max(...xs)));
  const bottom = Math.min(document.getElementById("map").clientHeight, Math.ceil(Math.max(...ys)));
  return {
    left,
    top,
    width: Math.max(32, right - left),
    height: Math.max(32, bottom - top),
  };
}

function clearRunPanels() {
  renderComparison([]);
  renderArtifacts({});
  document.getElementById("timeline").disabled = true;
  document.getElementById("timeline").value = 0;
  document.getElementById("timeline-label").textContent = "No run loaded.";
  document.getElementById("replay-network").innerHTML = "";
  document.getElementById("junction-detail").textContent = "Select a junction after running a simulation.";
}

function persistState() {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      polygon: state.polygon,
      runId: state.runId,
      selectedNode: state.selectedNode,
    })
  );
}

async function restoreState() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (!saved) return;
  try {
    const parsed = JSON.parse(saved);
    state.polygon = parsed.polygon ?? null;
    state.runId = parsed.runId ?? null;
    state.selectedNode = parsed.selectedNode ?? null;
    if (state.polygon?.length) {
      const layer = L.polygon(state.polygon.map((point) => [point.lat, point.lng]));
      drawnItems.addLayer(layer);
      map.fitBounds(layer.getBounds(), { padding: [20, 20] });
      setStatus("prepare-status", `Restored area with ${state.polygon.length} points.`);
    }
    if (!state.runId) return;
    const response = await fetch(`/api/runs/${state.runId}`);
    const payload = await response.json();
    if (!response.ok) return;
    state.preview = payload.scenario?.preview ?? null;
    if (state.preview) {
      drawNetwork(state.preview, document.getElementById("network-preview"), null);
      document.getElementById("run-simulation").disabled = false;
      document.getElementById("open-gui-btn").disabled = false;
    }
    if (payload.results) {
      renderComparison(payload.results.summary);
      renderArtifacts(payload.results.artifacts);
      state.trace = payload.results.trace;
      if (state.trace?.steps?.length) {
        const timeline = document.getElementById("timeline");
        timeline.disabled = false;
        timeline.min = 0;
        timeline.max = String(state.trace.steps.length - 1);
        timeline.value = 0;
        updateReplayStep(0);
        setStatus("run-status", "Restored latest simulation results.");
      }
    }
  } catch (error) {
    localStorage.removeItem(STORAGE_KEY);
  }
}

function setStatus(id, message) { document.getElementById(id).textContent = message; }
function formatValue(value) { return value === null || value === undefined ? "-" : typeof value === "number" ? Number(value).toFixed(2) : String(value); }
