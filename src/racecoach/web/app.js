const $ = (id) => document.getElementById(id);

const COLORS = {
  ref: "#4aa8ff",
  prac: "#ff9f43",
  good: "#3ddc97",
  bad: "#ff5c7a",
  warn: "#ffd166",
  muted: "#8fa1b8",
  grid: "rgba(143, 161, 184, 0.16)",
  cursor: "rgba(232, 238, 247, 0.7)",
  zone: "rgba(74, 168, 255, 0.08)",
};

const state = {
  payload: null,
  analysis: null,
  selectedZone: 0,
  currentDistance: 0,
  playing: false,
  speed: 32,
  nextEventIndex: 0,
  messages: [],
  raf: null,
  lastTs: null,
  sources: null,
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  wireEvents();
  try {
    const health = await fetchJson("/api/health");
    $("offline-badge").textContent = health.offline ? "Offline mode" : "Local only";
    $("offline-badge").className = "badge badge-good";
  } catch {
    $("offline-badge").textContent = "Local only";
  }
  await loadDemo();
  window.addEventListener("resize", debounce(() => drawCharts(), 100));
}

function wireEvents() {
  $("load-demo-button").addEventListener("click", () => loadDemo());
  $("analyze-button").addEventListener("click", () => analyzeFiles());
  $("reference-lap").addEventListener("change", () => reanalyze());
  $("practice-lap").addEventListener("change", () => reanalyze());
  $("max-gap").addEventListener("change", () => reanalyze());
  $("replay-play").addEventListener("click", () => (state.playing ? pauseReplay() : startReplay()));
  $("replay-reset").addEventListener("click", () => resetReplay(true));
  $("replay-speed").addEventListener("change", (event) => {
    state.speed = Number(event.target.value) || 1;
  });
  $("replay-distance").addEventListener("input", (event) => scrubTo(Number(event.target.value)));
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  let data;
  try {
    data = await response.json();
  } catch {
    data = { error: `HTTP ${response.status}` };
  }
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

async function loadDemo() {
  setStatus("Loading demo laps…");
  try {
    const payload = await fetchJson("/api/demo");
    state.sources = null;
    renderPayload(payload, "Demo loaded. Four complete braking zones and one skipped for a data gap.");
  } catch (error) {
    showError(error.message);
  }
}

async function analyzeFiles() {
  const refFile = $("reference-file").files[0];
  const pracFile = $("practice-file").files[0];
  if (!refFile || !pracFile) {
    showError("Choose both a reference CSV and a practice CSV.");
    return;
  }
  setStatus("Reading CSV files…");
  try {
    const [refText, pracText] = await Promise.all([refFile.text(), pracFile.text()]);
    state.sources = {
      reference: { name: refFile.name, csv: refText },
      practice: { name: pracFile.name, csv: pracText },
    };
    $("reference-lap").value = "0";
    $("practice-lap").value = "0";
    await reanalyze(true);
  } catch (error) {
    showError(error.message);
  }
}

async function reanalyze(fromFiles = false) {
  if (!state.sources) return;
  setStatus("Analyzing laps by distance…");
  try {
    const payload = await fetchJson("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reference: state.sources.reference,
        practice: state.sources.practice,
        reference_lap_index: fromFiles ? 0 : Number($("reference-lap").value || 0),
        practice_lap_index: fromFiles ? 0 : Number($("practice-lap").value || 0),
        max_gap_m: Number($("max-gap").value || 25),
      }),
    });
    renderPayload(
      payload,
      `Analysis loaded: ${payload.analysis.summary.completed_zones} complete braking zones, ` +
        `${payload.analysis.summary.skipped_zones} skipped.`
    );
  } catch (error) {
    showError(error.message);
  }
}

function renderPayload(payload, statusText) {
  state.payload = payload;
  state.analysis = payload.analysis;
  state.selectedZone = 0;
  state.messages = [];
  state.playing = false;
  state.lastTs = null;
  if (state.raf) cancelAnimationFrame(state.raf);
  state.raf = null;

  populateLaps(payload);
  const summary = payload.analysis.summary;
  $("zone-count").textContent = `${summary.completed_zones} complete · ${summary.skipped_zones} skipped`;
  $("demo-status").textContent = payload.demo ? "Demo loaded" : "Your laps";
  $("demo-status").className = "badge badge-good";
  renderZones();
  const firstComplete = payload.analysis.zones.findIndex((zone) => zone.status === "complete");
  selectZone(firstComplete >= 0 ? firstComplete : 0);
  renderQuality();
  resetReplay(true);
  setStatus(statusText, "ok");
}

