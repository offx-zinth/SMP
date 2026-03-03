import test from 'node:test';
import assert from 'node:assert/strict';

import { SMPProtocolHandler } from '../src/protocol/handler';
import { MemoryStore } from '../src/core/store';

const filePath = 'src/auth/auth.ts';
const content = `export function generateToken(email: string): string {
  return email + '-token';
}

export async function authenticateUser(email: string) {
  return generateToken(email);
}
`;

test('smp/update indexes nodes and smp/status reports totals', async () => {
  const handler = new SMPProtocolHandler(new MemoryStore());

  const updateRes = await handler.handleRequest({
    jsonrpc: '2.0',
    method: 'smp/update',
    params: { file_path: filePath, content, change_type: 'created' },
    id: 1,
  });

  assert.equal(updateRes.error, undefined);
  assert.equal((updateRes.result as any).status, 'success');
  assert.ok((updateRes.result as any).nodes_added >= 3);

  const statusRes = await handler.handleRequest({
    jsonrpc: '2.0',
    method: 'smp/status',
    id: 2,
  });

  assert.equal(statusRes.error, undefined);
  assert.ok((statusRes.result as any).total_nodes >= 3);
});

test('smp/navigate and smp/impact return indexed relationships', async () => {
  const handler = new SMPProtocolHandler(new MemoryStore());

  await handler.handleRequest({
    jsonrpc: '2.0',
    method: 'smp/update',
    params: { file_path: filePath, content, change_type: 'created' },
    id: 3,
  });

  const navRes = await handler.handleRequest({
    jsonrpc: '2.0',
    method: 'smp/navigate',
    params: { entity_name: 'authenticateUser', include_relationships: true },
    id: 4,
  });

  assert.equal(navRes.error, undefined);
  assert.equal((navRes.result as any).entity.structural.name, 'authenticateUser');

  const impactRes = await handler.handleRequest({
    jsonrpc: '2.0',
    method: 'smp/impact',
    params: { entity_id: 'func_generateToken_src_auth_auth_ts', change_type: 'delete' },
    id: 5,
  });

  assert.equal(impactRes.error, undefined);
  assert.equal((impactRes.result as any).severity, 'medium');
  assert.ok((impactRes.result as any).affected_functions.includes('authenticateUser'));
});
