import { MAX_BADGE_PNG_BYTES } from './badge-png';

/** Verify the baseline frame emitted by the browser, before storing a variant. */
export function validateBadgeJPEG(bytes: Uint8Array): void {
  const invalid = () => new Error('Could not prepare a baseline 320 × 240 JPEG for the badge.');
  // Both variants share the native transfer cap; a smaller JPEG must not
  // bypass it merely because its decoder uses a different file signature.
  if (bytes.length > MAX_BADGE_PNG_BYTES || bytes[0] !== 0xff || bytes[1] !== 0xd8
      || bytes[bytes.length - 2] !== 0xff || bytes[bytes.length - 1] !== 0xd9) throw invalid();
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  for (let offset = 2; offset < bytes.length - 2;) {
    if (bytes[offset++] !== 0xff) throw invalid();
    while (bytes[offset] === 0xff) offset++;
    const marker = bytes[offset++];
    if (offset + 2 > bytes.length || marker === 0xda || marker === 0xd9) throw invalid();
    const length = view.getUint16(offset);
    if (length < 2 || offset + length > bytes.length) throw invalid();
    // The browser has already decoded the source. Only its bounded baseline
    // frame matters here; decoding entropy would duplicate the native codec.
    if (marker === 0xc0) {
      if (length !== 17 || bytes[offset + 2] !== 8
          || view.getUint16(offset + 3) !== 240 || view.getUint16(offset + 5) !== 320
          || bytes[offset + 7] !== 3) throw invalid();
      return;
    }
    if (marker >= 0xc1 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker)) throw invalid();
    offset += length;
  }
  throw invalid();
}