function populateLaps(payload) {
  fillLapSelect($("reference-lap"), payload.reference_laps || [], payload.reference_selected_index || 0);
  fillLapSelect($("practice-lap"), payload.practice_laps || [], payload.practice_selected_index || 0);
}

function fillLapSelect(select, laps, selected) {
  select.replaceChildren();
  laps.forEach((lap, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = `${lap.label} · ${Math.round(lap.start_m)}–${Math.round(lap.end_m)} m`;
    select.append(option);
  });
  select.value = String(selected);
  select.disabled = laps.length <= 1 || !state.sources;
}

function renderZones() {
  const list = $("zone-list");
  list.replaceChildren();
  if (!state.analysis) return;
  state.analysis.zones.forEach((zone, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "zone-row" + (zone.status === "skipped" ? " skipped" : "");
    button.dataset.zoneIndex = String(index);
    button.dataset.status = zone.status;

    const name = document.createElement("span");
    name.className = "zone-name";
    name.textContent = zone.label;

    const meta = document.createElement("span");
    meta.className = "zone-meta";
    meta.textContent = `${Math.round(zone.start_m)}–${Math.round(zone.end_m)} m`;

    const delta = document.createElement("span");
    delta.className = "zone-delta";
    if (zone.status === "skipped") {
      delta.textContent = "Skipped";
      delta.classList.add("warn");
    } else if (zone.delta) {
      delta.textContent = signed(zone.delta.section_time_s, 2) + " s";
      const deltaClass =
        zone.delta.section_time_s > 0.005 ? "bad" : zone.delta.section_time_s < -0.005 ? "good" : "";
      if (deltaClass) delta.classList.add(deltaClass);
    }

    button.append(name, meta, delta);
    button.addEventListener("click", () => selectZone(index));
    list.append(button);
  });
}

function selectZone(index) {
  if (!state.analysis || index < 0 || index >= state.analysis.zones.length) return;
  state.selectedZone = index;
  document.querySelectorAll(".zone-row").forEach((row, rowIndex) => {
    row.classList.toggle("selected", rowIndex === index);
    row.setAttribute("aria-selected", rowIndex === index ? "true" : "false");
  });
  renderDetail();
  drawCharts();
}

function renderDetail() {
  const zone = state.analysis?.zones[state.selectedZone];
  if (!zone) return;
  $("detail-title").textContent = `${zone.label} · ${Math.round(zone.start_m)}–${Math.round(zone.end_m)} m`;
  $("detail-status").textContent = zone.status === "complete" ? "Complete" : "Skipped";
  $("detail-status").className = "badge " + (zone.status === "complete" ? "badge-good" : "badge-warn");
  $("detail-message").textContent = zone.message;
  $("detail-message").className = "feedback" + (zone.status === "skipped" ? " skipped" : "");

  const ref = zone.reference;
  const prac = zone.practice;
  const delta = zone.delta;
  const notes = $("detail-notes");
  notes.replaceChildren();

  if (zone.status === "skipped" || !ref || !prac || !delta) {
    setMetric("brake", "—", "practice —", "—", "");
    setMetric("speed", "—", "practice —", "—", "");
    setMetric("time", "—", "practice —", "—", "");
    if (zone.skip_reason) addNote(notes, zone.skip_reason);
    (zone.notes || []).forEach((note) => addNote(notes, note));
    return;
  }

  const brakeDelta = delta.brake_start_m;
  let brakeDeltaText = "—";
  let brakeDeltaClass = "";
  if (brakeDelta !== null && brakeDelta !== undefined) {
    if (Math.abs(brakeDelta) < 1) {
      brakeDeltaText = "same point";
    } else {
      brakeDeltaText = `${Math.abs(brakeDelta).toFixed(0)} m ${brakeDelta > 0 ? "earlier" : "later"}`;
      brakeDeltaClass = "warn";
    }
  }
  setMetric(
    "brake",
    ref.brake_start_m === null ? "—" : `${ref.brake_start_m.toFixed(0)} m`,
    prac.brake_start_m === null ? "practice no brake" : `practice ${prac.brake_start_m.toFixed(0)} m`,
    brakeDeltaText,
    brakeDeltaClass
  );

  const speedDelta = delta.min_speed_kmh;
  setMetric(
    "speed",
    `${ref.min_speed_kmh.toFixed(1)} km/h`,
    `practice ${prac.min_speed_kmh.toFixed(1)} km/h`,
    `${signed(speedDelta, 1)} km/h`,
    speedDelta < -0.05 ? "bad" : speedDelta > 0.05 ? "good" : ""
  );

  const timeDelta = delta.section_time_s;
  setMetric(
    "time",
    `${ref.section_time_s.toFixed(2)} s`,
    `practice ${prac.section_time_s.toFixed(2)} s`,
    `${signed(timeDelta, 2)} s`,
    timeDelta > 0.005 ? "bad" : timeDelta < -0.005 ? "good" : ""
  );

  (zone.notes || []).forEach((note) => addNote(notes, note));
}

