import { NextResponse } from 'next/server';
import { getProtocolHandler } from '@/src/protocol/handler';

const SAMPLE_FILES = [
  {
    file_path: 'src/auth/login.ts',
    change_type: 'created' as const,
    content: `import { UserModel } from '../db/user';
import { compareHash } from './crypto';
import { generateToken } from './token';

/** Handles user authentication */
export async function authenticateUser(email: string, password: string): Promise<string> {
  const user = await UserModel.findByEmail(email);
  if (!user) throw new Error('User not found');

  const valid = await compareHash(password, user.passwordHash);
  if (!valid) throw new Error('Invalid credentials');

  return generateToken(user.id);
}`,
  },
  {
    file_path: 'src/auth/routes.ts',
    change_type: 'created' as const,
    content: `import { authenticateUser } from './login';

export async function loginRoute(req: { body: { email: string; password: string } }) {
  const { email, password } = req.body;
  const token = await authenticateUser(email, password);
  return { token };
}`,
  },
  {
    file_path: 'tests/auth.test.ts',
    change_type: 'created' as const,
    content: `import { authenticateUser } from '../src/auth/login';

export async function test_authenticate_user() {
  const token = await authenticateUser('test@example.com', 'password123');
  return token.length > 0;
}`,
  },
];

export async function GET() {
  const handler = getProtocolHandler();

  await handler.handleRequest({
    jsonrpc: '2.0',
    method: 'smp/clear',
    id: 'clear',
  });

  const response = await handler.handleRequest({
    jsonrpc: '2.0',
    method: 'smp/batch_update',
    params: { changes: SAMPLE_FILES },
    id: 'init',
  });

  return NextResponse.json(response);
}
