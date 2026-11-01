const $ = (id) => document.getElementById(id);
const state = { runs: [null, null], index: 0, mode: "object", refPoints: [], polling: false, tracking: false };
const current = () => state.runs[state.index];

const LAW_FUNCTIONS = {
  constant_velocity: (t, p) => p.v * t + p.s0,
  constant_acceleration: (t, p) => 0.5 * p.a * t * t + p.v0 * t + p.s0,
  damped_oscillation: (t, p) => p.amp * Math.exp(-p.gamma * t) * Math.cos(p.omega * t + p.phase) + p.offset,
  exponential_relaxation: (t, p) => p.amp * Math.exp(-t / p.tau) + p.final,
};
const UNITS = { a: "m/s²", v: "m/s", tau: "s", omega: "rad/s", gamma: "1/s", period_s: "s" };
const GRAVITY = [["Moon", 1.62], ["Mars", 3.71], ["Earth", 9.81]];
const SAMPLE_FRAME = 48;

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `request failed (${res.status})`);
  return body;
}

const post = (path, data) => api(path, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data ?? {}),
});

function showError(message) {
  $("error").textContent = message || "";
  $("error").hidden = !message;
}

function startRun(run) {
  state.runs[state.index] = run;
  state.mode = "object";
  state.refPoints = [];
  $("video-card").hidden = false;
  document.querySelector("main").hidden = false;
  $("load").hidden = true;
  showLoadError(null);
  $("video-title").textContent = `Run ${state.index + 1}`;
  // The stage must match the video exactly, or taps land on letterbox bars and map to the wrong pixel.
  $("stage").style.aspectRatio = `${run.width} / ${run.height}`;
  $("stage").style.width = `min(100%, calc(62vh * ${run.width / run.height}))`;
  $("video").src = run.video;
  $("scrub").max = run.frames - 1;
  $("scrub").value = 0;
  $("metres").value = state.index === 1 ? $("metres").value : "";
  $("reference-row").hidden = true;
  showError(null);
  render();
  poll();
}

async function poll() {
  if (state.polling) return;
  state.polling = true;
  const index = state.index;
  try {
    for (;;) {
      const run = await api(`/api/runs/${state.runs[index].id}`);
      state.runs[index] = run;
      render();
      if (run.status === "idle") break;
      await new Promise((resolve) => setTimeout(resolve, 700));
    }
  } catch (err) {
    showError(err.message);
  }
  state.polling = false;
}

function stepList(run) {
  const verifying = state.index === 1;
  const steps = [
    ["Read", run.status !== "reading" || !!run.setup.experiment],
    ["Track", run.track.length > 0],
    ["Scale", !!run.metres_per_px],
    [verifying ? "Test" : "Find law", verifying ? !!run.verdict : !!run.finding],
  ];
  const now = steps.findIndex(([, done]) => !done);
  $("steps").replaceChildren(...steps.map(([text, done], i) => {
    const li = document.createElement("li");
    li.textContent = text;
    li.className = done ? "done" : i === now ? "now" : "";
    return li;
  }));
}

function render() {
  const run = current();
  if (!run) return;
  stepList(run);
  const busy = { reading: "Reading the video with Spark", analysing: "Agent working", verifying: "Scoring run 2" }[run.status];
  $("busy").textContent = state.tracking ? "Tracking with SAM 3.1…" : busy ? `${busy}…` : "";
  $("stage").classList.toggle("scanning", state.tracking || !!busy);
  updateReadout();
  if (run.error) showError(run.error);

  if (run.setup.experiment) {
    $("reading").hidden = false;
    $("experiment").textContent = run.setup.experiment;
    $("transcript").textContent = run.transcript ? `“${run.transcript}”` : "No narration heard.";
    if (run.setup.reference_metres && !$("metres").value) $("metres").value = run.setup.reference_metres;
  }

  const ready = run.status === "idle";
  if (run.status === "reading") {
    $("prompt").textContent = "Spark is watching the clip. Tapping opens up in a moment.";
  } else if (!run.track.length) {
    $("prompt").textContent = "Scrub to a frame where the object is clear, then tap it.";
  } else if (!run.metres_per_px) {
    state.mode = "reference";
    $("reference-row").hidden = false;
    const name = run.setup.reference || "reference";
    $("prompt").textContent = state.refPoints.length === 2
      ? "Enter the length, then press Set scale."
      : `Tap both ends of the ${name}.`;
  } else {
    state.mode = "done";
    $("prompt").textContent = `Tracked ${run.track.length} of ${run.frames} frames at ${(run.metres_per_px * 1000).toFixed(2)} mm per pixel.`;
  }

  const go = $("go");
  if (run.track.length && !run.metres_per_px) {
    go.textContent = "Set scale";
    go.disabled = !ready || state.refPoints.length !== 2;
  } else {
    go.textContent = state.index === 1 ? "Test the law" : "Analyse";
    go.disabled = !ready || !run.series;
  }

  renderAgent(run);
  renderFinding();
  renderVerdict(state.runs[1]);
  drawOverlay();
}

