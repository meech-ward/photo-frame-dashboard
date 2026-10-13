import { describe, expect, it } from 'vitest';
import { crc32, deflateSync, inflateSync } from 'node:zlib';
import { coalescePNGIDAT, MAX_BADGE_PNG_BYTES } from '../src/badge-png';

const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
const header = Buffer.alloc(13);
header.writeUInt32BE(2, 0); header.writeUInt32BE(2, 4);
header[8] = 8; header[9] = 6;
// Two unfiltered RGBA rows make the inflated bytes an exact pixel assertion.
const pixels = Buffer.from([0, 255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 0, 255, 255, 255, 255, 255, 255]);
const compressed = deflateSync(pixels);

function chunk(type: string, payload = Buffer.alloc(0)): Buffer {
  const result = Buffer.alloc(payload.length + 12);
  result.writeUInt32BE(payload.length);
  result.write(type, 4, 4, 'ascii');
  payload.copy(result, 8);
  result.writeUInt32BE(crc32(result.subarray(4, -4)), result.length - 4);
  return result;
}
function png(...chunks: Buffer[]): Uint8Array<ArrayBuffer> { return new Uint8Array(Buffer.concat([signature, ...chunks])); }
function chunks(bytes: Uint8Array): { type: string; payload: Buffer; crc: number; bytes: Buffer }[] {
  const source = Buffer.from(bytes);
  const result = [];
  for (let offset = 8; offset < source.length;) {
    const end = offset + source.readUInt32BE(offset) + 12;
    result.push({ type: source.toString('ascii', offset + 4, offset + 8), payload: source.subarray(offset + 8, end - 4), crc: source.readUInt32BE(end - 4), bytes: source.subarray(offset, end) });
    offset = end;
  }
  return result;
}
const ihdr = chunk('IHDR', header), iend = chunk('IEND');

describe('badge PNG chunk compatibility', () => {
  it('joins IDAT boundaries losslessly, writes a valid CRC and preserves every other chunk', () => {
    const before = chunk('tEXt', Buffer.from('Description\0Family photo'));
    const after = chunk('tEXt', Buffer.from('Author\0Our family'));
    const source = png(ihdr, before, chunk('IDAT', compressed.subarray(0, 5)), chunk('IDAT'), chunk('IDAT', compressed.subarray(5, 11)), chunk('IDAT', compressed.subarray(11)), after, iend);
    const sourceCopy = source.slice();
    const result = coalescePNGIDAT(source);
    const parsed = chunks(result);
    expect(parsed.map((entry) => entry.type)).toEqual(['IHDR', 'tEXt', 'IDAT', 'tEXt', 'IEND']);
    const data = parsed[2];
    expect(data.payload).toEqual(compressed);
    expect(inflateSync(data.payload)).toEqual(pixels);
    expect(data.crc).toBe(crc32(Buffer.concat([Buffer.from('IDAT'), compressed])));
    expect(parsed.filter((entry) => entry.type !== 'IDAT').map((entry) => entry.bytes)).toEqual([ihdr, before, after, iend]);
    expect(source).toEqual(sourceCopy);
    expect(result.length).toBe(source.length - 3 * 12);
  });

  it('passes a single IDAT through without changing or copying the PNG', () => {
    const source = png(ihdr, chunk('IDAT', compressed), iend);
    expect(coalescePNGIDAT(source)).toBe(source);
  });

  it.each([
    ['bad signature', new Uint8Array(40)],
    ['truncated header', png(ihdr).subarray(0, 20)],
    ['truncated data', png(ihdr, chunk('IDAT', compressed), iend).subarray(0, 35)],
    ['missing header', png(chunk('IDAT', compressed), iend)],
    ['repeated header', png(ihdr, ihdr, chunk('IDAT', compressed), iend)],
    ['no image data', png(ihdr, iend)],
    ['empty image data', png(ihdr, chunk('IDAT'), iend)],
    ['nonconsecutive image data', png(ihdr, chunk('IDAT', compressed.subarray(0, 5)), chunk('tEXt'), chunk('IDAT', compressed.subarray(5)), iend)],
    ['missing end', png(ihdr, chunk('IDAT', compressed))],
    ['invalid end payload', png(ihdr, chunk('IDAT', compressed), chunk('IEND', Buffer.from([0])))],
    ['trailing bytes', png(ihdr, chunk('IDAT', compressed), iend, Buffer.from([0]))],
    ['oversized output', png(ihdr, chunk('IDAT', Buffer.alloc(MAX_BADGE_PNG_BYTES)), iend)],
  ] as const)('refuses %s rather than emitting an unreadable image', (_reason, bytes) => {
    expect(() => coalescePNGIDAT(bytes)).toThrow('Could not prepare a valid badge PNG.');
  });
});
