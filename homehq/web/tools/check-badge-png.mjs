import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { inflateSync } from 'node:zlib';
import { chromium } from '@playwright/test';

const options = { '--web-url': 'http://127.0.0.1:5184/', '--input-type': 'image/png' };
for (let index = 2; index < process.argv.length; index += 2) {
  const key = process.argv[index];
  if (!['--web-url', '--runtime', '--input-type'].includes(key) || !process.argv[index + 1]) {
    throw new Error('Usage: node tools/check-badge-png.mjs --runtime RUNTIME_MJS [--web-url http://127.0.0.1:5184/] [--input-type image/png|image/jpeg|image/webp]');
  }
  options[key] = process.argv[index + 1];
}
if (!options['--runtime']) throw new Error('Pass --runtime with the native picovector MicroPython WASM loader.');
assert.ok(['image/png', 'image/jpeg', 'image/webp'].includes(options['--input-type']), 'Choose a supported source image MIME type.');
const webURL = new URL(options['--web-url']);
assert.equal(webURL.protocol, 'http:');
assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(webURL.hostname), 'The gate only uses a local Vite server.');
const runtime = resolve(options['--runtime']);
const provenance = JSON.parse(await readFile(resolve(dirname(runtime), 'provenance.json'), 'utf8'));
assert.equal(provenance.runtime, 'pimoroni-micropython-webassembly+picovector');
const expectedHash = provenance.artifacts?.['micropython.mjs']?.sha256;
assert.ok(expectedHash, 'The runtime must have a recorded artifact hash.');
assert.equal(createHash('sha256').update(await readFile(runtime)).digest('hex'), expectedHash);
const wasm = resolve(dirname(runtime), 'micropython.wasm');
assert.equal(createHash('sha256').update(await readFile(wasm)).digest('hex'), provenance.artifacts['micropython.wasm'].sha256);

function pngParts(bytes) {
  assert.equal(bytes.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  const chunks = [];
  let offset = 8;
  while (offset < bytes.length) {
    const length = bytes.readUInt32BE(offset);
    assert.ok(offset + length + 12 <= bytes.length, 'Truncated PNG chunk.');
    chunks.push({ type: bytes.toString('ascii', offset + 4, offset + 8), data: bytes.subarray(offset + 8, offset + 8 + length) });
    offset += length + 12;
  }
  assert.equal(offset, bytes.length);
  const header = chunks.find((chunk) => chunk.type === 'IHDR').data;
  assert.equal(header.readUInt32BE(0), 320);
  assert.equal(header.readUInt32BE(4), 240);
  assert.equal(header[8], 8);
  assert.ok([2, 6].includes(header[9]), 'Expected an opaque RGB or RGBA browser PNG.');
  assert.equal(header[12], 0);
  const idats = chunks.filter((chunk) => chunk.type === 'IDAT');
  return { chunks, idats, stream: Buffer.concat(idats.map((chunk) => chunk.data)), channels: header[9] === 6 ? 4 : 3 };
}

function pixels(parts) {
  const raw = inflateSync(parts.stream);
  const stride = 320 * parts.channels;
  assert.equal(raw.length, 240 * (stride + 1));
  const decoded = Buffer.alloc(240 * stride);
  const paeth = (left, up, upperLeft) => {
    const estimate = left + up - upperLeft;
    const a = Math.abs(estimate - left), b = Math.abs(estimate - up), c = Math.abs(estimate - upperLeft);
    return a <= b && a <= c ? left : b <= c ? up : upperLeft;
  };
  for (let y = 0; y < 240; y++) {
    const source = y * (stride + 1), target = y * stride, filter = raw[source];
    assert.ok(filter <= 4, 'Unsupported PNG filter.');
    for (let x = 0; x < stride; x++) {
      const left = x >= parts.channels ? decoded[target + x - parts.channels] : 0;
      const up = y ? decoded[target + x - stride] : 0;
      const upperLeft = y && x >= parts.channels ? decoded[target + x - stride - parts.channels] : 0;
      const prediction = [0, left, up, Math.floor((left + up) / 2), paeth(left, up, upperLeft)][filter];
      decoded[target + x] = (raw[source + x + 1] + prediction) & 255;
    }
  }
  return decoded;
}

const browser = await chromium.launch({ headless: true });
let prepared, converted;
try {
  const page = await browser.newPage();
  // A blank local document avoids starting Auth or loading any household data.
  // Only the real upload function and its local Vite module dependencies run.
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== webURL.origin) return route.abort('blockedbyclient');
    if (url.pathname === '/__badge_png_gate') return route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Badge PNG codec gate</title>' });
    return route.continue();
  });
  await page.goto(new URL('/__badge_png_gate', webURL).href);
  const result = await page.evaluate(async (inputType) => {
    const { badgePNG } = await import('/src/backend.ts');
    const canvas = document.createElement('canvas');
    canvas.width = 320; canvas.height = 240;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Canvas unavailable.');
    const pixels = context.createImageData(320, 240);
    let random = 0x6d2b79f5;
    for (let offset = 0; offset < pixels.data.length; offset += 4) {
      // High entropy forces Chromium to split IDAT, reproducing the decoder's
      // failure without downloading, editing or retaining anyone's photograph.
      for (let channel = 0; channel < 3; channel++) {
        random ^= random << 13; random ^= random >>> 17; random ^= random << 5;
        pixels.data[offset + channel] = random & 255;
      }
      pixels.data[offset + 3] = 255;
    }
    context.putImageData(pixels, 0, 0);
    const source = await new Promise((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('Source encoding failed.')), inputType));
    if (source.type !== inputType) throw new Error('The browser did not encode the requested source format.');
    let prepared;
    const toBlob = HTMLCanvasElement.prototype.toBlob;
    // Capture the exact intermediate that badgePNG encodes before coalescing;
    // comparing it proves the fix changes container framing, never pixels.
    HTMLCanvasElement.prototype.toBlob = function (callback, ...args) {
      return toBlob.call(this, (blob) => { prepared = blob; callback(blob); }, ...args);
    };
    try {
      const converted = await badgePNG(new File([source], `synthetic-codec-test.${inputType.split('/')[1]}`, { type: inputType }));
      if (!prepared) throw new Error('Upload function did not encode its canvas.');
      return { prepared: Array.from(new Uint8Array(await prepared.arrayBuffer())), converted: Array.from(new Uint8Array(await converted.arrayBuffer())) };
    } finally {
      HTMLCanvasElement.prototype.toBlob = toBlob;
    }
  }, options['--input-type']);
  prepared = Buffer.from(result.prepared);
  converted = Buffer.from(result.converted);
} finally {
  await browser.close();
}

