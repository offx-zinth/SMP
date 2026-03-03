/**
 * SMP API Route
 * JSON-RPC 2.0 endpoint for Structural Memory Protocol
 */

import { NextRequest, NextResponse } from 'next/server';
import { SMPProtocolHandler, getProtocolHandler } from '@/lib/smp/protocol/handler';
import { SMPRequest, SMPResponse } from '@/lib/smp/types';

// Initialize protocol handler
const handler: SMPProtocolHandler = getProtocolHandler();

/**
 * Handle POST requests for SMP protocol
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const body = await request.json();
    
    // Handle batch requests
    if (Array.isArray(body)) {
      const responses: SMPResponse[] = [];
      
      for (const req of body) {
        const response = await handler.handleRequest(req as SMPRequest);
        responses.push(response);
      }
      
      return NextResponse.json(responses);
    }
    
    // Single request
    const response = await handler.handleRequest(body as SMPRequest);
    return NextResponse.json(response);
  } catch (error) {
    return NextResponse.json(
      {
        jsonrpc: '2.0',
        error: {
          code: -32700,
          message: 'Parse error',
          data: error instanceof Error ? error.message : 'Invalid JSON',
        },
        id: null,
      },
      { status: 400 }
    );
  }
}

/**
 * Handle GET requests for status
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  const statusRequest: SMPRequest = {
    jsonrpc: '2.0',
    method: 'smp/status',
    id: 'status',
  };
  
  const response = await handler.handleRequest(statusRequest);
  return NextResponse.json(response);
}