function updateReadout() {
  const run = current();
  const frame = Number($("scrub").value);
  $("frame-readout").textContent = `${run.times[frame].toFixed(2)} s · frame ${frame + 1} of ${run.frames}`;
}

function renderAgent(run) {
  $("agent").hidden = run.events.length === 0;
  $("log").replaceChildren(...run.events.map((event) => {
    const li = document.createElement("li");
    li.textContent = `› ${event.text}`;
    return li;
  }));
}

function renderFinding() {
  const run = state.runs[0];
  if (!run || !run.finding) return;
  const f = run.finding;
  $("finding").hidden = false;
  $("next").hidden = state.index === 1;
  $("quantity").textContent = f.quantity;
  const magnitude = Math.abs(f.value);
  $("value").textContent = f.error != null ? `${magnitude.toFixed(2)} ± ${f.error.toFixed(2)} ` : `${magnitude.toFixed(3)} `;
  const unit = document.createElement("small");
  unit.textContent = UNITS[f.parameter] || "";
  $("value").append(unit);
  drawRuler(f);
  $("law").textContent = `${f.fit.law.replaceAll("_", " ")}: ${f.fit.equation}. ${f.fit.n} samples, R² ${f.fit.r2.toFixed(4)}, scatter ${(f.fit.rms_m * 1000).toFixed(2)} mm.`;
  $("explanation").textContent = f.explanation;
  $("next-run").textContent = f.next_run;
  $("fit-warnings").hidden = !f.warnings.length;
  $("fit-warnings").textContent = f.warnings.join(". ");
  drawChart(run);
  drawTable(run);
}

function renderVerdict(run) {
  if (!run || !run.verdict) return;
  const v = run.verdict;
  $("verdict").hidden = false;
  $("next").hidden = true;
  const line = $("verdict-line");
  line.className = `verdict ${v.passed ? "pass" : "fail"}`;
  line.textContent = v.passed ? "✓ The law held" : "✕ The law broke";
  $("verdict-text").textContent = v.explanation || v.reason;
  const head = "<tr><th>Constant</th><th>Run 1</th><th>Run 2</th><th>Difference</th></tr>";
  $("verdict-table").innerHTML = head;
  for (const [name, c] of Object.entries(v.constants)) {
    const row = $("verdict-table").insertRow();
    [name, Math.abs(c.run_1).toFixed(3), Math.abs(c.run_2).toFixed(3), `${(c.difference * 100).toFixed(1)}%`]
      .forEach((text) => { row.insertCell().textContent = text; });
  }
  $("verdict-rms").textContent = `Law frozen from run 1: ${(v.held_rms * 1000).toFixed(2)} mm scatter, across ${v.n} samples. Free fit to run 2: ${(v.free_rms * 1000).toFixed(2)} mm.`;
  $("verdict-warnings").hidden = !v.warnings.length;
  $("verdict-warnings").textContent = v.warnings.join(". ");
}

function drawRuler(f) {
  const box = $("ruler");
  // Only an acceleration can be read against the surface gravity of other worlds.
  if (f.parameter !== "a") {
    box.replaceChildren();
    return;
  }
  const width = 520, left = 6, right = 6, max = 11, base = 30;
  const sx = (v) => left + (Math.min(v, max) / max) * (width - left - right);
  const value = Math.abs(f.value), error = f.error || 0;
  const svg = [];
  for (let v = 0; v <= max; v += 0.5) {
    const major = Number.isInteger(v);
    svg.push(`<line class="tick${major ? " major" : ""}" x1="${sx(v)}" x2="${sx(v)}" y1="${base}" y2="${base + (major ? 12 : 7)}"/>`);
  }
  GRAVITY.forEach(([name, g]) => {
    svg.push(`<line class="mark-line" x1="${sx(g)}" x2="${sx(g)}" y1="${base}" y2="${base + 18}"/>`);
    svg.push(`<text class="mark-label" x="${sx(g)}" y="${base + 31}" text-anchor="middle">${name} ${g}</text>`);
  });
  svg.push(`<rect class="needle-band" x="${sx(value - error)}" y="${base - 22}" width="${Math.max(sx(value + error) - sx(value - error), 1)}" height="22"/>`);
  svg.push(`<line class="needle" x1="${sx(value)}" x2="${sx(value)}" y1="${base - 24}" y2="${base}"/>`);
  box.innerHTML = `<svg viewBox="0 0 ${width} ${base + 36}" role="img" aria-label="${value.toFixed(2)} metres per second squared on a scale with the Moon, Mars and Earth marked">${svg.join("")}</svg>`;
}

