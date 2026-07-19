const fs = require('node:fs');
const path = require('node:path');

const { generateSamples } = require('./samples');
const { LoopbackTransport } = require('./transport');
const { runAll } = require('./runner');

const root = path.resolve(__dirname, '..');
const defaultSamplesDir = path.join(root, 'samples');
const defaultRunsDir = path.join(root, 'runs');

function getOption(name, fallback) {
  const prefix = `--${name}=`;
  const value = process.argv.find(arg => arg.startsWith(prefix));
  return value ? value.slice(prefix.length) : fallback;
}

function printHelp() {
  console.log(`Traditional communication demo\n\nCommands:\n  demo               Generate samples and run text/image/video locally\n  generate-samples   Generate the three smoke-test samples\n  run                Run all generated samples\n\nOptions:\n  --samples=<dir>    Sample directory\n  --runs=<dir>       Run output directory\n  --chunk-size=<n>   Loopback chunk size in bytes\n  --delay-ms=<n>     Delay per chunk\n  --loss-rate=<n>    Deterministic smoke-test setting; 0 means no loss\n`);
}

async function main() {
  const command = process.argv[2] || 'help';
  const samplesDir = path.resolve(getOption('samples', defaultSamplesDir));
  const runsDir = path.resolve(getOption('runs', defaultRunsDir));
  const chunkSize = Number(getOption('chunk-size', 16 * 1024));
  const delayMs = Number(getOption('delay-ms', 0));
  const lossRate = Number(getOption('loss-rate', 0));

  if (command === 'help' || command === '--help') {
    printHelp();
    return;
  }

  if (command === 'generate-samples' || command === 'demo') {
    const generated = generateSamples(samplesDir);
    console.log(`Generated samples in ${samplesDir}`);
    console.log(generated);
  }

  if (command === 'generate-samples') return;
  if (command !== 'run' && command !== 'demo') {
    printHelp();
    process.exitCode = 1;
    return;
  }

  if (!fs.existsSync(samplesDir)) {
    throw new Error(`Sample directory does not exist: ${samplesDir}`);
  }

  const transport = new LoopbackTransport({ chunkSize, delayMs, lossRate });
  const results = await runAll({
    samplesDir,
    runsDir,
    transport,
    task: { task_id: 'smoke-test', task_type: 'reconstruction', output_type: 'reconstruction' },
  });
  console.table(results.map(result => ({
    run_id: result.runId,
    media: result.kind,
    status: result.metrics.status,
    input_bytes: result.metrics.input_bytes,
    payload_bytes: result.metrics.encoded_payload_bytes,
    latency_ms: result.metrics.end_to_end_latency_ms,
    throughput_mbps: result.metrics.average_throughput_mbps,
    content_match: result.metrics.task.content_match,
  })));
  fs.writeFileSync(path.join(runsDir, 'latest_summary.json'), `${JSON.stringify({
    generated_at: new Date().toISOString(),
    mode: 'traditional',
    transport: 'loopback',
    results: results.map(result => result.metrics),
  }, null, 2)}\n`, 'utf8');
  console.log(`Run artifacts saved in ${runsDir}`);
}

main().catch(error => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