function setMetric(name, refText, pracText, deltaText, deltaClass) {
  $(`detail-${name}-ref`).textContent = refText;
  $(`detail-${name}-prac`).textContent = pracText;
  const deltaEl = $(`detail-${name}-delta`);
  deltaEl.textContent = deltaText;
  deltaEl.className = "metric-delta " + (deltaClass || "");
}

function addNote(container, text) {
  const note = document.createElement("div");
  note.className = "note";
  note.textContent = text;
  container.append(note);
}

function renderQuality() {
  const list = $("gap-list");
  list.replaceChildren();
  if (!state.analysis) return;
  const gaps = state.analysis.gaps || { reference: [], practice: [] };
  const skipped = state.analysis.zones.filter((zone) => zone.status === "skipped");
  let count = 0;
  for (const [label, items] of [
    ["Reference", gaps.reference || []],
    ["Practice", gaps.practice || []],
  ]) {
    for (const gap of items) {
      const div = document.createElement("div");
      div.className = "gap";
      div.textContent = `${label}: ${gap.gap_m.toFixed(0)} m gap between ${gap.start_m.toFixed(0)} m and ${gap.end_m.toFixed(0)} m (${gap.gap_s.toFixed(2)} s).`;
      list.append(div);
      count += 1;
    }
  }
  for (const zone of skipped) {
    const div = document.createElement("div");
    div.className = "gap";
    div.textContent = `${zone.label} skipped: ${zone.skip_reason}`;
    list.append(div);
    count += 1;
  }
  if (count === 0) {
    const div = document.createElement("div");
    div.className = "gap ok";
    div.textContent = "No large gaps or skipped sections detected.";
    list.append(div);
  }
  $("quality-count").textContent = `${count} issue${count === 1 ? "" : "s"}`;
}

function resetReplay(clearMessages) {
  state.playing = false;
  state.lastTs = null;
  if (state.raf) cancelAnimationFrame(state.raf);
  state.raf = null;
  $("replay-play").textContent = "Play";
  const grid = state.analysis?.grid;
  if (!grid) return;
  state.currentDistance = grid.start_m;
  state.nextEventIndex = firstEventAfter(state.currentDistance);
  if (clearMessages) {
    state.messages = [];
    renderMessages();
  }
  const scrubber = $("replay-distance");
  scrubber.min = String(grid.start_m);
  scrubber.max = String(grid.end_m);
  scrubber.step = "0.5";
  scrubber.value = String(state.currentDistance);
  updateReplayReadout();
  $("replay-status").textContent = "Ready";
  drawCharts();
}

function firstEventAfter(distance) {
  const events = state.analysis?.replay_events || [];
  const index = events.findIndex((event) => event.distance_m > distance + 0.001);
  return index === -1 ? events.length : index;
}

function startReplay() {
  const grid = state.analysis?.grid;
  if (!grid) return;
  if (state.currentDistance >= grid.end_m - 0.01) {
    resetReplay(true);
  }
  state.playing = true;
  state.lastTs = null;
  $("replay-play").textContent = "Pause";
  $("replay-status").textContent = "Replaying…";
  state.raf = requestAnimationFrame(tick);
}

