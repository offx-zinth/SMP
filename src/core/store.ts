/**
 * SMP Memory Store Module
 * Graph DB + Vector Store implementation
 */

import {
  SMPNode,
  NodeType,
  RelationshipType,
  GraphStats,
  VectorSearchResult,
} from '../types';
import { GraphEdge } from './graph-builder';

// ============================================================================
// In-Memory Store (Development/Testing)
// ============================================================================

/**
 * In-memory graph store for development
 */
export class MemoryGraphStore {
  private nodes: Map<string, SMPNode> = new Map();
  private edges: Map<string, GraphEdge[]> = new Map(); // from_id -> edges
  private reverseEdges: Map<string, GraphEdge[]> = new Map(); // to_id -> edges
  private nameIndex: Map<string, Set<string>> = new Map(); // name -> node_ids
  private fileIndex: Map<string, Set<string>> = new Map(); // file -> node_ids
  private typeIndex: Map<NodeType, Set<string>> = new Map(); // type -> node_ids
  
  // Initialize with empty sets for each type
  constructor() {
    const types: NodeType[] = ['Repository', 'Package', 'File', 'Class', 'Function', 'Variable', 'Interface', 'Type', 'Method', 'Property', 'Test', 'Config'];
    for (const type of types) {
      this.typeIndex.set(type, new Set());
    }
  }
  
  // Node operations
  addNode(node: SMPNode): void {
    this.nodes.set(node.id, node);
    
    // Update indices
    const name = node.structural.name.toLowerCase();
    if (!this.nameIndex.has(name)) {
      this.nameIndex.set(name, new Set());
    }
    this.nameIndex.get(name)!.add(node.id);
    
    if (!this.fileIndex.has(node.structural.file)) {
      this.fileIndex.set(node.structural.file, new Set());
    }
    this.fileIndex.get(node.structural.file)!.add(node.id);
    
    this.typeIndex.get(node.structural.type)?.add(node.id);
  }
  
  getNode(id: string): SMPNode | undefined {
    return this.nodes.get(id);
  }
  
  updateNode(id: string, updates: Partial<SMPNode>): SMPNode | undefined {
    const node = this.nodes.get(id);
    if (!node) return undefined;
    
    const updated = {
      ...node,
      ...updates,
      updated_at: new Date().toISOString(),
    };
    
    this.nodes.set(id, updated);
    return updated;
  }
  
  deleteNode(id: string): boolean {
    const node = this.nodes.get(id);
    if (!node) return false;
    
    // Remove from indices
    const name = node.structural.name.toLowerCase();
    this.nameIndex.get(name)?.delete(id);
    this.fileIndex.get(node.structural.file)?.delete(id);
    this.typeIndex.get(node.structural.type)?.delete(id);
    
    // Remove node
    this.nodes.delete(id);
    
    // Remove edges
    this.edges.delete(id);
    this.reverseEdges.delete(id);
    
    return true;
  }
  
  // Edge operations
  addEdge(edge: GraphEdge): void {
    // Forward edge
    if (!this.edges.has(edge.from)) {
      this.edges.set(edge.from, []);
    }
    this.edges.get(edge.from)!.push(edge);
    
    // Reverse edge
    if (!this.reverseEdges.has(edge.to)) {
      this.reverseEdges.set(edge.to, []);
    }
    this.reverseEdges.get(edge.to)!.push(edge);
  }
  
  getEdges(nodeId: string, direction: 'outgoing' | 'incoming' | 'both' = 'outgoing'): GraphEdge[] {
    const result: GraphEdge[] = [];
    
    if (direction === 'outgoing' || direction === 'both') {
      result.push(...(this.edges.get(nodeId) || []));
    }
    
    if (direction === 'incoming' || direction === 'both') {
      result.push(...(this.reverseEdges.get(nodeId) || []));
    }
    
    return result;
  }
  
  getEdgesByType(nodeId: string, type: RelationshipType, direction: 'outgoing' | 'incoming' | 'both' = 'outgoing'): GraphEdge[] {
    return this.getEdges(nodeId, direction).filter(e => e.type === type);
  }
  
  deleteEdge(from: string, to: string, type: RelationshipType): boolean {
    const edges = this.edges.get(from);
    if (!edges) return false;
    
    const index = edges.findIndex(e => e.to === to && e.type === type);
    if (index === -1) return false;
    
    edges.splice(index, 1);
    
    // Remove from reverse
    const reverseEdges = this.reverseEdges.get(to);
    if (reverseEdges) {
      const revIndex = reverseEdges.findIndex(e => e.from === from && e.type === type);
      if (revIndex !== -1) {
        reverseEdges.splice(revIndex, 1);
      }
    }
    
    return true;
  }
  
