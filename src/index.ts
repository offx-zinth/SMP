/**
 * Structural Memory Protocol (SMP)
 * Main entry point
 */

// Types
export * from './types';

// Core modules
export { parseFile, parseFiles, detectLanguage, generateNodeId } from './core/parser';
export { buildGraph, mergeGraphs } from './core/graph-builder';
export { enrichNode, enrichNodes, batchEnrich } from './core/enricher';
export { 
  MemoryStore, 
  MemoryGraphStore, 
  MemoryVectorStore, 
  getMemoryStore, 
  resetMemoryStore 
} from './core/store';

// Query engine
export { QueryEngine, createQueryEngine } from './engine/query';

// Protocol
export { SMPProtocolHandler, getProtocolHandler, resetProtocolHandler } from './protocol/handler';

// Client
export { SMPClient, createSMPClient, createBrowserClient } from './client';