function pauseReplay() {
  state.playing = false;
  state.lastTs = null;
  if (state.raf) cancelAnimationFrame(state.raf);
  state.raf = null;
  $("replay-play").textContent = "Play";
  $("replay-status").textContent = "Paused";
}

function tick(timestamp) {
  if (!state.playing) return;
  const grid = state.analysis.grid;
  if (state.lastTs === null) state.lastTs = timestamp;
  const dt = Math.min((timestamp - state.lastTs) / 1000, 0.1);
  state.lastTs = timestamp;

  const speed = interpolate("reference", "speed_kmh", state.currentDistance);
  const metresPerSecond = Math.max((speed ?? 100) / 3.6, 1);
  state.currentDistance = Math.min(
    grid.end_m,
    state.currentDistance + metresPerSecond * dt * state.speed
  );
  emitEvents();
  updateReplayReadout();
  drawCharts();

  if (state.currentDistance >= grid.end_m - 0.001) {
    finishReplay();
  } else {
    state.raf = requestAnimationFrame(tick);
  }
}

function emitEvents() {
  const events = state.analysis?.replay_events || [];
  let changed = false;
  while (
    state.nextEventIndex < events.length &&
    state.currentDistance >= events[state.nextEventIndex].distance_m - 0.001
  ) {
    state.messages.push(events[state.nextEventIndex]);
    state.nextEventIndex += 1;
    changed = true;
  }
  if (changed) renderMessages();
}

function finishReplay() {
  state.playing = false;
  state.lastTs = null;
  if (state.raf) cancelAnimationFrame(state.raf);
  state.raf = null;
  const events = state.analysis?.replay_events || [];
  while (state.nextEventIndex < events.length) {
    state.messages.push(events[state.nextEventIndex]);
    state.nextEventIndex += 1;
  }
  renderMessages();
  $("replay-play").textContent = "Play";
  $("replay-status").textContent = `Replay complete — ${state.messages.length} message${state.messages.length === 1 ? "" : "s"}`;
  updateReplayReadout();
  drawCharts();
}

function scrubTo(distance) {
  if (!state.analysis) return;
  state.playing = false;
  state.lastTs = null;
  if (state.raf) cancelAnimationFrame(state.raf);
  state.raf = null;
  $("replay-play").textContent = "Play";
  state.currentDistance = distance;
  state.nextEventIndex = firstEventAfter(distance);
  state.messages = [];
  renderMessages();
  updateReplayReadout();
  $("replay-status").textContent = "Scrubbed";
  drawCharts();
}

function updateReplayReadout() {
  const grid = state.analysis?.grid;
  if (!grid) return;
  $("replay-distance").value = String(state.currentDistance);
  $("replay-readout").textContent = `${Math.round(state.currentDistance)} m / ${Math.round(grid.end_m)} m`;
}

function renderMessages() {
  const container = $("messages");
  container.replaceChildren();
  $("message-count").textContent = String(state.messages.length);
  if (state.messages.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "Press Play to receive one coaching message per completed braking zone.";
    container.append(empty);
    return;
  }
  for (const event of state.messages) {
    const row = document.createElement("div");
    row.className = "message";
    const distance = document.createElement("span");
    distance.className = "message-distance";
    distance.textContent = `${Math.round(event.distance_m)} m`;
    const text = document.createElement("span");
    text.className = "message-text";
    text.textContent = event.message;
    row.append(distance, text);
    container.append(row);
  }
  container.scrollTop = container.scrollHeight;
}

function setStatus(text, kind = "") {
  const el = $("app-status");
  el.textContent = text;
  el.className = "status" + (kind ? ` ${kind}` : "");
}

function showError(message) {
  setStatus(`Error: ${message}`, "error");
}

function signed(value, digits) {
  if (value === null || value === undefined) return "—";
  if (Math.abs(value) < 0.5 * 10 ** -digits) return (0).toFixed(digits);
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function debounce(fn, wait) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

// -- charts -------------------------------------------------------------

function drawCharts() {
  if (!state.analysis?.grid) return;
  drawSpeedChart();
  drawPedalChart();
  drawDeltaChart();
}

function prepareCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(canvas.clientWidth || 600, 200);
  const height = Math.max(canvas.clientHeight || Number(canvas.getAttribute("height")) || 150, 80);
  const pixelWidth = Math.round(width * dpr);
  const pixelHeight = Math.round(height * dpr);
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return { ctx, width, height };
}

