const fs = require('node:fs');
const path = require('node:path');

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function createRgbFrame(width, height, frameIndex = 0, totalFrames = 1) {
  const pixels = Buffer.alloc(width * height * 3);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const offset = (y * width + x) * 3;
      const phase = Math.floor((frameIndex / Math.max(totalFrames, 1)) * 255);
      pixels[offset] = (x * 255 / Math.max(width - 1, 1) + phase) % 256;
      pixels[offset + 1] = (y * 255 / Math.max(height - 1, 1) + phase * 2) % 256;
      pixels[offset + 2] = ((x + y + phase) * 3) % 256;
    }
  }
  return pixels;
}

function createPpm(width, height, frameIndex = 0, totalFrames = 1) {
  const header = Buffer.from(`P6\n${width} ${height}\n255\n`, 'ascii');
  return Buffer.concat([header, createRgbFrame(width, height, frameIndex, totalFrames)]);
}

function createTvid(width, height, fps, frameCount) {
  const header = Buffer.from(`TVID1\n${width} ${height} ${fps} ${frameCount}\n`, 'ascii');
  const frames = [];
  for (let frame = 0; frame < frameCount; frame += 1) {
    frames.push(createRgbFrame(width, height, frame, frameCount));
  }
  return Buffer.concat([header, ...frames]);
}

function parseTvid(buffer) {
  const firstBreak = buffer.indexOf(0x0a);
  const secondBreak = buffer.indexOf(0x0a, firstBreak + 1);
  if (firstBreak < 0 || secondBreak < 0) {
    throw new Error('Invalid TVID header');
  }
  const magic = buffer.subarray(0, firstBreak).toString('ascii');
  if (magic !== 'TVID1') {
    throw new Error(`Unsupported TVID magic: ${magic}`);
  }
  const [width, height, fps, frameCount] = buffer
    .subarray(firstBreak + 1, secondBreak)
    .toString('ascii')
    .trim()
    .split(/\s+/)
    .map(Number);
  const frameSize = width * height * 3;
  const data = buffer.subarray(secondBreak + 1);
  const expectedBytes = frameSize * frameCount;
  if (!Number.isInteger(width) || !Number.isInteger(height) || !Number.isInteger(frameCount) ||
      width <= 0 || height <= 0 || frameCount <= 0 || data.length !== expectedBytes) {
    throw new Error('Invalid TVID frame data');
  }
  return { width, height, fps, frameCount, frameSize, headerBytes: secondBreak + 1 };
}

function generateSamples(outputDir) {
  ensureDir(outputDir);

  const textPath = path.join(outputDir, 'sample.txt');
  fs.writeFileSync(textPath, [
    '传统通信本地测试样本',
    'This is a small UTF-8 text sample for the local baseline.',
    '内容2：常规通信链路先在单系统内跑通。',
  ].join('\n') + '\n', 'utf8');

  const imagePath = path.join(outputDir, 'sample.ppm');
  fs.writeFileSync(imagePath, createPpm(160, 90));

  const videoPath = path.join(outputDir, 'sample.tvid');
  fs.writeFileSync(videoPath, createTvid(160, 90, 10, 12));

  return { textPath, imagePath, videoPath };
}

module.exports = {
  createPpm,
  createTvid,
  parseTvid,
  generateSamples,
};
