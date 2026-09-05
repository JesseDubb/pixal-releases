import { build } from 'esbuild';
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export function shellPaths(source) {
  const declarations = [...source.matchAll(/const SHELL = (\[[\s\S]*?\]);/g)];
  if (declarations.length !== 1) throw new Error('Expected one literal service-worker shell list');
  const paths = JSON.parse(declarations[0][1]);
  if (!Array.isArray(paths) || paths.some(p => typeof p !== 'string' || !p.startsWith('/') || p.startsWith('//') || /[?#%\x00\\]/.test(p) || p.includes('..'))) {
    throw new Error('Shell entries must be local, root-relative asset paths');
  }
  return [...new Set(paths)].sort();
}

export function stampWorker(source, assets) {
  const declaration = /const CACHE = "pixal-dm-[^"]*";/g;
  if ([...source.matchAll(declaration)].length !== 1) throw new Error('Expected exactly one cache declaration');
  const normalized = source.replace(declaration, 'const CACHE = "pixal-dm-BUILD";').replace(/\r\n/g, '\n');
  const hash = createHash('sha256').update(normalized);
  for (const [name, bytes] of [...assets].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) {
    hash.update(name).update('\0').update(createHash('sha256').update(bytes).digest('hex')).update('\0');
  }
  return normalized.replace('const CACHE = "pixal-dm-BUILD";', `const CACHE = "pixal-dm-${hash.digest('hex').slice(0, 12)}";`);
}

export async function buildWeb({ check = false } = {}) {
  const web = path.join(root, 'web');
  const bundlePath = path.join(web, 'app.js');
  const workerPath = path.join(web, 'sw.js');
  const result = await build({
    absWorkingDir: root, entryPoints: ['web/src/app.jsx'], bundle: true,
    format: 'esm', external: ['/vendor/*'], outfile: bundlePath,
    jsx: 'automatic', minify: true, write: false,
  });
  const bundle = result.outputFiles.find(file => file.path === bundlePath)?.contents;
  if (!bundle) throw new Error('Build produced no application bundle');
  const worker = await readFile(workerPath, 'utf8');
  const assets = new Map();
  for (const asset of shellPaths(worker)) {
    assets.set(asset, asset === '/app.js' ? bundle : await readFile(path.join(web, asset === '/' ? 'index.html' : asset.slice(1))));
  }
  const stamped = stampWorker(worker, assets);
  if (check) {
    const current = await readFile(bundlePath);
    if (!current.equals(Buffer.from(bundle)) || worker.replace(/\r\n/g, '\n') !== stamped) {
      throw new Error('Frontend artifacts are stale. Run web\\build.bat (Windows) or node tools/build_web.mjs.');
    }
    console.log(`Frontend verified: ${bundle.byteLength} bytes; ${assets.size} shell assets.`);
  } else {
    await writeFile(bundlePath, bundle);
    await writeFile(workerPath, stamped, 'utf8');
    console.log(`Frontend built: ${bundle.byteLength} bytes; ${assets.size} shell assets stamped.`);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  if (args.some(arg => arg !== '--check')) {
    console.error('Usage: node tools/build_web.mjs [--check]');
    process.exitCode = 2;
  } else {
    try { await buildWeb({ check: args.includes('--check') }); }
    catch (error) { console.error(error.message); process.exitCode = 1; }
  }
}