  // Query operations
  findNodesByName(name: string): SMPNode[] {
    const ids = this.nameIndex.get(name.toLowerCase());
    if (!ids) return [];
    return Array.from(ids).map(id => this.nodes.get(id)!).filter(Boolean);
  }
  
  findNodesByFile(file: string): SMPNode[] {
    const ids = this.fileIndex.get(file);
    if (!ids) return [];
    return Array.from(ids).map(id => this.nodes.get(id)!).filter(Boolean);
  }
  
  findNodesByType(type: NodeType): SMPNode[] {
    const ids = this.typeIndex.get(type);
    if (!ids) return [];
    return Array.from(ids).map(id => this.nodes.get(id)!).filter(Boolean);
  }
  
  findNodeByPath(file: string, name?: string): SMPNode | undefined {
    const fileNodes = this.findNodesByFile(file);
    if (!name) {
      return fileNodes.find(n => n.structural.type === 'File');
    }
    return fileNodes.find(n => n.structural.name === name);
  }
  
  // Relationship traversal
  traverse(startId: string, relationshipType: RelationshipType, direction: 'outgoing' | 'incoming' = 'outgoing', depth: number = 3): Map<string, number> {
    const visited = new Map<string, number>();
    const queue: Array<{ id: string; level: number }> = [{ id: startId, level: 0 }];
    
    while (queue.length > 0) {
      const { id, level } = queue.shift()!;
      
      if (visited.has(id)) continue;
      visited.set(id, level);
      
      if (level >= depth) continue;
      
      const edges = this.getEdgesByType(id, relationshipType, direction);
      for (const edge of edges) {
        const nextId = direction === 'outgoing' ? edge.to : edge.from;
        if (!visited.has(nextId)) {
          queue.push({ id: nextId, level: level + 1 });
        }
      }
    }
    
    return visited;
  }
  
  // Stats
  getStats(): GraphStats {
    const nodesByType: Record<NodeType, number> = {} as Record<NodeType, number>;
    for (const [type, ids] of this.typeIndex) {
      nodesByType[type] = ids.size;
    }
    
    let totalRelationships = 0;
    const relationshipsByType: Record<RelationshipType, number> = {} as Record<RelationshipType, number>;
    
    for (const edges of this.edges.values()) {
      for (const edge of edges) {
        totalRelationships++;
        relationshipsByType[edge.type] = (relationshipsByType[edge.type] || 0) + 1;
      }
    }
    
    return {
      total_nodes: this.nodes.size,
      total_relationships: totalRelationships,
      nodes_by_type: nodesByType,
      relationships_by_type: relationshipsByType,
      last_indexed: new Date().toISOString(),
    };
  }
  
  // Bulk operations
  clear(): void {
    this.nodes.clear();
    this.edges.clear();
    this.reverseEdges.clear();
    this.nameIndex.clear();
    this.fileIndex.clear();
    
    const types: NodeType[] = ['Repository', 'Package', 'File', 'Class', 'Function', 'Variable', 'Interface', 'Type', 'Method', 'Property', 'Test', 'Config'];
    for (const type of types) {
      this.typeIndex.set(type, new Set());
    }
  }
  
  getAllNodes(): SMPNode[] {
    return Array.from(this.nodes.values());
  }
  
  getAllEdges(): GraphEdge[] {
    const result: GraphEdge[] = [];
    for (const edges of this.edges.values()) {
      result.push(...edges);
    }
    return result;
  }
}

// ============================================================================
// Vector Store
// ============================================================================

/**
 * In-memory vector store for semantic search
 */
export class MemoryVectorStore {
  private vectors: Map<string, number[]> = new Map();
  private dimensions: number = 384;
  
  addVector(id: string, vector: number[]): void {
    if (vector.length !== this.dimensions) {
      console.warn(`Vector dimension mismatch: expected ${this.dimensions}, got ${vector.length}`);
    }
    this.vectors.set(id, vector);
  }
  
  getVector(id: string): number[] | undefined {
    return this.vectors.get(id);
  }
  
  deleteVector(id: string): boolean {
    return this.vectors.delete(id);
  }
  