function drawChart(run) {
  const f = run.finding;
  const width = 520, height = 260, left = 52, right = 12, top = 10, bottom = 34;
  const ts = run.series.t, values = run.series[f.axis];
  const t0 = ts.find((t) => t >= f.window[0]);
  const law = LAW_FUNCTIONS[f.fit.law];
  const fitted = (t) => law(t - t0, f.fit.values);
  const minT = Math.min(...ts), maxT = Math.max(...ts);
  const minV = Math.min(...values), maxV = Math.max(...values);
  const pad = (maxV - minV) * 0.06 || 0.01;
  const sx = (t) => left + ((t - minT) / (maxT - minT || 1)) * (width - left - right);
  const sy = (v) => height - bottom - ((v - minV + pad) / (maxV - minV + 2 * pad)) * (height - top - bottom);
  const svg = [];
  svg.push(`<rect class="fit-band" x="${sx(f.window[0])}" y="${top}" width="${sx(f.window[1]) - sx(f.window[0])}" height="${height - top - bottom}"/>`);
  for (let i = 0; i <= 4; i++) {
    const v = minV + ((maxV - minV) * i) / 4;
    svg.push(`<line class="grid-line" x1="${left}" x2="${width - right}" y1="${sy(v)}" y2="${sy(v)}"/>`);
    svg.push(`<text x="${left - 8}" y="${sy(v) + 4}" text-anchor="end">${(v - minV).toFixed(2)}</text>`);
    const t = minT + ((maxT - minT) * i) / 4;
    svg.push(`<text x="${sx(t)}" y="${height - 16}" text-anchor="middle">${t.toFixed(2)}</text>`);
  }
  svg.push(`<text x="${(left + width - right) / 2}" y="${height - 2}" text-anchor="middle">time (s)</text>`);
  svg.push(`<text transform="translate(11 ${(top + height - bottom) / 2}) rotate(-90)" text-anchor="middle">${f.axis === "y" ? "height" : "position"} (m)</text>`);
  ts.forEach((t, i) => {
    const inside = t >= f.window[0] && t <= f.window[1];
    svg.push(`<circle class="dot" cx="${sx(t)}" cy="${sy(values[i])}" r="4" fill-opacity="${inside ? 1 : 0.3}" stroke-opacity="${inside ? 1 : 0}"/>`);
  });
  const line = [];
  for (let i = 0; i <= 80; i++) {
    const t = f.window[0] + ((f.window[1] - f.window[0]) * i) / 80;
    line.push(`${sx(t).toFixed(1)},${sy(fitted(t)).toFixed(1)}`);
  }
  svg.push(`<polyline class="fit-line" points="${line.join(" ")}"/>`);
  svg.push(`<line class="cross" id="cross" y1="${top}" y2="${height - bottom}" visibility="hidden"/>`);
  const box = $("chart");
  box.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Measured ${f.axis} position over time with the fitted law">${svg.join("")}</svg><div class="tip" hidden></div>`;
  const tip = box.querySelector(".tip"), cross = box.querySelector("#cross"), area = box.querySelector("svg");
  area.addEventListener("pointermove", (event) => {
    const rect = area.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * width;
    let nearest = 0;
    ts.forEach((t, i) => { if (Math.abs(sx(t) - px) < Math.abs(sx(ts[nearest]) - px)) nearest = i; });
    const x = sx(ts[nearest]);
    cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.style.left = `${(x / width) * rect.width}px`;
    tip.style.top = `${(sy(values[nearest]) / height) * rect.height}px`;
    tip.textContent = `${ts[nearest].toFixed(3)} s, ${(values[nearest] - minV).toFixed(3)} m`;
  });
  area.addEventListener("pointerleave", () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); });
}

function drawTable(run) {
  const { t, x, y } = run.series;
  const rows = t.map((_, i) => `<tr><td>${t[i].toFixed(3)}</td><td>${x[i].toFixed(4)}</td><td>${y[i].toFixed(4)}</td></tr>`);
  $("table").innerHTML = `<table><tr><th>t (s)</th><th>x (m)</th><th>y (m)</th></tr>${rows.join("")}</table>`;
}

