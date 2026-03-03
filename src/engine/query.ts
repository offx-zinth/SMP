/**
 * SMP Query Engine Module
 * Implements navigate, trace, context, impact, locate, flow queries
 */

import {
  SMPNode,
  NavigateQuery,
  TraceQuery,
  ContextQuery,
  ImpactQuery,
  LocateQuery,
  FlowQuery,
  NavigateResult,
  TraceResult,
  ContextResult,
  ImpactResult,
  LocateResult,
  FlowResult,
  RelationshipType,
} from '../types';
import { MemoryStore } from './store';
import { GraphEdge } from './graph-builder';

// ============================================================================
// Query Engine
// ============================================================================

export class QueryEngine {
  private store: MemoryStore;
  
  constructor(store: MemoryStore) {
    this.store = store;
  }
  
  // =========================================================================
  // Navigate Query
  // =========================================================================
  
  /**
   * Find entity and its relationships
   */
  navigate(query: NavigateQuery): NavigateResult {
    const nodes = this.store.graph.findNodesByName(query.entity_name);
    
    if (nodes.length === 0) {
      return { entity: null };
    }
    
    // Return first match
    const entity = nodes[0];
    
    if (!query.include_relationships) {
      return { entity };
    }
    
    // Gather relationships
    const relationships: Record<string, string[]> = {};
    const edges = this.store.graph.getEdges(entity.id, 'both');
    
    for (const edge of edges) {
      const key = edge.from === entity.id ? `${edge.type}_out` : `${edge.type}_in`;
      if (!relationships[key]) {
        relationships[key] = [];
      }
      relationships[key].push(edge.from === entity.id ? edge.to : edge.from);
    }
    
    return { entity, relationships };
  }
  
  // =========================================================================
  // Trace Query
  // =========================================================================
  
  /**
   * Follow relationship chain
   */
  trace(query: TraceQuery): TraceResult {
    const { start_id, relationship_type, depth = 3, direction = 'outgoing' } = query;
    
    const startNode = this.store.graph.getNode(start_id);
    if (!startNode) {
      return { root: start_id, tree: {}, depth: 0 };
    }
    
    const tree = this.buildTraceTree(start_id, relationship_type, direction, depth, new Set());
    
    return {
      root: startNode.structural.name,
      tree,
      depth,
    };
  }
  
  private buildTraceTree(
    nodeId: string,
    relationshipType: RelationshipType,
    direction: 'outgoing' | 'incoming',
    remainingDepth: number,
    visited: Set<string>
  ): Record<string, unknown> {
    if (remainingDepth <= 0 || visited.has(nodeId)) {
      return {};
    }
    
    visited.add(nodeId);
    
    const node = this.store.graph.getNode(nodeId);
    if (!node) return {};
    
    const edges = this.store.graph.getEdgesByType(nodeId, relationshipType, direction);
    const result: Record<string, unknown> = {};
    
    const childKey = direction === 'outgoing' ? relationshipType.toLowerCase() : `called_by`;
    
    for (const edge of edges) {
      const targetId = direction === 'outgoing' ? edge.to : edge.from;
      const targetNode = this.store.graph.getNode(targetId);
      
      if (targetNode) {
        const childTree = this.buildTraceTree(
          targetId,
          relationshipType,
          direction,
          remainingDepth - 1,
          new Set(visited)
        );
        
        result[targetNode.structural.name] = childTree[childKey] ? { [childKey]: childTree[childKey] } : {};
      }
    }
    
    return { [childKey]: result };
  }
  
  // =========================================================================
  // Context Query
  // =========================================================================
  
  /**
   * Get editing context for a file
   */
  context(query: ContextQuery): ContextResult | null {
    const { file_path, scope = 'edit', depth = 2 } = query;
    
    // Find file node
    const fileNodes = this.store.graph.findNodesByFile(file_path);
    const fileNode = fileNodes.find(n => n.structural.type === 'File');
    
    if (!fileNode) {
      // Try to find any node in the file
      const anyNode = fileNodes[0];
      if (!anyNode) return null;
      
      return this.buildContextResult(anyNode, scope, depth);
    }
    
    return this.buildContextResult(fileNode, scope, depth);
  }
  
