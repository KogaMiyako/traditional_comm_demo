const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const { codecInfo, decodePayload, encodePayload } = require('./codecs');
const { parseTvid } = require('./samples');

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function sha256(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

function elapsedMs(start) {
  return Number(process.hrtime.bigint() - start) / 1e6;
}

function writeJson(filePath, value) {
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

function getOutputName(kind, runDir) {
  const extension = kind === 'text' ? 'txt' : kind === 'image' ? 'ppm' : 'tvid';
  return path.join(runDir, `output.${extension}`);
}

function createRunId(kind) {
  return `traditional-${kind}-${Date.now()}-${crypto.randomBytes(3).toString('hex')}`;
}

function validateDecoded(kind, buffer) {
  if (kind === 'text') {
    buffer.toString('utf8');
    return { valid: true, details: {} };
  }
  if (kind === 'image') {
    const header = buffer.subarray(0, 2).toString('ascii');
    return { valid: header === 'P6', details: { format: header } };
  }
  const parsed = parseTvid(buffer);
  return { valid: true, details: parsed };
}

async function runOne({ kind, inputPath, runsDir, transport, task = {}, runId: providedRunId }) {
  const runId = providedRunId || createRunId(kind);
  const runDir = path.join(runsDir, runId);
  ensureDir(runDir);

  const input = fs.readFileSync(inputPath);
  const inputHash = sha256(input);
  const startedAt = new Date().toISOString();

  const encodeStart = process.hrtime.bigint();
  const encoded = encodePayload(kind, input);
  const encodeMs = elapsedMs(encodeStart);

  const transportStart = process.hrtime.bigint();
  const transmitted = await transport.sendPayload(encoded.payload, {
    run_id: runId,
    mode: 'traditional',
    sample_id: path.basename(inputPath),
    task_id: task.task_id || null,
    codec: encoded.codec,
    container: encoded.container,
    payload_size: encoded.payload.length,
  });
  const transportMs = elapsedMs(transportStart);

  const decodeStart = process.hrtime.bigint();
  const output = decodePayload(kind, transmitted.payload);
  const decodeMs = elapsedMs(decodeStart);
  const validation = validateDecoded(kind, output);

  const outputPath = getOutputName(kind, runDir);
  fs.writeFileSync(outputPath, output);

  const outputHash = sha256(output);
  const contentMatch = inputHash === outputHash;
  const endToEndMs = encodeMs + transportMs + decodeMs;
  const inputBytes = input.length;
  const encodedBytes = encoded.payload.length;
  const dataReduction = inputBytes === 0 ? 0 : (inputBytes - encodedBytes) / inputBytes;
  const memory = process.memoryUsage();
  const cpu = process.cpuUsage();

  const config = {
    run_id: runId,
    mode: 'traditional',
    media_type: kind,
    input_path: path.resolve(inputPath),
    input_sha256: inputHash,
    task,
    codec: codecInfo(kind),
    transport: 'loopback-or-adapter',
    started_at: startedAt,
    finished_at: new Date().toISOString(),
  };
  const metrics = {
    run_id: runId,
    mode: 'traditional',
    media_type: kind,
    input_bytes: inputBytes,
    encoded_payload_bytes: encodedBytes,
    actual_sent_bytes: transmitted.stats.sent_bytes,
    actual_received_bytes: transmitted.stats.received_bytes,
    data_reduction_ratio: Number(dataReduction.toFixed(6)),
    encode_time_ms: Number(encodeMs.toFixed(3)),
    transport_time_ms: Number(transportMs.toFixed(3)),
    decode_time_ms: Number(decodeMs.toFixed(3)),
    end_to_end_latency_ms: Number(endToEndMs.toFixed(3)),
    average_throughput_mbps: transmitted.stats.average_throughput_mbps,
    peak_throughput_mbps: transmitted.stats.peak_throughput_mbps,
    quality: { psnr: null, ssim: null, lpips: null },
    task: { content_match: contentMatch ? 1 : 0, output_valid: validation.valid ? 1 : 0 },
    resource: {
      rss_bytes: memory.rss,
      heap_used_bytes: memory.heapUsed,
      cpu_user_ms: Math.round(cpu.user / 1000),
      cpu_system_ms: Math.round(cpu.system / 1000),
      gpu_usage: null,
    },
    status: contentMatch && validation.valid ? 'completed' : 'failed',
  };

  writeJson(path.join(runDir, 'config.json'), config);
  writeJson(path.join(runDir, 'metrics.json'), metrics);
  writeJson(path.join(runDir, 'transport.json'), transmitted.stats);
  writeJson(path.join(runDir, 'result.json'), {
    run_id: runId,
    output_path: outputPath,
    output_sha256: outputHash,
    content_match: contentMatch,
    validation,
  });
  fs.writeFileSync(path.join(runDir, 'encoded_payload.bin'), encoded.payload);

  return { runId, runDir, kind, metrics, outputPath };
}

async function runAll({ samplesDir, runsDir, transport, task = {} }) {
  ensureDir(runsDir);
  const inputs = {
    text: path.join(samplesDir, 'sample.txt'),
    image: path.join(samplesDir, 'sample.ppm'),
    video: path.join(samplesDir, 'sample.tvid'),
  };
  for (const inputPath of Object.values(inputs)) {
    if (!fs.existsSync(inputPath)) {
      throw new Error(`Missing sample: ${inputPath}`);
    }
  }
  const results = [];
  for (const [kind, inputPath] of Object.entries(inputs)) {
    results.push(await runOne({ kind, inputPath, runsDir, transport, task }));
  }
  return results;
}

module.exports = {
  runOne,
  runAll,
  createRunId,
  sha256,
};
