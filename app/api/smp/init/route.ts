import { NextResponse } from 'next/server';
import { VibeCoderApiClient } from '@/src/lib/api';

const backend = new VibeCoderApiClient({
  baseUrl: process.env.VIBECODER_BACKEND_URL ?? 'http://localhost:8000',
});

export async function POST() {
  try {
    const response = await backend.initWorkspace({ recursive: true });
    return NextResponse.json(response);
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : 'Unknown backend error' },
      { status: 500 },
    );
  }
}
