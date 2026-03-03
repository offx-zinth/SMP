/**
 * SMP Graph Builder Module
 * Creates structural relationships from parsed code
 */

import {
  SMPNode,
  ParsedFile,
  FunctionNode,
  ClassNode,
  InterfaceNode,
  VariableNode,
  NodeType,
  RelationshipType,
  StructuralInfo,
  CodeMetrics,
  Position,
} from '../types';
import { generateNodeId } from './parser';

// ============================================================================
// Graph Builder
// ============================================================================

export interface GraphEdge {
  from: string;
  to: string;
  type: RelationshipType;
  metadata?: Record<string, unknown>;
}

export interface GraphBuildResult {
  nodes: SMPNode[];
  edges: GraphEdge[];
  stats: {
    nodes_created: number;
    edges_created: number;
    parse_errors: string[];
  };
}

/**
 * Calculate code metrics for a function
 */
function calculateMetrics(node: FunctionNode, content: string): CodeMetrics {
  const lines = content.split('\n');
  const nodeContent = lines.slice(node.start_line - 1, node.end_line).join('\n');
  
  // Simple cyclomatic complexity estimation
  const controlFlowPatterns = [
    /\bif\b/g,
    /\belse\s+if\b/g,
    /\bfor\b/g,
    /\bwhile\b/g,
    /\bswitch\b/g,
    /\bcase\b/g,
    /\bcatch\b/g,
    /\?\s*:/g, // ternary
    /&&/g,
    /\|\|/g,
  ];
  
  let complexity = 1;
  for (const pattern of controlFlowPatterns) {
    const matches = nodeContent.match(pattern);
    if (matches) {
      complexity += matches.length;
    }
  }
  
  // Calculate nesting depth
  let maxNesting = 0;
  let currentNesting = 0;
  for (const char of nodeContent) {
    if (char === '{') {
      currentNesting++;
      maxNesting = Math.max(maxNesting, currentNesting);
    } else if (char === '}') {
      currentNesting--;
    }
  }
  
  return {
    complexity,
    lines: node.end_line - node.start_line + 1,
    parameters: node.parameters.length,
    nesting_depth: maxNesting,
    cyclomatic_complexity: complexity,
  };
}

/**
 * Convert parsed node to SMP node
 */
function createSMPNode(
  parsedNode: FunctionNode | ClassNode | InterfaceNode | VariableNode,
  filePath: string,
  content?: string
): SMPNode {
  let nodeType: NodeType;
  let signature: string | undefined;
  let metrics: CodeMetrics | undefined;
  
  if (parsedNode.type === 'function_declaration' || 
      parsedNode.type === 'function_expression' || 
      parsedNode.type === 'arrow_function' ||
      parsedNode.type === 'method_definition') {
    nodeType = 'Function';
    const fn = parsedNode as FunctionNode;
    signature = fn.signature;
    if (content) {
      metrics = calculateMetrics(fn, content);
    }
  } else if (parsedNode.type === 'class_declaration') {
    nodeType = 'Class';
    signature = `class ${parsedNode.name}`;
  } else if (parsedNode.type === 'interface_declaration' || parsedNode.type === 'type_declaration') {
    nodeType = 'Interface';
    signature = `interface ${parsedNode.name}`;
  } else {
    nodeType = 'Variable';
    const vn = parsedNode as VariableNode;
    signature = vn.type_annotation 
      ? `${vn.name}: ${vn.type_annotation}`
      : vn.name;
  }
  
  const structural: StructuralInfo = {
    id: parsedNode.id,
    type: nodeType,
    name: parsedNode.name,
    file: filePath,
    signature,
    position: {
      start_line: parsedNode.start_line,
      end_line: parsedNode.end_line,
    },
    modifiers: parsedNode.modifiers,
    docstring: parsedNode.docstring,
    metrics,
  };
  
  const now = new Date().toISOString();
  
  return {
    id: parsedNode.id,
    structural,
    relationships: {
      CONTAINS: [],
      IMPORTS: [],
      DEFINES: [],
      CALLS: [],
      INHERITS: [],
      IMPLEMENTES: [],
      DEPENDS_ON: [],
      TESTS: [],
      USES: [],
      REFERENCES: [],
      EXPORTS: [],
    },
    created_at: now,
    updated_at: now,
  };
}

/**
 * Build graph from parsed files
 */
