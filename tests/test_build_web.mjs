import test from 'node:test';
import assert from 'node:assert/strict';
import { shellPaths, stampWorker } from '../tools/build_web.mjs';

const worker = 'const CACHE = "pixal-dm-old";\nconst SHELL = ["/", "/app.js", "/fonts/geist.woff2"];\n';
const assets = () => new Map([['/', Buffer.from('html')], ['/app.js', Buffer.from('js')], ['/fonts/geist.woff2', Buffer.from('font')]]);

test('the shell manifest includes fonts and is deterministic', () => {
  assert.deepEqual(shellPaths(worker), ['/', '/app.js', '/fonts/geist.woff2']);
});
test('a font-only change rotates the cache', () => {
  const before = assets();
  const after = assets();
  after.set('/fonts/geist.woff2', Buffer.from('new font'));
  assert.notEqual(stampWorker(worker, before), stampWorker(worker, after));
});
test('worker logic rotates the cache but the previous stamp does not', () => {
  assert.notEqual(stampWorker(worker, assets()), stampWorker(worker + '// new logic\n', assets()));
  assert.equal(stampWorker(worker, assets()), stampWorker(worker.replace('pixal-dm-old', 'pixal-dm-other'), assets()));
});
test('cache generation is stable across platform newlines and map order', () => {
  assert.equal(stampWorker(worker, assets()), stampWorker(worker.replaceAll('\n', '\r\n'), new Map([...assets()].reverse())));
  const once = stampWorker(worker, assets());
  assert.equal(stampWorker(once, assets()), once);
});
test('invalid or ambiguous manifests fail rather than shipping stale assets', () => {
  assert.throws(() => shellPaths('const SHELL = ["../secret"];'));
  assert.throws(() => shellPaths('const SHELL = ["/../secret"];'));
  assert.throws(() => shellPaths('const SHELL = ["https://example.test/a"];'));
  assert.throws(() => shellPaths('const SHELL = ["//example.test/a"];'));
  assert.throws(() => shellPaths('const SHELL = ["/%2e%2e/secret"];'));
  assert.throws(() => shellPaths(worker + 'const SHELL = ["/"];'));
  assert.throws(() => stampWorker(worker + 'const CACHE = "pixal-dm-two";', assets()));
});