  private buildContextResult(node: SMPNode, scope: string, depth: number): ContextResult {
    const result: ContextResult = {
      self: node,
      imports: [],
      imported_by: [],
      defines: [],
      tests: [],
      patterns: [],
      warnings: [],
    };
    
    // Get imports
    const importEdges = this.store.graph.getEdgesByType(node.id, 'IMPORTS', 'outgoing');
    for (const edge of importEdges) {
      const importNode = this.store.graph.getNode(edge.to);
      if (importNode) {
        result.imports.push(importNode);
      }
    }
    
    // Get imported_by
    const importedByEdges = this.store.graph.getEdgesByType(node.id, 'IMPORTS', 'incoming');
    for (const edge of importedByEdges) {
      const importerNode = this.store.graph.getNode(edge.from);
      if (importerNode) {
        result.imported_by.push(importerNode);
      }
    }
    
    // Get defines
    const definesEdges = this.store.graph.getEdgesByType(node.id, 'DEFINES', 'outgoing');
    for (const edge of definesEdges) {
      const definedNode = this.store.graph.getNode(edge.to);
      if (definedNode) {
        result.defines.push(definedNode);
      }
    }
    
    // Get tests
    const testsEdges = this.store.graph.getEdgesByType(node.id, 'TESTS', 'incoming');
    for (const edge of testsEdges) {
      const testNode = this.store.graph.getNode(edge.from);
      if (testNode) {
        result.tests.push(testNode.structural.file);
      }
    }
    
    // Find similar patterns
    if (node.semantic?.keywords) {
      const similar = this.store.vectors.findByKeywords(
        node.semantic.keywords,
        this.store.graph,
        5
      );
      
      for (const match of similar) {
        if (match.node.id !== node.id) {
          result.patterns.push({
            entity: match.node,
            similarity: match.score,
          });
        }
      }
    }
    
    // Add warnings based on scope
    if (scope === 'edit') {
      if (result.imported_by.length > 5) {
        result.warnings.push(`This file is imported by ${result.imported_by.length} other files. Changes may have broad impact.`);
      }
      
      if (result.tests.length === 0) {
        result.warnings.push('No tests found for this file. Consider adding tests.');
      }
    }
    
    if (scope === 'debug') {
      // Trace data flow
      result.data_flow_in = this.traceDataFlow(node.id, 'in', depth);
      result.data_flow_out = this.traceDataFlow(node.id, 'out', depth);
    }
    
    return result;
  }
  
  private traceDataFlow(nodeId: string, direction: 'in' | 'out', depth: number): string[] {
    const result: string[] = [];
    const visited = new Set<string>();
    const queue: Array<{ id: string; level: number }> = [{ id: nodeId, level: 0 }];
    
    while (queue.length > 0) {
      const { id, level } = queue.shift()!;
      
      if (visited.has(id) || level > depth) continue;
      visited.add(id);
      
      const edges = direction === 'in'
        ? this.store.graph.getEdges(id, 'incoming')
        : this.store.graph.getEdges(id, 'outgoing');
      
      for (const edge of edges) {
        const targetId = direction === 'in' ? edge.from : edge.to;
        const targetNode = this.store.graph.getNode(targetId);
        
        if (targetNode && !visited.has(targetId)) {
          result.push(`${targetNode.structural.name} (${targetNode.structural.type})`);
          queue.push({ id: targetId, level: level + 1 });
        }
      }
    }
    
    return result;
  }
  
  // =========================================================================
  // Impact Query
  // =========================================================================
  
  /**
   * Assess change impact
   */
  impact(query: ImpactQuery): ImpactResult {
    const { entity_id, change_type } = query;
    
    const node = this.store.graph.getNode(entity_id);
    if (!node) {
      return {
        affected_files: [],
        affected_functions: [],
        affected_classes: [],
        severity: 'low',
        recommendations: [],
        breaking_changes: [],
      };
    }
    
    const affectedFiles = new Set<string>();
    const affectedFunctions = new Set<string>();
    const affectedClasses = new Set<string>();
    const breakingChanges: string[] = [];
    
    // Find all nodes that depend on this node
    const visited = new Set<string>();
    const queue = [entity_id];
    
    while (queue.length > 0) {
      const currentId = queue.shift()!;
      if (visited.has(currentId)) continue;
      visited.add(currentId);
      
      // Get incoming edges (things that depend on this)
      const incomingEdges = this.store.graph.getEdges(currentId, 'incoming');
      
      for (const edge of incomingEdges) {
        const dependant = this.store.graph.getNode(edge.from);
        if (dependant) {
          affectedFiles.add(dependant.structural.file);
          
          if (dependant.structural.type === 'Function') {
            affectedFunctions.add(dependant.structural.name);
          } else if (dependant.structural.type === 'Class') {
            affectedClasses.add(dependant.structural.name);
          }
          
          queue.push(edge.from);
        }
      }
    }
    
    // Determine severity
    let severity: 'low' | 'medium' | 'high' | 'critical' = 'low';
    
    if (change_type === 'delete') {
      severity = affectedFiles.size > 10 ? 'critical' : affectedFiles.size > 5 ? 'high' : 'medium';
    } else if (change_type === 'signature_change') {
      severity = affectedFunctions.size > 5 ? 'high' : affectedFunctions.size > 0 ? 'medium' : 'low';
    }
    
    // Generate recommendations
    const recommendations: string[] = [];
    
    if (change_type === 'delete') {
      recommendations.push(`Review all ${affectedFiles.size} affected files before deletion`);
      
      if (affectedFunctions.size > 0) {
        recommendations.push(`Update or remove ${affectedFunctions.size} dependent functions`);
      }
      
      if (affectedClasses.size > 0) {
        recommendations.push(`Update or remove ${affectedClasses.size} dependent classes`);
      }
    } else if (change_type === 'signature_change') {
      for (const func of affectedFunctions) {
        recommendations.push(`Update call sites for ${func} to match new signature`);
      }
    }
    
    if (node.structural.type === 'Function' && change_type !== 'move') {
      breakingChanges.push(`Function signature change will break ${affectedFunctions.size} callers`);
    }
    
    return {
      affected_files: Array.from(affectedFiles),
      affected_functions: Array.from(affectedFunctions),
      affected_classes: Array.from(affectedClasses),
      severity,
      recommendations,
      breaking_changes: breakingChanges,
    };
  }
  