const before = pngParts(prepared), after = pngParts(converted);
assert.ok(before.idats.length > 1, 'The negative control must contain multiple IDAT chunks.');
assert.equal(after.idats.length, 1);
assert.ok(converted.length <= 327680, 'The fixed PNG exceeds the badge transfer limit.');
assert.deepEqual(after.stream, before.stream, 'Coalescing must preserve every compressed byte.');
assert.deepEqual(inflateSync(after.stream), inflateSync(before.stream), 'Inflated scanlines changed.');
assert.deepEqual(pixels(after), pixels(before), 'Decoded image pixels changed.');
assert.deepEqual(after.chunks.filter((chunk) => chunk.type !== 'IDAT'), before.chunks.filter((chunk) => chunk.type !== 'IDAT'), 'Non-image chunks changed.');

// The pinned module contains the real native C++ decoder; a JavaScript image
// decoder accepting both files would miss the specific hardware limitation.
process.argv[1] = 'homehq-badge-png-codec-gate';
const { loadMicroPython } = await import(pathToFileURL(runtime).href);
const output = [];
const mp = await loadMicroPython({ stdout: (line) => output.push(line), stderr: (line) => output.push(line) });
mp.FS.writeFile('/browser-multichunk.png', prepared);
mp.FS.writeFile('/badge-singlechunk.png', converted);
await mp.runPythonAsync(`
import json
from picovector import image
before_outcome = 'decoded'
try:
    image.load('/browser-multichunk.png')
except ValueError:
    before_outcome = 'ValueError'
# Failure depends on compressed data at the IDAT boundary. Lossy-source files
# can decode, so only the deterministic PNG-source regression must raise.
if ${options['--input-type'] === 'image/png' ? 'True' : 'False'}:
    assert before_outcome == 'ValueError', 'Native negative control unexpectedly decoded'
after = image.load('/badge-singlechunk.png')
assert after.width == 320 and after.height == 240, 'Native decoded dimensions differ'
print(json.dumps({'before': before_outcome, 'after': 'decoded', 'width': after.width, 'height': after.height}))
`);
const native = output.filter((line) => line.startsWith('{')).map((line) => JSON.parse(line));
assert.equal(native.length, 1, 'The native decoder did not report success.');
console.log(JSON.stringify({ ...native[0], input_type: options['--input-type'], browser_idat_chunks: before.idats.length, badge_idat_chunks: after.idats.length, browser_bytes: prepared.length, badge_bytes: converted.length, lossless: true, lossless_scope: 'PNG IDAT coalescing', native_runtime_sha256: expectedHash }));