function chartFrame(ctx, width, height) {
  const left = 48;
  const right = 12;
  const top = 10;
  const bottom = 22;
  return {
    left,
    right,
    top,
    bottom,
    plotWidth: Math.max(width - left - right, 10),
    plotHeight: Math.max(height - top - bottom, 10),
  };
}

function drawSpeedChart() {
  const canvas = $("speed-chart");
  const { ctx, width, height } = prepareCanvas(canvas);
  const frame = chartFrame(ctx, width, height);
  const grid = state.analysis.grid;
  const maxSpeed = niceMax(
    Math.max(...nonNull(grid.reference.speed_kmh), ...nonNull(grid.practice.speed_kmh), 100),
    50
  );
  drawZoneShade(ctx, frame);
  drawGrid(ctx, frame, 0, maxSpeed, 3, (value) => `${Math.round(value)}`);
  const xFor = (distance) => xScale(distance, frame, grid);
  const yFor = (value) => yScale(value, 0, maxSpeed, frame);
  drawSeries(ctx, grid.reference.speed_kmh, xFor, yFor, COLORS.ref, 2, []);
  drawSeries(ctx, grid.practice.speed_kmh, xFor, yFor, COLORS.prac, 2, []);
  drawCursor(ctx, frame, grid);
  drawXAxis(ctx, frame, grid);
}

function drawPedalChart() {
  const canvas = $("pedal-chart");
  const { ctx, width, height } = prepareCanvas(canvas);
  const frame = chartFrame(ctx, width, height);
  const grid = state.analysis.grid;
  drawZoneShade(ctx, frame);
  drawGrid(ctx, frame, 0, 1, 2, (value) => value.toFixed(1));
  const xFor = (distance) => xScale(distance, frame, grid);
  const yFor = (value) => yScale(value, 0, 1, frame);
  drawSeries(ctx, grid.reference.throttle, xFor, yFor, COLORS.ref, 1.4, []);
  drawSeries(ctx, grid.practice.throttle, xFor, yFor, COLORS.prac, 1.4, []);
  drawSeries(ctx, grid.reference.brake, xFor, yFor, COLORS.ref, 1.8, [4, 3]);
  drawSeries(ctx, grid.practice.brake, xFor, yFor, COLORS.prac, 1.8, [4, 3]);
  drawCursor(ctx, frame, grid);
  drawXAxis(ctx, frame, grid);
}

function drawDeltaChart() {
  const canvas = $("delta-chart");
  const { ctx, width, height } = prepareCanvas(canvas);
  const frame = chartFrame(ctx, width, height);
  const grid = state.analysis.grid;
  const values = nonNull(grid.delta_time_s);
  const maxAbs = niceMax(Math.max(...values.map((value) => Math.abs(value)), 0.5), 0.5);
  drawZoneShade(ctx, frame);
  drawGrid(ctx, frame, -maxAbs, maxAbs, 2, (value) => `${value >= 0 ? "+" : ""}${value.toFixed(1)}`);
  const xFor = (distance) => xScale(distance, frame, grid);
  const yFor = (value) => yScale(value, -maxAbs, maxAbs, frame);
  ctx.save();
  ctx.strokeStyle = "rgba(232, 238, 247, 0.25)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(frame.left, yFor(0));
  ctx.lineTo(frame.left + frame.plotWidth, yFor(0));
  ctx.stroke();
  ctx.restore();
  drawSeries(ctx, grid.delta_time_s, xFor, yFor, "#9ad7ff", 2, []);
  drawCursor(ctx, frame, grid);
  drawXAxis(ctx, frame, grid);
}

