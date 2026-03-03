import { NextRequest, NextResponse } from 'next/server';
import { getProtocolHandler } from '@/src/protocol/handler';
import { SMPRequest } from '@/src/types';

export async function GET() {
  const handler = getProtocolHandler();
  const status = await handler.handleRequest({
    jsonrpc: '2.0',
    method: 'smp/status',
    id: 'status',
  });

  return NextResponse.json(status);
}

export async function POST(req: NextRequest) {
  try {
    const request = (await req.json()) as SMPRequest;

    if (!request || request.jsonrpc !== '2.0' || !request.method) {
      return NextResponse.json(
        {
          jsonrpc: '2.0',
          error: { code: -32600, message: 'Invalid Request' },
          id: request?.id ?? null,
        },
        { status: 400 },
      );
    }

    const handler = getProtocolHandler();
    const response = await handler.handleRequest(request);
    return NextResponse.json(response);
  } catch {
    return NextResponse.json(
      {
        jsonrpc: '2.0',
        error: { code: -32700, message: 'Parse error' },
        id: null,
      },
      { status: 400 },
    );
  }
}
