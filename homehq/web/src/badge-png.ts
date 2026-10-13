// Match the badge's bounded image reader. A valid opaque 320×240 RGBA PNG can
// exceed 256 KiB when its pixels compress poorly; 320 KiB keeps that case valid.
export const MAX_BADGE_PNG_BYTES = 327_680;

const signature = [137, 80, 78, 71, 13, 10, 26, 10];
const IHDR = 0x49484452, IDAT = 0x49444154, IEND = 0x49454e44;

function crc32(bytes: Uint8Array): number {
  // PNG uses IEEE CRC-32 over the chunk type and payload. Computing only the
  // merged chunk's checksum avoids adding an image codec to the web bundle.
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

/** Join a browser PNG's compressed stream without decoding or recompressing it. */
export function coalescePNGIDAT(bytes: Uint8Array<ArrayBuffer>): Uint8Array<ArrayBuffer> {
  const invalid = () => new Error('Could not prepare a valid badge PNG.');
  if (bytes.length > MAX_BADGE_PNG_BYTES || !signature.every((byte, i) => bytes[i] === byte)) throw invalid();
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let first = -1, last = -1, payloadBytes = 0, count = 0;
  let ended = false, dataEnded = false;
  for (let offset = 8; offset < bytes.length;) {
    if (bytes.length - offset < 12) throw invalid();
    const length = view.getUint32(offset);
    const type = view.getUint32(offset + 4);
    const end = offset + length + 12;
    if (end > bytes.length || (offset === 8 && (type !== IHDR || length !== 13))) throw invalid();
    if (type === IHDR && offset !== 8) throw invalid();
    if (type === IDAT) {
      // PNG requires consecutive IDAT chunks. Refuse an unexpected layout
      // rather than relocating an ancillary chunk and changing its meaning.
      if (dataEnded) throw invalid();
      if (first < 0) first = offset;
      last = end;
      payloadBytes += length;
      count++;
    } else if (count) dataEnded = true;
    if (type === IEND) {
      if (length !== 0 || end !== bytes.length) throw invalid();
      ended = true;
    }
    offset = end;
  }
  if (!ended || !count || !payloadBytes) throw invalid();
  if (count === 1) return bytes;

  // The badge's native PNG decoder fails on browsers' multiple IDAT chunks.
  // One chunk keeps the identical deflate bytes/pixels while avoiding that
  // decoder boundary; a valid PNG in the browser alone did not catch this.
  const result = new Uint8Array(bytes.length - (count - 1) * 12);
  const output = new DataView(result.buffer);
  result.set(bytes.subarray(0, first));
  output.setUint32(first, payloadBytes);
  output.setUint32(first + 4, IDAT);
  let target = first + 8;
  for (let offset = first; offset < last;) {
    const length = view.getUint32(offset);
    result.set(bytes.subarray(offset + 8, offset + 8 + length), target);
    target += length;
    offset += length + 12;
  }
  output.setUint32(target, crc32(result.subarray(first + 4, target)));
  result.set(bytes.subarray(last), target + 4);
  return result;
}