function drawZoneShade(ctx, frame) {
  const zone = state.analysis?.zones[state.selectedZone];
  const grid = state.analysis?.grid;
  if (!zone || !grid) return;
  const x1 = xScale(zone.start_m, frame, grid);
  const x2 = xScale(zone.end_m, frame, grid);
  ctx.save();
  ctx.fillStyle = COLORS.zone;
  ctx.fillRect(x1, frame.top, Math.max(x2 - x1, 1), frame.plotHeight);
  ctx.strokeStyle = "rgba(74, 168, 255, 0.35)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x1, frame.top);
  ctx.lineTo(x1, frame.top + frame.plotHeight);
  ctx.moveTo(x2, frame.top);
  ctx.lineTo(x2, frame.top + frame.plotHeight);
  ctx.stroke();
  ctx.restore();
}

function drawGrid(ctx, frame, min, max, divisions, formatter) {
  ctx.save();
  ctx.strokeStyle = COLORS.grid;
  ctx.fillStyle = COLORS.muted;
  ctx.lineWidth = 1;
  ctx.font = "11px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= divisions; i += 1) {
    const value = min + ((max - min) * i) / divisions;
    const y = yScale(value, min, max, frame);
    ctx.beginPath();
    ctx.moveTo(frame.left, y);
    ctx.lineTo(frame.left + frame.plotWidth, y);
    ctx.stroke();
    ctx.fillText(formatter(value), frame.left - 6, y);
  }
  ctx.restore();
}

function drawXAxis(ctx, frame, grid) {
  ctx.save();
  ctx.fillStyle = COLORS.muted;
  ctx.font = "11px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const span = grid.end_m - grid.start_m;
  const step = span > 3000 ? 1000 : span > 1500 ? 500 : span > 600 ? 200 : 100;
  const first = Math.ceil(grid.start_m / step) * step;
  for (let distance = first; distance <= grid.end_m + 0.1; distance += step) {
    const x = xScale(distance, frame, grid);
    ctx.fillText(`${Math.round(distance)} m`, x, frame.top + frame.plotHeight + 6);
  }
  ctx.restore();
}

function drawSeries(ctx, values, xFor, yFor, color, width, dash) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.setLineDash(dash);
  ctx.beginPath();
  let started = false;
  const distances = state.analysis.grid.distance_m;
  for (let i = 0; i < values.length; i += 1) {
    const value = values[i];
    if (value === null || value === undefined) {
      started = false;
      continue;
    }
    const x = xFor(distances[i]);
    const y = yFor(value);
    if (!started) {
      ctx.moveTo(x, y);
      started = true;
    } else {
      ctx.lineTo(x, y);
    }
  }
  ctx.stroke();
  ctx.restore();
}

function drawCursor(ctx, frame, grid) {
  if (state.currentDistance < grid.start_m || state.currentDistance > grid.end_m) return;
  const x = xScale(state.currentDistance, frame, grid);
  ctx.save();
  ctx.strokeStyle = COLORS.cursor;
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(x, frame.top);
  ctx.lineTo(x, frame.top + frame.plotHeight);
  ctx.stroke();
  ctx.restore();
}

function xScale(distance, frame, grid) {
  const span = Math.max(grid.end_m - grid.start_m, 1);
  return frame.left + ((distance - grid.start_m) / span) * frame.plotWidth;
}

function yScale(value, min, max, frame) {
  const span = Math.max(max - min, 1e-9);
  return frame.top + (1 - (value - min) / span) * frame.plotHeight;
}

function interpolate(which, field, distance) {
  const grid = state.analysis?.grid;
  if (!grid) return null;
  const distances = grid.distance_m;
  const values = grid[which]?.[field];
  if (!values || distances.length === 0) return null;
  if (distance < distances[0] || distance > distances[distances.length - 1]) return null;
  let low = 0;
  let high = distances.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (distances[mid] < distance) low = mid + 1;
    else high = mid - 1;
  }
  if (low < distances.length && Math.abs(distances[low] - distance) < 1e-6) {
    return values[low];
  }
  if (low === 0 || low >= distances.length) return null;
  const leftValue = values[low - 1];
  const rightValue = values[low];
  if (leftValue === null || rightValue === null) return null;
  const t = (distance - distances[low - 1]) / Math.max(distances[low] - distances[low - 1], 1e-9);
  return leftValue + t * (rightValue - leftValue);
}

function nonNull(values) {
  return values.filter((value) => value !== null && value !== undefined);
}

function niceMax(value, step) {
  return Math.ceil(value / step) * step;
}
