/**
 * SMP Protocol Handler
 * JSON-RPC 2.0 implementation for Structural Memory Protocol
 */

import {
  SMPRequest,
  SMPResponse,
  SMPNotification,
  FileChange,
  UpdateResult,
  NavigateQuery,
  TraceQuery,
  ContextQuery,
  ImpactQuery,
  LocateQuery,
  FlowQuery,
} from '../types';
import { parseFile } from '../core/parser';
import { buildGraph, GraphBuildResult } from '../core/graph-builder';
import { enrichNode, enrichNodes } from '../core/enricher';
import { getMemoryStore, MemoryStore } from '../core/store';
import { QueryEngine, createQueryEngine } from '../engine/query';

// ============================================================================
// Protocol Handler
// ============================================================================

export class SMPProtocolHandler {
  private store: MemoryStore;
  private queryEngine: QueryEngine;
  private fileContents: Map<string, string> = new Map();
  
  constructor(store?: MemoryStore) {
    this.store = store || getMemoryStore();
    this.queryEngine = createQueryEngine(this.store);
  }
  
  /**
   * Handle incoming JSON-RPC request
   */
  async handleRequest(request: SMPRequest): Promise<SMPResponse> {
    const { method, params, id } = request;
    
    try {
      let result: unknown;
      
      switch (method) {
        // Memory Management
        case 'smp/update':
          result = await this.handleUpdate(params as { file_path: string; content?: string; change_type: string });
          break;
          
        case 'smp/batch_update':
          result = await this.handleBatchUpdate(params as { changes: FileChange[] });
          break;
          
        case 'smp/reindex':
          result = await this.handleReindex(params as { scope?: string });
          break;
          
        case 'smp/status':
          result = this.handleStatus();
          break;
          
        case 'smp/clear':
          result = this.handleClear();
          break;
          
        // Structural Queries
        case 'smp/navigate':
          result = this.queryEngine.navigate(params as unknown as NavigateQuery);
          break;
          
        case 'smp/trace':
          result = this.queryEngine.trace(params as unknown as TraceQuery);
          break;
          
        // Context Queries
        case 'smp/context':
          result = this.queryEngine.context(params as unknown as ContextQuery);
          break;
          
        case 'smp/impact':
          result = this.queryEngine.impact(params as unknown as ImpactQuery);
          break;
          
        // Semantic Search
        case 'smp/locate':
          result = this.queryEngine.locate(params as unknown as LocateQuery);
          break;
          
        // Flow Analysis
        case 'smp/flow':
          result = this.queryEngine.flow(params as unknown as FlowQuery);
          break;
          
        // Graph Operations
        case 'smp/graph':
          result = this.queryEngine.getGraph();
          break;
          
        case 'smp/nodes':
          result = this.handleGetNodes(params as { type?: string });
          break;
          
        case 'smp/node':
          result = this.handleGetNode(params as { id: string });
          break;
          
        case 'smp/enrich':
          result = await this.handleEnrich(params as { id?: string; use_llm?: boolean });
          break;
          
        default:
          return {
            jsonrpc: '2.0',
            error: {
              code: -32601,
              message: `Method not found: ${method}`,
            },
            id,
          };
      }
      
      return {
        jsonrpc: '2.0',
        result,
        id,
      };
    } catch (error) {
      return {
        jsonrpc: '2.0',
        error: {
          code: -32603,
          message: 'Internal error',
          data: error instanceof Error ? error.message : 'Unknown error',
        },
        id,
      };
    }
  }
  
  // =========================================================================
  // Memory Management Handlers
  // =========================================================================
  
