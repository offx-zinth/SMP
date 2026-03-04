export interface SMPRequest {
  action: 'navigate' | 'trace' | 'search';
  query: string;
  file_path?: string;
  depth?: number;
  limit?: number;
}

export interface SMPResponse<T = Record<string, unknown>> {
  ok: boolean;
  action: string;
  data: T;
}

export interface AgentChatRequest {
  prompt: string;
  max_steps?: number;
}

export interface WorkspaceInitRequest {
  workspace_dir?: string;
  recursive?: boolean;
}

export interface VibeCoderApiClientConfig {
  baseUrl: string;
  timeoutMs?: number;
}

export class VibeCoderApiClient {
  private readonly baseUrl: string;
  private readonly timeoutMs: number;

  constructor(config: VibeCoderApiClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, '');
    this.timeoutMs = config.timeoutMs ?? 30_000;
  }

  async querySmp<T = Record<string, unknown>>(request: SMPRequest): Promise<SMPResponse<T>> {
    return this.post<SMPResponse<T>>('/smp/query', request);
  }

  async chatAgent(request: AgentChatRequest): Promise<{ ok: boolean; result: string }> {
    return this.post<{ ok: boolean; result: string }>('/agent/chat', request);
  }

  async initWorkspace(request: WorkspaceInitRequest = {}): Promise<{
    ok: boolean;
    workspace: string;
    files_indexed: number;
    nodes_indexed: number;
  }> {
    return this.post('/workspace/init', request);
  }

  private async post<T>(path: string, body: unknown): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`Backend request failed: ${response.status} ${response.statusText}`);
      }

      return (await response.json()) as T;
    } finally {
      clearTimeout(timer);
    }
  }
}
