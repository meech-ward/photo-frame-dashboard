import { afterEach, describe, expect, it, vi } from 'vitest';
import { photoVariants } from '../src/backend';

function png(): Uint8Array<ArrayBuffer> {
  const bytes = new Uint8Array(58);
  bytes.set([137, 80, 78, 71, 13, 10, 26, 10]);
  const view = new DataView(bytes.buffer);
  view.setUint32(8, 13); bytes.set([73, 72, 68, 82], 12);
  view.setUint32(33, 1); bytes.set([73, 68, 65, 84, 1], 37);
  bytes.set([73, 69, 78, 68], 50);
  return bytes;
}
const jpeg = new Uint8Array([255, 216, 255, 192, 0, 17, 8, 0, 240, 1, 64, 3, 1, 17, 0, 2, 17, 1, 3, 17, 1, 255, 217]);
function canvases(width: number, height: number) {
  const output: { width: number; height: number; draw: ReturnType<typeof vi.fn> }[] = [];
  const close = vi.fn();
  vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ width, height, close })));
  vi.stubGlobal('document', { createElement: () => {
    const draw = vi.fn();
    const canvas = { width: 0, height: 0, draw,
      getContext: () => ({ fillRect: vi.fn(), drawImage: draw, fillStyle: '' }),
      toBlob: (callback: (blob: Blob) => void, type: string) => callback(new Blob([type === 'image/png' ? png() : canvas.width === 320 ? jpeg : new TextEncoder().encode(`${canvas.width}x${canvas.height}`)], { type })),
    };
    output.push(canvas);
    return canvas;
  } });
  return { output, close };
}
afterEach(() => vi.unstubAllGlobals());

describe('web and device photo renditions', () => {
  it('keeps a portrait photo uncropped on web while preparing both native codecs', async () => {
    const { output, close } = canvases(3000, 4000);
    const variants = await photoVariants(new File(['source'], 'portrait.png', { type: 'image/png' }));
    expect(output.map(({ width, height }) => [width, height])).toEqual([[320, 240], [1536, 2048]]);
    expect(output[1].draw.mock.calls[0].slice(1)).toEqual([0, 0, 1536, 2048]);
    expect(output[0].draw.mock.calls[0][2]).toBeLessThan(0);
    expect(await variants.web.text()).toBe('1536x2048');
    expect(variants.png.type).toBe('image/png');
    expect(variants.jpeg.type).toBe('image/jpeg');
    expect(close).toHaveBeenCalledTimes(2);
  });
  it('does not enlarge a small web original', async () => {
    const { output } = canvases(640, 360);
    await photoVariants(new File(['source'], 'small.webp', { type: 'image/webp' }));
    expect([output[1].width, output[1].height]).toEqual([640, 360]);
  });
});