  /**
   * Calculate cosine similarity between two vectors
   */
  cosineSimilarity(a: number[], b: number[]): number {
    if (a.length !== b.length) return 0;
    
    let dotProduct = 0;
    let magnitudeA = 0;
    let magnitudeB = 0;
    
    for (let i = 0; i < a.length; i++) {
      dotProduct += a[i] * b[i];
      magnitudeA += a[i] * a[i];
      magnitudeB += b[i] * b[i];
    }
    
    magnitudeA = Math.sqrt(magnitudeA);
    magnitudeB = Math.sqrt(magnitudeB);
    
    if (magnitudeA === 0 || magnitudeB === 0) return 0;
    
    return dotProduct / (magnitudeA * magnitudeB);
  }
  
  /**
   * Find similar vectors
   */
  findSimilar(queryVector: number[], topK: number = 5): VectorSearchResult[] {
    const similarities: Array<{ id: string; score: number }> = [];
    
    for (const [id, vector] of this.vectors) {
      const score = this.cosineSimilarity(queryVector, vector);
      similarities.push({ id, score });
    }
    
    // Sort by score descending
    similarities.sort((a, b) => b.score - a.score);
    
    return similarities.slice(0, topK).map(s => ({
      id: s.id,
      score: s.score,
      node: null as unknown as SMPNode, // Will be filled by query engine
    }));
  }
  
  /**
   * Find by text similarity (simple keyword matching as fallback)
   */
  findByKeywords(keywords: string[], nodeStore: MemoryGraphStore, topK: number = 5): VectorSearchResult[] {
    const results: Array<{ id: string; score: number }> = [];
    
    for (const node of nodeStore.getAllNodes()) {
      if (!node.semantic?.keywords) continue;
      
      let matchCount = 0;
      for (const keyword of keywords) {
        if (node.semantic.keywords.some(k => k.includes(keyword.toLowerCase()))) {
          matchCount++;
        }
      }
      
      if (matchCount > 0) {
        const score = matchCount / keywords.length;
        results.push({ id: node.id, score });
      }
    }
    
    results.sort((a, b) => b.score - a.score);
    
    return results.slice(0, topK).map(s => ({
      id: s.id,
      score: s.score,
      node: nodeStore.getNode(s.id)!,
    }));
  }
  
  clear(): void {
    this.vectors.clear();
  }
  
  getStats(): { total_vectors: number; dimensions: number } {
    return {
      total_vectors: this.vectors.size,
      dimensions: this.dimensions,
    };
  }
}

// ============================================================================
// Combined Memory Store
// ============================================================================

export class MemoryStore {
  graph: MemoryGraphStore;
  vectors: MemoryVectorStore;
  
  constructor() {
    this.graph = new MemoryGraphStore();
    this.vectors = new MemoryVectorStore();
  }
  
  /**
   * Add a node with its embedding
   */
  addNode(node: SMPNode): void {
    this.graph.addNode(node);
    
    if (node.semantic?.embedding) {
      this.vectors.addVector(node.id, node.semantic.embedding);
    }
  }
  
  /**
   * Update node and its embedding
   */
  updateNode(id: string, updates: Partial<SMPNode>): SMPNode | undefined {
    const updated = this.graph.updateNode(id, updates);
    
    if (updated?.semantic?.embedding) {
      this.vectors.addVector(id, updated.semantic.embedding);
    }
    
    return updated;
  }
  
  /**
   * Delete node and its embedding
   */
  deleteNode(id: string): boolean {
    this.vectors.deleteVector(id);
    return this.graph.deleteNode(id);
  }
  
  /**
   * Semantic search
   */
  semanticSearch(query: string, topK: number = 5): VectorSearchResult[] {
    // Simple keyword-based search as fallback
    const keywords = query.toLowerCase().split(/\s+/);
    return this.vectors.findByKeywords(keywords, this.graph, topK);
  }
  
  /**
   * Clear all data
   */
  clear(): void {
    this.graph.clear();
    this.vectors.clear();
  }
  
  /**
   * Get combined stats
   */
  getStats(): GraphStats & { vectors: { total: number; dimensions: number } } {
    const graphStats = this.graph.getStats();
    const vectorStats = this.vectors.getStats();
    
    return {
      ...graphStats,
      vectors: {
        total: vectorStats.total_vectors,
        dimensions: vectorStats.dimensions,
      },
    };
  }
}

// Singleton instance
let memoryStoreInstance: MemoryStore | null = null;

export function getMemoryStore(): MemoryStore {
  if (!memoryStoreInstance) {
    memoryStoreInstance = new MemoryStore();
  }
  return memoryStoreInstance;
}

export function resetMemoryStore(): void {
  memoryStoreInstance = new MemoryStore();
}
