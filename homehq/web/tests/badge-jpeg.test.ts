import { describe, expect, it } from 'vitest';
import { validateBadgeJPEG } from '../src/badge-jpeg';

function segment(marker: number, data: number[]): number[] {
  return [0xff, marker, (data.length + 2) >>> 8, (data.length + 2) & 255, ...data];
}
const frame = [8, 0, 240, 1, 64, 3, 1, 0x11, 0, 2, 0x11, 1, 3, 0x11, 1];
const jpeg = (header = frame, marker = 0xc0): Uint8Array => new Uint8Array([0xff, 0xd8, ...segment(0xe0, [74, 70, 73, 70, 0]), ...segment(marker, header), 0xff, 0xd9]);

describe('prepared JPEG frame contract', () => {
  it('accepts an 8-bit, three-component baseline 320x240 frame after metadata', () => {
    expect(() => validateBadgeJPEG(jpeg())).not.toThrow();
  });
  it.each([
    ['progressive encoding', jpeg(frame, 0xc2)],
    ['wrong dimensions', jpeg([8, 0, 240, 1, 65, ...frame.slice(5)])],
    ['high bit depth', jpeg([16, ...frame.slice(1)])],
    ['unsupported components', jpeg([...frame.slice(0, 5), 4, ...frame.slice(6)])],
    ['truncated frame', jpeg(frame.slice(0, 8))],
    ['invalid signature', new Uint8Array([0, 0, 0xff, 0xd9])],
    ['no baseline frame', new Uint8Array([0xff, 0xd8, 0xff, 0xd9])],
    ['missing end', jpeg().subarray(0, -2)],
    ['truncated segment', new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0xff, 0xff, 0xff, 0xd9])],
    ['segment before frame is too short', new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 1, 0xff, 0xd9])],
    ['scan before frame', jpeg(frame, 0xda)],
    ['excessive bytes', new Uint8Array(327_681)],
  ] as const)('refuses %s before storing it', (_reason, bytes) => {
    expect(() => validateBadgeJPEG(bytes)).toThrow('Could not prepare a baseline 320 × 240 JPEG for the badge.');
  });
});