function drawOverlay() {
  const canvas = $("overlay"), run = current();
  if (!run) return;
  canvas.width = run.width;
  canvas.height = run.height;
  const ctx = canvas.getContext("2d");
  const scale = Math.max(run.width / 640, 1);
  ctx.lineWidth = 2 * scale;
  const frame = Number($("scrub").value);
  ctx.strokeStyle = "#f0a35e";
  ctx.beginPath();
  run.track.forEach((p, i) => {
    const x = (p.x1 + p.x2) / 2, y = (p.y1 + p.y2) / 2;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
  const box = run.track.find((p) => p.frame === frame);
  if (box) {
    ctx.strokeStyle = "#ffffff";
    ctx.strokeRect(box.x1, box.y1, box.x2 - box.x1, box.y2 - box.y1);
  }
  ctx.fillStyle = "#6cb2e8";
  ctx.strokeStyle = "#6cb2e8";
  state.refPoints.forEach(([x, y]) => {
    ctx.beginPath();
    ctx.arc(x, y, 6 * scale, 0, Math.PI * 2);
    ctx.fill();
  });
  if (state.refPoints.length === 2) {
    ctx.beginPath();
    ctx.moveTo(...state.refPoints[0]);
    ctx.lineTo(...state.refPoints[1]);
    ctx.stroke();
  }
}

function seek() {
  const run = current();
  if (!run) return;
  $("video").currentTime = run.times[Number($("scrub").value)] + 0.001;
  updateReadout();
  drawOverlay();
}

async function onTap(event) {
  const run = current();
  if (!run || run.status !== "idle" || state.tracking) return;
  const rect = $("overlay").getBoundingClientRect();
  const x = Math.round(((event.clientX - rect.left) / rect.width) * run.width);
  const y = Math.round(((event.clientY - rect.top) / rect.height) * run.height);
  showError(null);
  if (state.mode === "object") {
    state.tracking = true;
    $("busy").textContent = "Tracking with SAM 3.1…";
    try {
      const t = run.times[Number($("scrub").value)];
      state.runs[state.index] = await post(`/api/runs/${run.id}/track`, { t, x, y });
    } catch (err) {
      showError(err.message);
    }
    state.tracking = false;
    render();
  } else if (state.mode === "reference") {
    if (state.refPoints.length === 2) state.refPoints = [];
    state.refPoints.push([x, y]);
    render();
  }
}

async function onGo() {
  const run = current();
  showError(null);
  try {
    if (run.track.length && !run.metres_per_px) {
      const metres = parseFloat($("metres").value);
      if (!(metres > 0)) throw new Error("enter the reference length in metres");
      state.runs[state.index] = await post(`/api/runs/${run.id}/reference`, {
        p1: state.refPoints[0], p2: state.refPoints[1], metres,
      });
      $("reference-row").hidden = true;
      render();
    } else if (state.index === 1) {
      await post(`/api/runs/${run.id}/verify`, { against: state.runs[0].id });
      poll();
    } else {
      await post(`/api/runs/${run.id}/analyse`);
      poll();
    }
  } catch (err) {
    showError(err.message);
  }
}

async function upload(file) {
  const form = new FormData();
  form.append("file", file);
  $("busy").textContent = "Uploading…";
  showError(null);
  try {
    startRun(await api("/api/runs", { method: "POST", body: form }));
  } catch (err) {
    showLoadError(err.message);
  }
}

function showLoadError(message) {
  $("load-error").textContent = message || "";
  $("load-error").hidden = !message;
}

async function loadSample() {
  showError(null);
  try {
    startRun(await post(`/api/samples/jump_${state.index + 1}`));
    $("metres").value = "0.914";
    $("sample-note").hidden = false;
    // Open on the top of the jump, where the astronaut is easiest to tap.
    $("scrub").value = SAMPLE_FRAME;
    seek();
  } catch (err) {
    showLoadError(err.message);
  }
}

async function init() {
  $("pick").onclick = () => $("file").click();
  $("file").onchange = () => { if ($("file").files[0]) upload($("file").files[0]); };
  $("scrub").oninput = seek;
  $("overlay").onclick = onTap;
  $("go").onclick = onGo;
  $("restart-ref").onclick = () => { state.refPoints = []; render(); };
  $("start-run-2").onclick = () => {
    state.index = 1;
    $("load-title").textContent = "Run 2";
    $("load-heading").textContent = "Now try to break it.";
    $("load-lede").textContent = "Give Gauge a second recording. The law from run 1 stays frozen and has to predict it.";
    $("sample").textContent = "Use the second jump";
    $("load").classList.add("compact");
    $("load").hidden = false;
    document.querySelector("main").hidden = true;
    $("next").hidden = true;
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const samples = await api("/api/samples").catch(() => []);
  if (samples.includes("jump_1") && samples.includes("jump_2")) {
    $("sample").hidden = false;
    $("sample").onclick = loadSample;
  }
}

init();
