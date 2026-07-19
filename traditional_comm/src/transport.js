const { setTimeout: delay } = require('node:timers/promises');

class TransportAdapter {
  async healthCheck() {
    return { online: true, transport: this.constructor.name };
  }

  async sendPayload() {
    throw new Error('TransportAdapter.sendPayload() must be implemented');
  }
}

class LoopbackTransport extends TransportAdapter {
  constructor({ chunkSize = 16 * 1024, delayMs = 0, lossRate = 0 } = {}) {
    super();
    if (!Number.isInteger(chunkSize) || chunkSize <= 0) {
      throw new Error('chunkSize must be a positive integer');
    }
    if (delayMs < 0 || lossRate < 0 || lossRate >= 1) {
      throw new Error('delayMs must be >= 0 and lossRate must be in [0, 1)');
    }
    this.chunkSize = chunkSize;
    this.delayMs = delayMs;
    this.lossRate = lossRate;
  }

  async sendPayload(payload, metadata = {}) {
    if (!Buffer.isBuffer(payload)) {
      throw new TypeError('LoopbackTransport payload must be a Buffer');
    }

    const start = process.hrtime.bigint();
    const chunks = [];
    let lostChunks = 0;

    for (let offset = 0; offset < payload.length; offset += this.chunkSize) {
      const chunk = payload.subarray(offset, Math.min(offset + this.chunkSize, payload.length));
      if (this.delayMs > 0) await delay(this.delayMs);
      if (this.lossRate > 0 && Math.random() < this.lossRate) {
        lostChunks += 1;
        continue;
      }
      chunks.push(Buffer.from(chunk));
    }

    const received = Buffer.concat(chunks);
    const elapsedMs = Number(process.hrtime.bigint() - start) / 1e6;
    const seconds = Math.max(elapsedMs / 1000, 1e-9);
    const averageMbps = received.length * 8 / seconds / 1e6;
    const stats = {
      transport: 'loopback',
      run_id: metadata.run_id || null,
      sent_bytes: payload.length,
      received_bytes: received.length,
      chunk_size: this.chunkSize,
      chunk_count: Math.ceil(payload.length / this.chunkSize),
      lost_chunks: lostChunks,
      loss_rate: this.lossRate,
      delay_ms_per_chunk: this.delayMs,
      elapsed_ms: Number(elapsedMs.toFixed(3)),
      average_throughput_mbps: Number(averageMbps.toFixed(3)),
      peak_throughput_mbps: Number(averageMbps.toFixed(3)),
    };
    return { payload: received, stats };
  }
}

class Task3Transport extends TransportAdapter {
  constructor(implementation) {
    super();
    if (!implementation || typeof implementation.sendPayload !== 'function') {
      throw new Error('Task3Transport requires an implementation with sendPayload()');
    }
    this.implementation = implementation;
  }

  async healthCheck() {
    if (typeof this.implementation.healthCheck === 'function') {
      return this.implementation.healthCheck();
    }
    return { online: true, transport: 'task3-adapter' };
  }

  async sendPayload(payload, metadata = {}) {
    return this.implementation.sendPayload(payload, metadata);
  }
}

module.exports = {
  TransportAdapter,
  LoopbackTransport,
  Task3Transport,
};
