/**
 * SMP TypeScript Client SDK
 * For integrating with Structural Memory Protocol servers
 */

import {
  SMPRequest,
  SMPResponse,
  SMPNode,
  NavigateQuery,
  TraceQuery,
  ContextQuery,
  ImpactQuery,
  LocateQuery,
  FlowQuery,
  FileChange,
  UpdateResult,
  NavigateResult,
  TraceResult,
  ContextResult,
  ImpactResult,
  LocateResult,
  FlowResult,
  GraphStats,
  GraphEdge,
} from '../types';

export interface SMPClientConfig {
  baseUrl: string;
  timeout?: number;
}

export class SMPClient {
  private baseUrl: string;
  private timeout: number;
  private requestId: number = 0;

  constructor(config: SMPClientConfig) {
    this.baseUrl = config.baseUrl;
    this.timeout = config.timeout || 30000;
  }

  /**
   * Send a JSON-RPC request
   */
  private async sendRequest<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T> {
    const request: SMPRequest = {
      jsonrpc: '2.0',
      method,
      params,
      id: ++this.requestId,
    };

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.timeout);

    try {
      const response = await fetch(`${this.baseUrl}/api/smp`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(request),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      const data: SMPResponse<T> = await response.json();

      if (data.error) {
        throw new Error(`SMP Error ${data.error.code}: ${data.error.message}`);
      }

      return data.result as T;
    } catch (error) {
      clearTimeout(timeoutId);
      throw error;
    }
  }

  // =========================================================================
  // Memory Management
  // =========================================================================

  /**
   * Update a single file
   */
  async update(filePath: string, content: string, changeType: 'created' | 'modified' | 'deleted' = 'modified'): Promise<UpdateResult> {
    return this.sendRequest<UpdateResult>('smp/update', {
      file_path: filePath,
      content,
      change_type: changeType,
    });
  }

  /**
   * Update multiple files
   */
  async batchUpdate(changes: FileChange[]): Promise<UpdateResult> {
    return this.sendRequest<UpdateResult>('smp/batch_update', { changes });
  }

  /**
   * Reindex the memory store
   */
  async reindex(scope?: string): Promise<{ status: string }> {
    return this.sendRequest('smp/reindex', { scope });
  }

  /**
   * Get memory status
   */
  async status(): Promise<GraphStats> {
    return this.sendRequest<GraphStats>('smp/status');
  }

  /**
   * Clear all memory
   */
  async clear(): Promise<{ status: string }> {
    return this.sendRequest('smp/clear');
  }

  // =========================================================================
  // Structural Queries
  // =========================================================================

  /**
   * Navigate to an entity
   */
  async navigate(query: NavigateQuery): Promise<NavigateResult> {
    return this.sendRequest<NavigateResult>('smp/navigate', query as unknown as Record<string, unknown>);
  }

  /**
   * Trace relationships
   */
  async trace(query: TraceQuery): Promise<TraceResult> {
    return this.sendRequest<TraceResult>('smp/trace', query as unknown as Record<string, unknown>);
  }

  /**
   * Get editing context
   */
  async context(query: ContextQuery): Promise<ContextResult> {
    return this.sendRequest<ContextResult>('smp/context', query as unknown as Record<string, unknown>);
  }

  /**
   * Assess change impact
   */
  async impact(query: ImpactQuery): Promise<ImpactResult> {
    return this.sendRequest<ImpactResult>('smp/impact', query as unknown as Record<string, unknown>);
  }

  /**
   * Locate by description
   */
  async locate(query: LocateQuery): Promise<LocateResult> {
    return this.sendRequest<LocateResult>('smp/locate', query as unknown as Record<string, unknown>);
  }

  /**
   * Trace execution/data flow
   */
  async flow(query: FlowQuery): Promise<FlowResult> {
    return this.sendRequest<FlowResult>('smp/flow', query as unknown as Record<string, unknown>);
  }

  // =========================================================================
  // Graph Operations
  // =========================================================================

  /**
   * Get full graph
   */
  async getGraph(): Promise<{ nodes: SMPNode[]; edges: GraphEdge[] }> {
    return this.sendRequest('smp/graph');
  }

  /**
   * Get node by ID
   */
  async getNode(id: string): Promise<SMPNode | null> {
    return this.sendRequest('smp/node', { id });
  }

  /**
   * Get nodes by type
   */
  async getNodes(type?: string): Promise<SMPNode[]> {
    return this.sendRequest('smp/nodes', type ? { type } : {});
  }

  /**
   * Enrich nodes with semantic information
   */
  async enrich(id?: string, useLlm: boolean = false): Promise<unknown> {
    return this.sendRequest('smp/enrich', { id, use_llm: useLlm });
  }
}

// Factory function
export function createSMPClient(config: SMPClientConfig): SMPClient {
  return new SMPClient(config);
}

// Default client for browser usage
export function createBrowserClient(): SMPClient {
  return new SMPClient({
    baseUrl: typeof window !== 'undefined' ? window.location.origin : 'http://localhost:3000',
  });
}
