import test from 'node:test';
import assert from 'node:assert/strict';
import { syncStagingDispatchCredential } from './sync-newjoy-staging-dispatch-secret.mjs';

test('only the approved ARC key is sent to the exact website Actions secret via stdin', () => {
  const calls = [];
  const token = 'fake-arc-token';
  syncStagingDispatchCredential((...args) => {
    calls.push(args);
    return calls.length === 1 ? JSON.stringify({ data: { github_token: Buffer.from(token).toString('base64'), unrelated: 'ignored' } }) : '';
  });
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[0].slice(0, 2), ['kubectl', ['-n', 'arc-runners', 'get', 'secret', 'github-arc-token', '-o', 'json']]);
  assert.deepEqual(calls[1].slice(0, 2), ['gh', ['secret', 'set', 'NEWJOY_STAGING_DISPATCH_TOKEN', '--repo', 'alpar-t/newjoy-website']]);
  assert.equal(calls[1][2].input, token);
  assert.deepEqual(calls[1][2].stdio, ['pipe', 'pipe', 'pipe']);
  assert.ok(!calls[1][1].includes(token));
  assert.ok(!Object.hasOwn(calls[1][2], 'env'));
});

test('missing key fails before any GitHub mutation', () => {
  let calls = 0;
  assert.throws(() => syncStagingDispatchCredential(() => { calls++; return '{"data":{}}'; }), /sensitive output suppressed/);
  assert.equal(calls, 1);
});

test('credential-bearing subprocess failures never escape into diagnostics', () => {
  assert.throws(() => syncStagingDispatchCredential(() => { throw new Error('fake-private-token'); }), (error) => !error.message.includes('fake-private-token'));
});