export function buildGraph(
  parsedFiles: ParsedFile[],
  contents?: Map<string, string>
): GraphBuildResult {
  const nodes: SMPNode[] = [];
  const edges: GraphEdge[] = [];
  const parseErrors: string[] = [];
  
  // Create node lookup map
  const nodeMap = new Map<string, SMPNode>();
  const functionCalls = new Map<string, string[]>(); // function id -> called function names
  const classNameMap = new Map<string, string>(); // class name -> class id
  
  // Phase 1: Create all nodes
  for (const parsed of parsedFiles) {
    if (parsed.parse_errors && parsed.parse_errors.length > 0) {
      parseErrors.push(...parsed.parse_errors.map(e => `${parsed.file_path}: ${e}`));
    }
    
    // Create file node
    const fileId = generateNodeId('file', parsed.file_path, parsed.file_path);
    const fileNode: SMPNode = {
      id: fileId,
      structural: {
        id: fileId,
        type: 'File',
        name: parsed.file_path.split('/').pop() || parsed.file_path,
        file: parsed.file_path,
        position: { start_line: 1, end_line: 1 },
      },
      relationships: {
        CONTAINS: [],
        IMPORTS: [],
        DEFINES: [],
        CALLS: [],
        INHERITS: [],
        IMPLEMENTES: [],
        DEPENDS_ON: [],
        TESTS: [],
        USES: [],
        REFERENCES: [],
        EXPORTS: [],
      },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    
    nodes.push(fileNode);
    nodeMap.set(fileId, fileNode);
    
    // Create nodes for code entities
    const fileContent = contents?.get(parsed.file_path);
    for (const parsedNode of parsed.nodes) {
      const smpNode = createSMPNode(parsedNode, parsed.file_path, fileContent);
      nodes.push(smpNode);
      nodeMap.set(smpNode.id, smpNode);
      
      // Track class names for inheritance resolution
      if (parsedNode.type === 'class_declaration') {
        classNameMap.set(parsedNode.name, smpNode.id);
      }
      
      // Track function calls
      if ('calls' in parsedNode && parsedNode.calls.length > 0) {
        functionCalls.set(smpNode.id, parsedNode.calls);
      }
      
      // Create DEFINES relationship
      edges.push({
        from: fileId,
        to: smpNode.id,
        type: 'DEFINES',
      });
      
      fileNode.relationships.DEFINES.push(smpNode.id);
    }
  }
  
  // Phase 2: Create relationships
  
  // Create function name to id mapping
  const functionNameMap = new Map<string, string[]>();
  for (const node of nodes) {
    if (node.structural.type === 'Function') {
      const existing = functionNameMap.get(node.structural.name) || [];
      existing.push(node.id);
      functionNameMap.set(node.structural.name, existing);
    }
  }
  
  // Create CALLS relationships
  for (const [callerId, calledNames] of functionCalls) {
    const caller = nodeMap.get(callerId);
    if (!caller) continue;
    
    for (const calledName of calledNames) {
      const targetIds = functionNameMap.get(calledName) || [];
      for (const targetId of targetIds) {
        if (targetId !== callerId) {
          edges.push({
            from: callerId,
            to: targetId,
            type: 'CALLS',
          });
          caller.relationships.CALLS.push(targetId);
        }
      }
    }
  }
  
  // Create IMPORTS relationships
  for (const parsed of parsedFiles) {
    const fileId = generateNodeId('file', parsed.file_path, parsed.file_path);
    const fileNode = nodeMap.get(fileId);
    if (!fileNode) continue;
    
    for (const imp of parsed.imports) {
      // Find imported file
      let importedFilePath = imp.from;
      if (!importedFilePath.startsWith('.')) {
        // External module - create a placeholder
        importedFilePath = `node_modules/${imp.from}`;
      }
      
      const importedFileId = generateNodeId('file', importedFilePath, importedFilePath);
      
      // Check if the imported file node exists
      if (nodeMap.has(importedFileId)) {
        edges.push({
          from: fileId,
          to: importedFileId,
          type: 'IMPORTS',
          metadata: { items: imp.items },
        });
        fileNode.relationships.IMPORTS.push(importedFileId);
      }
    }
  }
  
  // Create INHERITS and IMPLEMENTS relationships
  for (const parsed of parsedFiles) {
    for (const node of parsed.nodes) {
      if (node.type === 'class_declaration') {
        const classNode = nodeMap.get(node.id);
        if (!classNode) continue;
        
        // Inheritance
        if (node.extends) {
          const parentId = classNameMap.get(node.extends);
          if (parentId) {
            edges.push({
              from: node.id,
              to: parentId,
              type: 'INHERITS',
            });
            classNode.relationships.INHERITS.push(parentId);
          }
        }
        
        // Interface implementation
        for (const iface of node.implements) {
          const ifaceId = classNameMap.get(iface);
          if (ifaceId) {
            edges.push({
              from: node.id,
              to: ifaceId,
              type: 'IMPLEMENTES',
            });
            classNode.relationships.IMPLEMENTES.push(ifaceId);
          }
        }
      }
    }
  }
  
  // Create TESTS relationships
  for (const parsed of parsedFiles) {
    // Check if this is a test file
    if (parsed.file_path.includes('.test.') || 
        parsed.file_path.includes('.spec.') || 
        parsed.file_path.includes('test_')) {
      const fileId = generateNodeId('file', parsed.file_path, parsed.file_path);
      const fileNode = nodeMap.get(fileId);
      if (!fileNode) continue;
      
      // Mark as test file
      fileNode.structural.type = 'Test';
      
      // Find what's being tested
      for (const node of parsed.nodes) {
        if ('calls' in node && node.calls) {
          for (const calledName of node.calls) {
            const targetIds = functionNameMap.get(calledName) || [];
            for (const targetId of targetIds) {
              if (targetId !== node.id) {
                edges.push({
                  from: node.id,
                  to: targetId,
                  type: 'TESTS',
                });
              }
            }
          }
        }
      }
    }
  }
  
  return {
    nodes,
    edges,
    stats: {
      nodes_created: nodes.length,
      edges_created: edges.length,
      parse_errors: parseErrors,
    },
  };
}

/**
 * Merge new graph with existing graph
 */
export function mergeGraphs(
  existing: { nodes: SMPNode[]; edges: GraphEdge[] },
  updates: GraphBuildResult
): GraphBuildResult {
  const existingNodeIds = new Set(existing.nodes.map(n => n.id));
  const existingEdgeKeys = new Set(
    existing.edges.map(e => `${e.from}:${e.to}:${e.type}`)
  );
  
  const newNodes: SMPNode[] = [];
  const newEdges: GraphEdge[] = [];
  
  // Add new nodes
  for (const node of updates.nodes) {
    if (!existingNodeIds.has(node.id)) {
      newNodes.push(node);
    }
  }
  
  // Add new edges
  for (const edge of updates.edges) {
    const key = `${edge.from}:${edge.to}:${edge.type}`;
    if (!existingEdgeKeys.has(key)) {
      newEdges.push(edge);
    }
  }
  
  return {
    nodes: newNodes,
    edges: newEdges,
    stats: updates.stats,
  };
}
