import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';

import { SMPProtocolHandler } from '../src/protocol/handler';
import { MemoryStore } from '../src/core/store';

const handler = new SMPProtocolHandler(new MemoryStore());
let server: http.Server;
let baseUrl = '';

function post(body: unknown): Promise<any> {
  return fetch(`${baseUrl}/api/smp`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => r.json());
}

function get(path: string): Promise<any> {
  return fetch(`${baseUrl}${path}`).then((r) => r.json());
}

test.before(async () => {
  server = http.createServer(async (req, res) => {
    const url = req.url || '/';

    if (req.method === 'GET' && url === '/api/smp') {
      const response = await handler.handleRequest({ jsonrpc: '2.0', method: 'smp/status', id: 'status' });
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(response));
      return;
    }

    if (req.method === 'POST' && url === '/api/smp') {
      let data = '';
      req.on('data', (chunk) => {
        data += chunk;
      });
      req.on('end', async () => {
        const request = JSON.parse(data || '{}');
        const response = await handler.handleRequest(request);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(response));
      });
      return;
    }

    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not found' }));
  });

  await new Promise<void>((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve());
  });

  const addr = server.address();
  if (!addr || typeof addr === 'string') {
    throw new Error('Could not resolve test server address');
  }

  baseUrl = `http://127.0.0.1:${addr.port}`;
});

test.after(async () => {
  await new Promise<void>((resolve, reject) => {
    server.close((err) => (err ? reject(err) : resolve()));
  });
});

test('API call smoke test for core SMP methods', async () => {
  const status = await get('/api/smp');
  assert.equal(status.result.status, 'running');

  const sampleContent = `
import { hash } from './crypto';

export function generateToken(email: string): string {
  return hash(email);
}

export async function authenticateUser(email: string, password: string) {
  if (!password) throw new Error('missing password');
  return generateToken(email);
}

export class AuthService {
  login(email: string, password: string) {
    return authenticateUser(email, password);
  }
}
`;

  const update = await post({
    jsonrpc: '2.0',
    method: 'smp/update',
    params: {
      file_path: 'src/auth/auth.ts',
      content: sampleContent,
      change_type: 'created',
    },
    id: 1,
  });
  assert.equal(update.result.status, 'success');
  assert.ok(update.result.nodes_added >= 4);

  const navigate = await post({
    jsonrpc: '2.0',
    method: 'smp/navigate',
    params: { entity_name: 'authenticateUser', include_relationships: true },
    id: 2,
  });
  assert.equal(navigate.result.entity.structural.name, 'authenticateUser');

  const trace = await post({
    jsonrpc: '2.0',
    method: 'smp/trace',
    params: {
      start_id: 'func_authenticateUser_src_auth_auth_ts',
      relationship_type: 'CALLS',
      depth: 3,
      direction: 'outgoing',
    },
    id: 3,
  });
  assert.equal(trace.result.root, 'authenticateUser');

  const context = await post({
    jsonrpc: '2.0',
    method: 'smp/context',
    params: { file_path: 'src/auth/auth.ts', scope: 'edit' },
    id: 4,
  });
  assert.ok(Array.isArray(context.result.defines));

  const impact = await post({
    jsonrpc: '2.0',
    method: 'smp/impact',
    params: { entity_id: 'func_generateToken_src_auth_auth_ts', change_type: 'delete' },
    id: 5,
  });
  assert.equal(impact.result.severity, 'medium');

  const locate = await post({
    jsonrpc: '2.0',
    method: 'smp/locate',
    params: { description: 'authenticate user token login', top_k: 5 },
    id: 6,
  });
  assert.ok(locate.result.matches.length > 0);

  const flow = await post({
    jsonrpc: '2.0',
    method: 'smp/flow',
    params: { start: 'func_authenticateUser_src_auth_auth_ts', flow_type: 'execution' },
    id: 7,
  });
  assert.ok(Array.isArray(flow.result.path));

  const graph = await post({
    jsonrpc: '2.0',
    method: 'smp/graph',
    id: 8,
  });
  assert.ok(graph.result.nodes.length >= 4);
  assert.ok(graph.result.edges.length >= 3);

  const batch = await post({
    jsonrpc: '2.0',
    method: 'smp/batch_update',
    params: {
      changes: [
        {
          file_path: 'src/utils/helpers.ts',
          content: 'export function formatDate(input: Date): string { return input.toISOString(); }',
          change_type: 'created',
        },
        {
          file_path: 'src/utils/validators.ts',
          content: 'export function isEmail(value: string): boolean { return value.includes("@"); }',
          change_type: 'created',
        },
      ],
    },
    id: 9,
  });

  assert.equal(batch.result.status, 'success');
  assert.ok(batch.result.nodes_added >= 4);
});
