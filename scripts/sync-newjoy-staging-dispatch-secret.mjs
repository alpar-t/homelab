#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

// Owner-approved reuse of the existing ARC credential. It goes directly from
// captured Secret data to gh stdin; never to a file, argv, environment, or logs.
export function syncStagingDispatchCredential(run = execFileSync) {
  try {
    const options = { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 30000 };
    const source = JSON.parse(run('kubectl', ['-n', 'arc-runners', 'get', 'secret', 'github-arc-token', '-o', 'json'], options));
    if (typeof source.data?.github_token !== 'string') throw new Error('missing credential');
    const token = Buffer.from(source.data.github_token, 'base64').toString('utf8').trim();
    if (!token) throw new Error('empty credential');
    run('gh', ['secret', 'set', 'NEWJOY_STAGING_DISPATCH_TOKEN', '--repo', 'alpar-t/newjoy-website'], { ...options, input: token });
  } catch {
    throw new Error('Staging dispatch credential synchronization failed; all sensitive output suppressed.');
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    syncStagingDispatchCredential();
    console.log('Website staging dispatch secret synchronized from the existing ARC credential.');
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
