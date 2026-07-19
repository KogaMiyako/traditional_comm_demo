const state = {
  runId: null,
  timer: null,
  receiverTimer: null,
  samples: [],
};

const $ = (id) => document.getElementById(id);
const terminalStatuses = ["completed", "failed", "cancelled"];

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

function formatBytes(value) {
  if (value === null || value === undefined) return "-";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(2)} KB`;
  return `${(value / 1024 / 1024).toFixed(2)} MB`;
}

function formatValue(value) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}

function basename(path) {
  return path ? String(path).replaceAll("\\", "/").split("/").pop() : "";
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
  $("command-hint").textContent = tcp
    ? "先在接收端 Web 页面点击“启动接收”"
    : "默认使用本地回环，不需要另一台电脑";
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
  if (samples.length) $("kind").value = samples[0].media_type;
}

function addEvent(event) {
  const list = $("events");
  const item = document.createElement("li");
  const dot = document.createElement("span");
  dot.className = "event-dot";
  const content = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = event.phase || "event";
  const message = document.createElement("span");
  message.textContent = event.message || "";
  const detail = document.createElement("small");
  const time = event.time ? new Date(event.time).toLocaleTimeString() : "";
  detail.textContent = `${time} · ${event.progress ?? 0}%`;
  content.append(title, message, detail);
  item.append(dot, content);
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
  $("cancel").disabled = !status.run_id || terminalStatuses.includes(status.status);
  $("start").disabled = Boolean(status.run_id) && !terminalStatuses.includes(status.status);
}

function flattenMetrics(metrics) {
  return [
    ["编码格式", `${metrics.codec || "-"} / ${metrics.container || "-"}`],
    ["原始输入大小", formatBytes(metrics.input_bytes)],
    ["编码载荷大小", formatBytes(metrics.encoded_payload_bytes)],
    ["实际链路总字节", formatBytes(metrics.actual_link_total_bytes)],
    ["数据量降幅", metrics.data_reduction_ratio == null ? "-" : `${(metrics.data_reduction_ratio * 100).toFixed(2)}%`],
    ["编码耗时", `${formatValue(metrics.encode_time_ms)} ms`],
    ["传输耗时", `${formatValue(metrics.transport_time_ms)} ms`],
    ["解码耗时", `${formatValue(metrics.decode_time_ms)} ms`],
    ["端到端时延", `${formatValue(metrics.end_to_end_latency_ms)} ms`],
    ["平均吞吐", `${formatValue(metrics.average_throughput_mbps)} Mbps`],
    ["PSNR", metrics.quality?.psnr == null ? "-" : `${formatValue(metrics.quality.psnr)} dB`],
    ["输出有效", metrics.task ? formatValue(metrics.task.output_valid) : "-"],
    ["接收端解码", formatValue(metrics.receiver_decode_valid)],
  ];
}

function renderMetrics(metrics) {
  if (!metrics) return;
  const cards = [
    ["端到端时延", `${formatValue(metrics.end_to_end_latency_ms)} ms`, "latency"],
    ["编码载荷", formatBytes(metrics.encoded_payload_bytes), "payload"],
    ["平均吞吐", `${formatValue(metrics.average_throughput_mbps)} Mbps`, "throughput"],
    ["PSNR", metrics.quality?.psnr == null ? "-" : `${metrics.quality.psnr} dB`, "quality"],
  ];
  $("metric-cards").replaceChildren(...cards.map(([label, value, tone]) => {
    const card = document.createElement("div");
    card.className = `metric-card ${tone}`;
    const title = document.createElement("span");
    title.textContent = label;
    const number = document.createElement("strong");
    number.textContent = value;
    card.append(title, number);
    return card;
  }));
  const table = document.createElement("div");
  table.className = "metric-table";
  for (const [label, value] of flattenMetrics(metrics)) {
    const row = document.createElement("div");
    const name = document.createElement("span");
    name.textContent = label;
    const valueNode = document.createElement("strong");
    valueNode.textContent = value;
    row.append(name, valueNode);
    table.appendChild(row);
  }
  $("metric-table").replaceWith(table);
  table.id = "metric-table";
}

function fileUrl(runId, path) {
  const name = basename(path);
  return name ? `/api/runs/${encodeURIComponent(runId)}/files/${encodeURIComponent(name)}` : null;
}

function renderPreview(preview, outputUrl, emptyText) {
  preview.className = "preview";
  preview.replaceChildren();
  if (outputUrl && /\.(jpg|jpeg)$/i.test(outputUrl)) {
    const image = document.createElement("img");
    image.src = outputUrl;
    image.alt = "图片输出";
    preview.appendChild(image);
  } else if (outputUrl && /\.mp4$/i.test(outputUrl)) {
    const video = document.createElement("video");
    video.src = outputUrl;
    video.controls = true;
    video.setAttribute("aria-label", "视频输出");
    preview.appendChild(video);
  } else {
    preview.textContent = emptyText;
  }
}

function renderResult(runId, result) {
  if (!result) return;
  renderPreview($("preview"), fileUrl(runId, result.output_path), "文字结果已生成，可从结果文件查看。");
  const files = $("result-files");
  files.replaceChildren();
  for (const [label, path] of [["正式输出", result.output_path], ["编码载荷", result.encoded_path], ["解码结果", result.decoded_path]]) {
    if (!path) continue;
    const link = document.createElement("a");
    link.href = fileUrl(runId, path);
    link.textContent = `${label} · ${basename(path)}`;
    link.target = "_blank";
    files.appendChild(link);
  }
}

function receiverFileUrl(runId, path) {
  const name = basename(path);
  return name ? `/api/receiver/runs/${encodeURIComponent(runId)}/files/${encodeURIComponent(name)}` : null;
}

function renderReceiverResult(result) {
  if (!result) {
    $("receiver-preview").className = "preview empty";
    $("receiver-preview").textContent = "接收端收到文件后显示预览";
    $("receiver-result-table").className = "receiver-result-table empty";
    $("receiver-result-table").textContent = "暂无接收结果";
    $("receiver-files").replaceChildren();
    return;
  }
  renderPreview($("receiver-preview"), receiverFileUrl(result.run_id, result.output_path), "已收到文字载荷。");
  const table = $("receiver-result-table");
  table.className = "receiver-result-table";
  table.replaceChildren();
  for (const [label, value] of [
    ["运行编号", result.run_id],
    ["发送端", result.peer ? `${result.peer.host}:${result.peer.port}` : "-"],
    ["媒体/编码", `${result.media_type || "-"} / ${result.codec || "-"}`],
    ["接收字节", formatBytes(result.received_bytes)],
    ["SHA-256", result.sha256 || "-"],
    ["解码状态", result.receiver_decode_valid ? "成功" : `失败：${result.receiver_error || "未知错误"}`],
  ]) {
    const row = document.createElement("div");
    const name = document.createElement("span");
    name.textContent = label;
    const valueNode = document.createElement("strong");
    valueNode.textContent = value;
    row.append(name, valueNode);
    table.appendChild(row);
  }
  const files = $("receiver-files");
  files.replaceChildren();
  for (const [label, path] of [["接收载荷", result.received_path], ["输出文件", result.output_path], ["解码结果", result.decoded_path]]) {
    if (!path) continue;
    const link = document.createElement("a");
    link.href = receiverFileUrl(result.run_id, path);
    link.textContent = `${label} · ${basename(path)}`;
    link.target = "_blank";
    files.appendChild(link);
  }
}

function renderReceiverHistory(results) {
  const history = $("receiver-history");
  history.replaceChildren();
  for (const result of results.slice(0, 6)) {
    const item = document.createElement("button");
    item.className = "receiver-history-item";
    item.textContent = `${result.run_id} · ${result.receiver_decode_valid ? "解码成功" : "解码失败"}`;
    item.onclick = () => renderReceiverResult(result);
    history.appendChild(item);
  }
}

function renderReceiverStatus(status) {
  $("receiver-status").textContent = status.online ? "监听中" : (status.status || "未监听");
  $("receiver-status").className = `status-badge ${status.online ? "online" : "offline"}`;
  $("receiver-start").disabled = Boolean(status.online);
  $("receiver-stop").disabled = !status.online;
  $("receiver-address").textContent = status.address ? `${status.address[0]}:${status.address[1]}` : "尚未启动";
  $("receiver-count").textContent = formatValue(status.received_count || 0);
  const last = status.last_result;
  $("receiver-last").textContent = last
    ? `最近接收：${last.run_id || "未知"} · ${last.receiver_decode_valid ? "解码成功" : "解码失败"}`
    : "最近接收：暂无";
  if (status.last_error) $("receiver-hint").textContent = `接收端错误：${status.last_error}`;
}

async function refreshReceiver() {
  try {
    const [status, results] = await Promise.all([
      request("/api/receiver/status"),
      request("/api/receiver/results"),
    ]);
    renderReceiverStatus(status);
    renderReceiverHistory(results.results);
    if (results.results.length) renderReceiverResult(results.results[0]);
  } catch (error) {
    $("receiver-hint").textContent = `接收端状态读取失败：${error.message}`;
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
    if (terminalStatuses.includes(status.status)) {
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
    const title = document.createElement("strong");
    title.textContent = run.run_id;
    const detail = document.createElement("span");
    detail.textContent = `${run.kind} · ${run.status} · ${run.transport}`;
    item.append(title, detail);
    item.onclick = () => {
      state.runId = run.run_id;
      refreshRun(run.run_id);
    };
    list.appendChild(item);
  }
}

async function startRun() {
  if (!$("sample").value) return;
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
    $("start").disabled = false;
  }
}

async function cancelRun() {
  if (!state.runId) return;
  await request(`/api/runs/${encodeURIComponent(state.runId)}/cancel`, { method: "POST", body: "{}" });
  await refreshRun(state.runId);
}

async function startReceiver() {
  $("receiver-start").disabled = true;
  try {
    await request("/api/receiver/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        bind_host: $("receiver-bind").value.trim() || "0.0.0.0",
        port: Number($("receiver-port").value || 5000),
      }),
    });
    await refreshReceiver();
  } catch (error) {
    $("receiver-hint").textContent = `启动接收端失败：${error.message}`;
    $("receiver-start").disabled = false;
  }
}

async function stopReceiver() {
  try {
    await request("/api/receiver/stop", { method: "POST", body: "{}" });
    await refreshReceiver();
  } catch (error) {
    $("receiver-hint").textContent = `停止接收端失败：${error.message}`;
  }
}

async function init() {
  try {
    const health = await request("/api/health");
    setHealth(health.online, "Web 服务在线");
    const samples = await request("/api/samples");
    fillSamples(samples.samples);
    await Promise.all([refreshRuns(), refreshReceiver()]);
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
  $("receiver-start").addEventListener("click", startReceiver);
  $("receiver-stop").addEventListener("click", stopReceiver);
  $("refresh-runs").addEventListener("click", refreshRuns);
  updateTransportFields();
  state.receiverTimer = setInterval(refreshReceiver, 1000);
}

init();
