import { createHash } from 'node:crypto';
import { lstat, readFile, readdir } from 'node:fs/promises';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const web = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const upstream = join(web, 'upstream');
const pinned = 'fbe9a30ac4f9c77d3863e19a5e98d9eadb04ab03';

async function filesBelow(directory) {
  const files = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await filesBelow(path));
    else if (entry.isFile()) files.push(relative(upstream, path).split(sep).join('/'));
    else throw new Error(`Unsupported entry in upstream: ${relative(upstream, path)}`);
  }
  return files.sort();
}

try {
  const manifest = JSON.parse(await readFile(join(web, 'upstream-files.json'), 'utf8'));
  if (manifest.version !== 1 || manifest.repository !== 'https://github.com/wesbos/photo-frame-dashboard' || manifest.revision !== pinned) {
    throw new Error('The upstream manifest must identify the documented pinned Wes Bos commit.');
  }
  if (!manifest.files || !Object.keys(manifest.files).length) throw new Error('The upstream manifest is empty.');
  const expected = Object.keys(manifest.files).sort();
  const actual = await filesBelow(upstream);
  const errors = [];
  for (const name of actual) if (!Object.hasOwn(manifest.files, name)) errors.push(`Unexpected: ${name}`);
  for (const name of expected) {
    // These hashes identify original bytes, not a current-tree baseline. A
    // regenerated manifest after an accidental vendor edit would hide the edit.
    if (name.startsWith('/') || name.includes('\\') || name.split('/').some((part) => !part || part === '.' || part === '..')) {
      throw new Error(`Unsafe manifest path: ${name}`);
    }
    const entry = manifest.files[name];
    if (!entry || !/^[a-f0-9]{64}$/.test(entry.sha256) || !Number.isSafeInteger(entry.bytes) || entry.bytes < 0) {
      throw new Error(`Invalid manifest entry: ${name}`);
    }
    if (!actual.includes(name)) { errors.push(`Missing: ${name}`); continue; }
    const path = join(upstream, name);
    if (!(await lstat(path)).isFile()) { errors.push(`Not a regular file: ${name}`); continue; }
    const bytes = await readFile(path);
    if (bytes.length !== entry.bytes || createHash('sha256').update(bytes).digest('hex') !== entry.sha256) errors.push(`Modified: ${name}`);
  }
  if (errors.length) throw new Error(`${errors.join('\n')}\nKeep additions outside upstream/; see UPSTREAM.md.`);
  console.log(`Upstream verified: ${expected.length} original files at ${pinned}.`);
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
