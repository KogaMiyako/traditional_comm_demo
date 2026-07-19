const state = { runId: null, timer: null, samples: [] };

const $ = (id) => document.getElementById(id);

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

function formatBytes(value) {
  if (value === null || value === undefined) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(2)} KB`;
  return `${(value / 1024 / 1024).toFixed(2)} MB`;
}

function formatValue(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}

function setHealth(online, message) {
  $("health").textContent = message;
  $("health").className = `health-pill ${online ? "online" : "offline"}`;
}

function updateTransportFields() {
  const tcp = $("transport").value === "lan-tcp";
  document.querySelectorAll(".tcp-field").forEach((element) => element.classList.toggle("hidden", !tcp));
  $("delay-field").classList.toggle("hidden", tcp);
  $("loss-field").classList.toggle("hidden", tcp);
  $("command-hint").textContent = tcp ? "请先在接收端启动 tcp-receive" : "默认使用 LoopbackTransport";
}

function fillSamples(samples) {
  state.samples = samples;
  const select = $("sample");
  select.replaceChildren();
  for (const sample of samples) {
    const option = document.createElement("option");
    option.value = sample.sample_id;
    option.textContent = `${sample.sample_id} · ${sample.media_type} · ${formatBytes(sample.bytes)}`;
    option.dataset.kind = sample.media_type;
    select.appendChild(option);
  }
  if (samples.length) {
    $("kind").value = samples[0].media_type;
  }
}

function addEvent(event) {
  const list = $("events");
  const item = document.createElement("li");
  const time = event.time ? new Date(event.time).toLocaleTimeString() : "";
  item.innerHTML = `<span class="event-dot"></span><div><strong>${event.phase || "event"}</strong><span>${event.message || ""}</span><small>${time} · ${event.progress ?? 0}%</small></div>`;
  list.appendChild(item);
  while (list.children.length > 12) list.removeChild(list.firstChild);
}

function renderStatus(status) {
  $("run-id").textContent = status.run_id || "尚未运行";
  $("status-label").textContent = status.status || "待机";
  $("status-label").className = `status-badge ${status.status || ""}`;
  $("phase").textContent = status.message || status.phase || "等待任务";
  const progress = Math.max(0, Math.min(100, Number(status.progress || 0)));
  $("progress").style.width = `${progress}%`;
  $("progress-text").textContent = `${progress}%`;
  $("cancel").disabled = !status.run_id || ["completed", "failed", "cancelled"].includes(status.status);
}

function flattenMetrics(metrics) {
  return [
    ["编码格式", `${metrics.codec || "—"} / ${metrics.container || "—"}`],
    ["原始输入大小", formatBytes(metrics.input_bytes)],
    ["编码载荷大小", formatBytes(metrics.encoded_payload_bytes)],
    ["实际链路总字节", formatBytes(metrics.actual_link_total_bytes)],
    ["数据量降幅", metrics.data_reduction_ratio == null ? "—" : `${(metrics.data_reduction_ratio * 100).toFixed(2)}%`],
    ["编码耗时", `${formatValue(metrics.encode_time_ms)} ms`],
    ["传输耗时", `${formatValue(metrics.transport_time_ms)} ms`],
    ["解码耗时", `${formatValue(metrics.decode_time_ms)} ms`],
    ["端到端时延", `${formatValue(metrics.end_to_end_latency_ms)} ms`],
    ["平均吞吐", `${formatValue(metrics.average_throughput_mbps)} Mbps`],
    ["PSNR", metrics.quality ? `${formatValue(metrics.quality.psnr)} dB` : "—"],
    ["输出有效", metrics.task ? formatValue(metrics.task.output_valid) : "—"],
    ["接收端解码", formatValue(metrics.receiver_decode_valid)],
  ];
}

function renderMetrics(metrics) {
  if (!metrics) return;
  const cards = [
    ["端到端时延", `${formatValue(metrics.end_to_end_latency_ms)} ms`, "latency"],
    ["编码载荷", formatBytes(metrics.encoded_payload_bytes), "payload"],
    ["平均吞吐", `${formatValue(metrics.average_throughput_mbps)} Mbps`, "throughput"],
    ["PSNR", metrics.quality?.psnr == null ? "—" : `${metrics.quality.psnr} dB`, "quality"],
  ];
  $("metric-cards").replaceChildren(...cards.map(([label, value, tone]) => {
    const card = document.createElement("div");
    card.className = `metric-card ${tone}`;
    card.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
    return card;
  }));
  const table = document.createElement("div");
  table.className = "metric-table";
  for (const [label, value] of flattenMetrics(metrics)) {
    const row = document.createElement("div");
    row.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
    table.appendChild(row);
  }
  $("metric-table").replaceWith(table);
  table.id = "metric-table";
}

function fileUrl(runId, absolutePath) {
  if (!absolutePath) return null;
  const name = absolutePath.replaceAll("\\", "/").split("/").pop();
  return `/api/runs/${encodeURIComponent(runId)}/files/${encodeURIComponent(name)}`;
}

function renderResult(runId, result) {
  if (!result) return;
  const outputUrl = fileUrl(runId, result.output_path);
  const preview = $("preview");
  preview.className = "preview";
  preview.replaceChildren();
  if (outputUrl && outputUrl.endsWith(".jpg")) {
    const image = document.createElement("img");
    image.src = outputUrl;
    image.alt = "接收端图片输出";
    preview.appendChild(image);
  } else if (outputUrl && outputUrl.endsWith(".mp4")) {
    const video = document.createElement("video");
    video.src = outputUrl;
    video.controls = true;
    preview.appendChild(video);
  } else {
    preview.textContent = "文字结果已生成，可从结果文件查看。";
  }
  const files = $("result-files");
  files.replaceChildren();
  for (const [label, path] of [["正式输出", result.output_path], ["编码载荷", result.encoded_path], ["解码结果", result.decoded_path]]) {
    if (!path) continue;
    const link = document.createElement("a");
    link.href = fileUrl(runId, path);
    link.textContent = `${label} · ${path.replaceAll("\\", "/").split("/").pop()}`;
    link.target = "_blank";
    files.appendChild(link);
  }
}

async function refreshEvents(runId) {
  const data = await request(`/api/runs/${encodeURIComponent(runId)}/events`);
  $("events").replaceChildren();
  data.events.forEach(addEvent);
}

async function refreshRun(runId) {
  try {
    const status = await request(`/api/runs/${encodeURIComponent(runId)}/status`);
    renderStatus(status);
    await refreshEvents(runId);
    if (["completed", "failed"].includes(status.status)) {
      const [metrics, result] = await Promise.all([
        request(`/api/runs/${encodeURIComponent(runId)}/metrics`),
        request(`/api/runs/${encodeURIComponent(runId)}/result`),
      ]);
      renderMetrics(metrics.metrics);
      renderResult(runId, result.result);
      clearInterval(state.timer);
      state.timer = null;
    }
    await refreshRuns();
  } catch (error) {
    $("phase").textContent = error.message;
  }
}

async function refreshRuns() {
  const data = await request("/api/runs");
  const list = $("runs-list");
  list.replaceChildren();
  if (!data.runs.length) {
    list.className = "runs-list empty";
    list.textContent = "暂无运行记录";
    return;
  }
  list.className = "runs-list";
  for (const run of data.runs) {
    const item = document.createElement("button");
    item.className = "run-item";
    item.innerHTML = `<strong>${run.run_id}</strong><span>${run.kind} · ${run.status} · ${run.transport}</span>`;
    item.onclick = () => {
      state.runId = run.run_id;
      refreshRun(run.run_id);
    };
    list.appendChild(item);
  }
}

async function startRun() {
  $("start").disabled = true;
  $("events").replaceChildren();
  $("metric-cards").replaceChildren();
  $("preview").className = "preview empty";
  $("preview").textContent = "运行中…";
  const config = {
    kind: $("kind").value,
    sample_id: $("sample").value,
    transport: $("transport").value,
    delay_ms: Number($("delay-ms").value || 0),
    loss_rate: Number($("loss-rate").value || 0),
    host: $("tcp-host").value,
    port: Number($("tcp-port").value || 5000),
    task: { task_id: "web-demo", task_type: "reconstruction", output_type: "reconstruction" },
  };
  try {
    const data = await request("/api/runs/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    });
    state.runId = data.run_id;
    renderStatus(data);
    state.timer = setInterval(() => refreshRun(state.runId), 600);
    await refreshRun(state.runId);
  } catch (error) {
    $("phase").textContent = error.message;
  } finally {
    $("start").disabled = false;
  }
}

async function cancelRun() {
  if (!state.runId) return;
  await request(`/api/runs/${encodeURIComponent(state.runId)}/cancel`, { method: "POST", body: "{}" });
  await refreshRun(state.runId);
}

async function init() {
  try {
    const health = await request("/api/health");
    setHealth(health.online, "Web 服务在线");
    const samples = await request("/api/samples");
    fillSamples(samples.samples);
    await refreshRuns();
  } catch (error) {
    setHealth(false, error.message);
  }
  $("transport").addEventListener("change", updateTransportFields);
  $("kind").addEventListener("change", () => {
    const sample = state.samples.find((item) => item.media_type === $("kind").value);
    if (sample) $("sample").value = sample.sample_id;
  });
  $("sample").addEventListener("change", () => {
    const sample = state.samples.find((item) => item.sample_id === $("sample").value);
    if (sample) $("kind").value = sample.media_type;
  });
  $("start").addEventListener("click", startRun);
  $("cancel").addEventListener("click", cancelRun);
  $("refresh-runs").addEventListener("click", refreshRuns);
  updateTransportFields();
}

init();