  // =========================================================================
  // Locate Query
  // =========================================================================
  
  /**
   * Find code by description
   */
  locate(query: LocateQuery): LocateResult {
    const { description, top_k = 5 } = query;
    
    // Extract keywords from description
    const keywords = description
      .toLowerCase()
      .replace(/[^a-z\s]/g, ' ')
      .split(/\s+/)
      .filter(w => w.length > 2);
    
    // Search using keywords
    const matches = this.store.vectors.findByKeywords(keywords, this.store.graph, top_k);
    
    return {
      matches: matches.map(m => ({
        entity: m.node,
        relevance: m.score,
        highlight: m.node.semantic?.purpose,
      })),
    };
  }
  
  // =========================================================================
  // Flow Query
  // =========================================================================
  
  /**
   * Trace execution/data flow
   */
  flow(query: FlowQuery): FlowResult {
    const { start, end, flow_type = 'execution', max_depth = 10 } = query;
    
    const startNode = this.store.graph.getNode(start) || 
                      this.store.graph.findNodesByName(start)[0];
    
    if (!startNode) {
      return { path: [], data_transformations: [] };
    }
    
    const path: Array<{ node: string; type: string; position?: { start_line: number; end_line: number } }> = [];
    const dataTransformations: string[] = [];
    
    // BFS to find path
    const visited = new Set<string>();
    const parentMap = new Map<string, string>();
    const queue = [startNode.id];
    
    let endNode: SMPNode | undefined;
    if (end) {
      endNode = this.store.graph.getNode(end) || 
                this.store.graph.findNodesByName(end)[0];
    }
    
    // Build path
    while (queue.length > 0 && path.length < max_depth) {
      const currentId = queue.shift()!;
      
      if (visited.has(currentId)) continue;
      visited.add(currentId);
      
      const currentNode = this.store.graph.getNode(currentId);
      if (!currentNode) continue;
      
      path.push({
        node: currentNode.structural.name,
        type: currentNode.structural.type,
        position: currentNode.structural.position,
      });
      
      // Check if we've reached the end
      if (endNode && currentId === endNode.id) break;
      
      // Get next nodes based on flow type
      const nextEdges = flow_type === 'execution'
        ? this.store.graph.getEdgesByType(currentId, 'CALLS', 'outgoing')
        : this.store.graph.getEdges(currentId, 'outgoing');
      
      for (const edge of nextEdges) {
        if (!visited.has(edge.to)) {
          queue.push(edge.to);
          parentMap.set(edge.to, currentId);
          
          // Track data transformation
          if (flow_type === 'data') {
            const toNode = this.store.graph.getNode(edge.to);
            if (toNode) {
              dataTransformations.push(
                `${currentNode.structural.name} → ${toNode.structural.name}`
              );
            }
          }
        }
      }
    }
    
    return {
      path,
      data_transformations: dataTransformations,
    };
  }
  
  // =========================================================================
  // Utility Methods
  // =========================================================================
  
  /**
   * Get all nodes of a specific type
   */
  getNodesByType(type: string): SMPNode[] {
    return this.store.graph.findNodesByType(type as any);
  }
  
  /**
   * Get full graph for visualization
   */
  getGraph(): { nodes: SMPNode[]; edges: GraphEdge[] } {
    return {
      nodes: this.store.graph.getAllNodes(),
      edges: this.store.graph.getAllEdges(),
    };
  }
}

// Factory function
export function createQueryEngine(store: MemoryStore): QueryEngine {
  return new QueryEngine(store);
}
