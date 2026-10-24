import { setTimeout as delay } from 'node:timers/promises';

const endpoint = 'http://127.0.0.1:3000/mcp';
const headers = {
  'content-type': 'application/json',
  accept: 'application/json, text/event-stream',
};

async function request(payload, sessionId) {
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { ...headers, ...(sessionId ? { 'mcp-session-id': sessionId } : {}) },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(5000),
  });
  const body = await response.text();
  if (!response.ok) throw new Error(`MCP HTTP ${response.status}: ${body.slice(0, 300)}`);
  const message = response.headers.get('content-type')?.includes('text/event-stream')
    ? body.split('\n').filter((line) => line.startsWith('data: '))
        .map((line) => JSON.parse(line.slice(6))).find((item) => item.id === payload.id)
    : body ? JSON.parse(body) : undefined;
  if (message?.error) throw new Error(JSON.stringify(message.error));
  return { message, sessionId: response.headers.get('mcp-session-id') || sessionId };
}

let initialized;
for (let attempt = 0; attempt < 30; attempt++) {
  try {
    initialized = await request({
      jsonrpc: '2.0', id: 1, method: 'initialize',
      params: {
        protocolVersion: '2025-06-18', capabilities: {},
        clientInfo: { name: 'runtime-smoke', version: '1.0.0' },
      },
    });
    break;
  } catch (error) {
    if (attempt === 29) throw error;
    await delay(1000);
  }
}

if (!initialized.message?.result?.serverInfo) {
  throw new Error('MCP initialize did not return serverInfo');
}
await request({ jsonrpc: '2.0', method: 'notifications/initialized' }, initialized.sessionId);
const catalog = await request({ jsonrpc: '2.0', id: 2, method: 'tools/list' }, initialized.sessionId);
const names = new Set(catalog.message?.result?.tools?.map((tool) => tool.name));
for (const name of ['kubectl_get', 'kubectl_describe', 'kubectl_logs']) {
  if (!names.has(name)) throw new Error(`Missing read-only tool: ${name}`);
}
for (const name of ['kubectl_apply', 'kubectl_delete', 'exec_in_pod']) {
  if (names.has(name)) throw new Error(`Write-capable tool exposed: ${name}`);
}
console.log(`MCP initialized; ${names.size} read-only tools exposed`);
