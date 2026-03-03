/**
 * Structural Memory Protocol (SMP) Types
 * Version 1.0
 */

// ============================================================================
// Node Types
// ============================================================================

export type NodeType =
  | 'Repository'
  | 'Package'
  | 'File'
  | 'Class'
  | 'Function'
  | 'Variable'
  | 'Interface'
  | 'Type'
  | 'Method'
  | 'Property'
  | 'Test'
  | 'Config';

// ============================================================================
// Relationship Types
// ============================================================================

export type RelationshipType =
  | 'CONTAINS'      // Parent-child (Package → File)
  | 'IMPORTS'       // File imports File/Module
  | 'DEFINES'       // File defines Class/Function
  | 'CALLS'         // Function calls Function
  | 'INHERITS'      // Class inherits Class
  | 'IMPLEMENTES'   // Class implements Interface
  | 'DEPENDS_ON'    // General dependency
  | 'TESTS'         // Test tests Function/Class
  | 'USES'          // Function uses Variable/Type
  | 'REFERENCES'    // Variable references Variable
  | 'EXPORTS';      // File exports Symbol

// ============================================================================
// Core Node Interfaces
// ============================================================================

export interface CodeMetrics {
  complexity: number;
  lines: number;
  parameters: number;
  nesting_depth?: number;
  cyclomatic_complexity?: number;
}

export interface Position {
  start_line: number;
  end_line: number;
  start_column?: number;
  end_column?: number;
}

export interface StructuralInfo {
  id: string;
  type: NodeType;
  name: string;
  file: string;
  signature?: string;
  position: Position;
  modifiers?: string[];
  docstring?: string;
  metrics?: CodeMetrics;
}

export interface SemanticInfo {
  purpose: string;
  keywords: string[];
  embedding?: number[];
  last_enriched: string;
  confidence: number;
}

export interface SMPNode {
  id: string;
  structural: StructuralInfo;
  semantic?: SemanticInfo;
  relationships: Record<RelationshipType, string[]>;
  created_at: string;
  updated_at: string;
}

// ============================================================================
// Parse Results
// ============================================================================

export interface ImportInfo {
  from: string;
  items: string[];
  is_default?: boolean;
  is_namespace?: boolean;
}

export interface ExportInfo {
  name: string;
  type: NodeType;
  is_default?: boolean;
}

export interface FunctionNode {
  id: string;
  type: 'function_declaration' | 'function_expression' | 'arrow_function' | 'method_definition';
  name: string;
  start_line: number;
  end_line: number;
  signature: string;
  docstring?: string;
  modifiers: string[];
  parameters: string[];
  return_type?: string;
  calls: string[];
  uses: string[];
}

export interface ClassNode {
  id: string;
  type: 'class_declaration';
  name: string;
  start_line: number;
  end_line: number;
  docstring?: string;
  modifiers: string[];
  methods: string[];
  properties: string[];
  extends?: string;
  implements: string[];
}

export interface InterfaceNode {
  id: string;
  type: 'interface_declaration' | 'type_declaration';
  name: string;
  start_line: number;
  end_line: number;
  docstring?: string;
  methods: string[];
  properties: string[];
  extends?: string[];
}

export interface VariableNode {
  id: string;
  type: 'variable_declaration' | 'const_declaration' | 'let_declaration';
  name: string;
  start_line: number;
  end_line: number;
  type_annotation?: string;
  initial_value?: string;
}

export interface ParsedFile {
  file_path: string;
  language: string;
  nodes: (FunctionNode | ClassNode | InterfaceNode | VariableNode)[];
  imports: ImportInfo[];
  exports: ExportInfo[];
  parse_errors?: string[];
}

// ============================================================================
// Query Types
// ============================================================================

export type QueryType =
  | 'navigate'    // Find specific entities
  | 'trace'       // Follow relationships
  | 'context'     // Get relevant context
  | 'impact'      // Assess change impact
  | 'locate'      // Find by description
  | 'flow';       // Trace data/logic path

export interface NavigateQuery {
  entity_name: string;
  direction?: 'to' | 'from' | 'both';
  include_relationships?: boolean;
}

export interface TraceQuery {
  start_id: string;
  relationship_type: RelationshipType;
  depth?: number;
  direction?: 'incoming' | 'outgoing' | 'both';
}

export interface ContextQuery {
  file_path: string;
  scope: 'edit' | 'create' | 'debug' | 'review';
  depth?: number;
}

export interface ImpactQuery {
  entity_id: string;
  change_type: 'signature_change' | 'delete' | 'move' | 'rename';
}

export interface LocateQuery {
  description: string;
  top_k?: number;
}

export interface FlowQuery {
  start: string;
  end?: string;
  flow_type: 'data' | 'execution';
  max_depth?: number;
}

// ============================================================================
// Query Results
// ============================================================================

export interface NavigateResult {
  entity: SMPNode | null;
  relationships?: Record<string, string[]>;
}

export interface TraceResult {
  root: string;
  tree: Record<string, unknown>;
  depth: number;
}

export interface ContextResult {
  self: SMPNode;
  imports: SMPNode[];
  imported_by: SMPNode[];
  defines: SMPNode[];
  tests: string[];
  patterns: Array<{ entity: SMPNode; similarity: number }>;
  warnings: string[];
  data_flow_in?: string[];
  data_flow_out?: string[];
}

export interface ImpactResult {
  affected_files: string[];
  affected_functions: string[];
  affected_classes: string[];
  severity: 'low' | 'medium' | 'high' | 'critical';
  recommendations: string[];
  breaking_changes: string[];
}

export interface LocateResult {
  matches: Array<{
    entity: SMPNode;
    relevance: number;
    highlight?: string;
  }>;
}

export interface FlowResult {
  path: Array<{
    node: string;
    type: string;
    position?: Position;
  }>;
  data_transformations: string[];
  branches?: string[];
}

// ============================================================================
// Protocol Types
// ============================================================================

export interface SMPRequest {
  jsonrpc: '2.0';
  method: string;
  params?: Record<string, unknown>;
  id?: string | number;
}

export interface SMPResponse<T = unknown> {
  jsonrpc: '2.0';
  result?: T;
  error?: {
    code: number;
    message: string;
    data?: unknown;
  };
  id?: string | number;
}

export interface SMPNotification {
  jsonrpc: '2.0';
  method: string;
  params: Record<string, unknown>;
}

// ============================================================================
// Update Types
// ============================================================================

export type ChangeType = 'created' | 'modified' | 'deleted';

export interface FileChange {
  file_path: string;
  content?: string;
  change_type: ChangeType;
}

export interface UpdateResult {
  status: 'success' | 'partial' | 'failed';
  nodes_added: number;
  nodes_updated: number;
  nodes_removed: number;
  relationships_updated: number;
  errors?: string[];
}

// ============================================================================
// Memory Store Types
// ============================================================================

export interface GraphStats {
  total_nodes: number;
  total_relationships: number;
  nodes_by_type: Record<NodeType, number>;
  relationships_by_type: Record<RelationshipType, number>;
  last_indexed: string;
}

export interface VectorSearchResult {
  id: string;
  score: number;
  node: SMPNode;
}
