const fs = require('node:fs');
const path = require('node:path');

const { createRunId, runOne } = require('./runner');

class TraditionalCommunicationController {
  constructor({ runsDir, transport }) {
    if (!runsDir) throw new Error('runsDir is required');
    if (!transport) throw new Error('transport is required');
    this.runsDir = path.resolve(runsDir);
    this.transport = transport;
    this.mode = 'traditional';
    this.states = new Map();
  }

  async healthCheck() {
    return this.transport.healthCheck();
  }

  switchMode(mode) {
    if (!['traditional', 'semantic'].includes(mode)) {
      throw new Error(`Unsupported mode: ${mode}`);
    }
    this.mode = mode;
    return { mode: this.mode };
  }

  async startRun({ kind, inputPath, task = {} }) {
    if (this.mode !== 'traditional') {
      throw new Error('This controller only executes traditional mode; semantic mode needs its own adapter');
    }
    const runId = createRunId(kind);
    const state = {
      run_id: runId,
      mode: this.mode,
      status: 'preparing',
      kind,
      input_path: path.resolve(inputPath),
    };
    this.states.set(runId, state);

    const promise = runOne({
      runId,
      kind,
      inputPath,
      runsDir: this.runsDir,
      transport: this.transport,
      task,
    }).then(result => {
      this.states.set(runId, { ...state, status: result.metrics.status, result });
      return result;
    }).catch(error => {
      this.states.set(runId, { ...state, status: 'failed', error: error.message });
      throw error;
    });
    state.status = 'running';
    state.promise = promise;
    return { run_id: runId, status: state.status };
  }

  async waitForRun(runId) {
    const state = this.states.get(runId);
    if (!state) throw new Error(`Unknown run_id: ${runId}`);
    if (state.promise) return state.promise;
    return state.result;
  }

  getStatus(runId) {
    const state = this.states.get(runId);
    if (!state) throw new Error(`Unknown run_id: ${runId}`);
    return {
      run_id: runId,
      mode: state.mode,
      status: state.status,
      kind: state.kind,
      input_path: state.input_path,
      error: state.error || null,
    };
  }

  getPerformance(runId) {
    const state = this.states.get(runId);
    if (!state) throw new Error(`Unknown run_id: ${runId}`);
    if (!state.result) return { run_id: runId, status: state.status, metrics: null };
    return state.result.metrics;
  }

  getResult(runId) {
    const state = this.states.get(runId);
    if (!state) throw new Error(`Unknown run_id: ${runId}`);
    if (!state.result) return { run_id: runId, status: state.status, result: null };
    const resultPath = path.join(state.result.runDir, 'result.json');
    return JSON.parse(fs.readFileSync(resultPath, 'utf8'));
  }

  stopRun(runId) {
    const state = this.states.get(runId);
    if (!state) throw new Error(`Unknown run_id: ${runId}`);
    if (state.status === 'running' || state.status === 'preparing') {
      state.status = 'cancelled';
    }
    return this.getStatus(runId);
  }
}

module.exports = { TraditionalCommunicationController };
