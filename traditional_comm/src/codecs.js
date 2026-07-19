const zlib = require('node:zlib');

function assertBuffer(value, label) {
  if (!Buffer.isBuffer(value)) {
    throw new TypeError(`${label} must be a Buffer`);
  }
}

function encodePayload(kind, input) {
  assertBuffer(input, 'input');

  switch (kind) {
    case 'text':
      return {
        codec: 'utf8',
        container: 'txt',
        payload: Buffer.from(input),
      };
    case 'image':
      return {
        codec: 'ppm-deflate',
        container: 'ppm',
        payload: zlib.deflateSync(input, { level: 6 }),
      };
    case 'video':
      return {
        codec: 'tvid-deflate',
        container: 'tvid',
        payload: zlib.deflateSync(input, { level: 6 }),
      };
    default:
      throw new Error(`Unsupported media kind: ${kind}`);
  }
}

function decodePayload(kind, payload) {
  assertBuffer(payload, 'payload');

  switch (kind) {
    case 'text':
      return Buffer.from(payload);
    case 'image':
    case 'video':
      return zlib.inflateSync(payload);
    default:
      throw new Error(`Unsupported media kind: ${kind}`);
  }
}

function codecInfo(kind) {
  switch (kind) {
    case 'text':
      return { codec: 'utf8', container: 'txt', lossless: true };
    case 'image':
      return { codec: 'ppm-deflate', container: 'ppm', lossless: true };
    case 'video':
      return { codec: 'tvid-deflate', container: 'tvid', lossless: true };
    default:
      throw new Error(`Unsupported media kind: ${kind}`);
  }
}

module.exports = {
  encodePayload,
  decodePayload,
  codecInfo,
};
