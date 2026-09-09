#!/usr/bin/env node
// Copy only the three existing integration values. Never print Secret bodies,
// kubectl error buffers, or credentials, including on failed commands.
import { execFileSync } from 'node:child_process';
const kubectl = (args, input) => execFileSync('kubectl', args, {
  input, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 30_000,
});
try {
  const source = JSON.parse(kubectl(['-n', 'baloo', 'get', 'secret', 'opencloud-baloo', '-o', 'json']));
  const keys = ['webdav-url', 'username', 'app-token'];
  const data = Object.fromEntries(keys.map((key) => {
    if (!source.data?.[key]) throw new Error('missing source key');
    return [key, source.data[key]];
  }));
  const target = { apiVersion: 'v1', kind: 'Secret', type: 'Opaque',
    metadata: { name: 'newjoy-website-opencloud', namespace: 'arc-runners',
      annotations: { 'newjoy.ro/credential-source': 'baloo/opencloud-baloo' } }, data };
  kubectl(['apply', '--server-side', '--field-manager=newjoy-credential-sync', '-f', '-'], JSON.stringify(target));
  const actual = JSON.parse(kubectl(['-n', 'arc-runners', 'get', 'secret', 'newjoy-website-opencloud', '-o', 'json']));
  if (keys.some((key) => actual.data?.[key] !== data[key])) throw new Error('readback mismatch');
  console.log('Website OpenCloud Secret matches the existing Baloo credentials (3 keys verified).');
} catch {
  console.error('Credential synchronization failed; all Secret output suppressed.');
  process.exitCode = 1;
}