  private async handleUpdate(params: { file_path: string; content?: string; change_type: string }): Promise<UpdateResult> {
    const { file_path, content, change_type } = params;
    
    if (change_type === 'deleted') {
      // Remove node and all its relationships
      const fileNodes = this.store.graph.findNodesByFile(file_path);
      for (const node of fileNodes) {
        this.store.deleteNode(node.id);
      }
      
      return {
        status: 'success',
        nodes_added: 0,
        nodes_updated: 0,
        nodes_removed: fileNodes.length,
        relationships_updated: 0,
      };
    }
    
    if (!content) {
      return {
        status: 'failed',
        nodes_added: 0,
        nodes_updated: 0,
        nodes_removed: 0,
        relationships_updated: 0,
        errors: ['No content provided for update'],
      };
    }
    
    // Store content
    this.fileContents.set(file_path, content);
    
    // Parse file
    const parsed = parseFile(content, file_path);
    
    // Build graph
    const graphResult = buildGraph([parsed], this.fileContents);
    
    // Enrich nodes
    const enrichedNodes = await enrichNodes(graphResult.nodes, { useLLM: false });
    
    // Add to store
    for (const result of enrichedNodes) {
      this.store.addNode(result.node);
    }
    
    // Add edges
    for (const edge of graphResult.edges) {
      this.store.graph.addEdge(edge);
    }
    
    return {
      status: 'success',
      nodes_added: graphResult.nodes.length,
      nodes_updated: 0,
      nodes_removed: 0,
      relationships_updated: graphResult.edges.length,
    };
  }
  
  private async handleBatchUpdate(params: { changes: FileChange[] }): Promise<UpdateResult> {
    let totalAdded = 0;
    let totalUpdated = 0;
    let totalRemoved = 0;
    let totalRelationships = 0;
    const errors: string[] = [];
    
    for (const change of params.changes) {
      const result = await this.handleUpdate(change);
      totalAdded += result.nodes_added;
      totalUpdated += result.nodes_updated;
      totalRemoved += result.nodes_removed;
      totalRelationships += result.relationships_updated;
      if (result.errors) {
        errors.push(...result.errors);
      }
    }
    
    return {
      status: errors.length > 0 ? 'partial' : 'success',
      nodes_added: totalAdded,
      nodes_updated: totalUpdated,
      nodes_removed: totalRemoved,
      relationships_updated: totalRelationships,
      errors: errors.length > 0 ? errors : undefined,
    };
  }
  
  private async handleReindex(params: { scope?: string }): Promise<{ status: string; message: string }> {
    // Clear existing data
    this.store.clear();
    this.fileContents.clear();
    
    return {
      status: 'success',
      message: 'Memory store cleared. Ready for reindexing.',
    };
  }
  
  private handleStatus(): Record<string, unknown> {
    const stats = this.store.getStats();
    
    return {
      status: 'running',
      version: '1.0.0',
      ...stats,
    };
  }
  
  private handleClear(): { status: string } {
    this.store.clear();
    this.fileContents.clear();
    
    return { status: 'success' };
  }
  
  // =========================================================================
  // Graph Operations
  // =========================================================================
  
  private handleGetNodes(params: { type?: string }): unknown[] {
    if (params.type) {
      return this.store.graph.findNodesByType(params.type as any);
    }
    return this.store.graph.getAllNodes();
  }
  
  private handleGetNode(params: { id: string }): unknown {
    return this.store.graph.getNode(params.id) || null;
  }
  
  private async handleEnrich(params: { id?: string; use_llm?: boolean }): Promise<unknown> {
    const useLLM = params.use_llm ?? false;
    
    if (params.id) {
      const node = this.store.graph.getNode(params.id);
      if (!node) {
        return { error: 'Node not found' };
      }
      
      const result = await enrichNode(node, { useLLM });
      if (result.enriched) {
        this.store.updateNode(params.id, { semantic: result.node.semantic });
      }
      
      return result;
    }
    
    // Enrich all nodes
    const nodes = this.store.graph.getAllNodes();
    const results = await enrichNodes(nodes, { useLLM });
    
    for (const result of results) {
      if (result.enriched) {
        this.store.updateNode(result.node.id, { semantic: result.node.semantic });
      }
    }
    
    return {
      total: results.length,
      enriched: results.filter(r => r.enriched).length,
    };
  }
  
  // =========================================================================
  // Notification Handling
  // =========================================================================
  
  createNotification(type: string, params: Record<string, unknown>): SMPNotification {
    return {
      jsonrpc: '2.0',
      method: 'smp/notification',
      params: {
        type,
        ...params,
      },
    };
  }
}

// Singleton instance
let handlerInstance: SMPProtocolHandler | null = null;

export function getProtocolHandler(): SMPProtocolHandler {
  if (!handlerInstance) {
    handlerInstance = new SMPProtocolHandler();
  }
  return handlerInstance;
}

export function resetProtocolHandler(): void {
  handlerInstance = new SMPProtocolHandler();
}
