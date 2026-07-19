const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const { generateSamples, parseTvid } = require('../src/samples');
const { LoopbackTransport } = require('../src/transport');
const { runAll } = require('../src/runner');
const { TraditionalCommunicationController } = require('../src/controller');

test('local traditional communication smoke test covers text, image, and video', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'traditional-comm-'));
  const samplesDir = path.join(tempRoot, 'samples');
  const runsDir = path.join(tempRoot, 'runs');
  generateSamples(samplesDir);

  const video = fs.readFileSync(path.join(samplesDir, 'sample.tvid'));
  const videoInfo = parseTvid(video);
  assert.equal(videoInfo.frameCount, 12);
  assert.equal(videoInfo.width, 160);

  const results = await runAll({
    samplesDir,
    runsDir,
    transport: new LoopbackTransport({ chunkSize: 128 }),
  });

  assert.deepEqual(results.map(result => result.kind), ['text', 'image', 'video']);
  for (const result of results) {
    assert.equal(result.metrics.status, 'completed');
    assert.equal(result.metrics.task.content_match, 1);
    assert.equal(result.metrics.task.output_valid, 1);
    assert.ok(fs.existsSync(result.outputPath));
    assert.ok(fs.existsSync(path.join(result.runDir, 'metrics.json')));
    assert.ok(fs.existsSync(path.join(result.runDir, 'transport.json')));
  }
});

test('controller exposes mode switching, start, status, performance, and result interfaces', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'traditional-controller-'));
  const samplesDir = path.join(tempRoot, 'samples');
  const runsDir = path.join(tempRoot, 'runs');
  const samples = generateSamples(samplesDir);
  const controller = new TraditionalCommunicationController({
    runsDir,
    transport: new LoopbackTransport({ chunkSize: 64 }),
  });

  assert.equal((await controller.healthCheck()).online, true);
  assert.deepEqual(controller.switchMode('traditional'), { mode: 'traditional' });
  const started = await controller.startRun({ kind: 'text', inputPath: samples.textPath });
  assert.match(started.run_id, /^traditional-text-/);
  const result = await controller.waitForRun(started.run_id);
  assert.equal(result.metrics.status, 'completed');
  assert.equal(controller.getStatus(started.run_id).status, 'completed');
  assert.equal(controller.getPerformance(started.run_id).task.content_match, 1);
  assert.equal(controller.getResult(started.run_id).content_match, true);
});
