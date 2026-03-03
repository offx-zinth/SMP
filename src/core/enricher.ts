/**
 * SMP Semantic Enricher Module
 * Adds semantic meaning to structural nodes
 */

import {
  SMPNode,
  SemanticInfo,
} from '../types';
import ZAI from 'z-ai-web-dev-sdk';

// ============================================================================
// Enrichment Types
// ============================================================================

export interface EnrichmentConfig {
  useLLM: boolean;
  batchSize: number;
  maxRetries: number;
}

export interface EnrichmentResult {
  node: SMPNode;
  enriched: boolean;
  error?: string;
}

// ============================================================================
// Static Enrichment (No LLM)
// ============================================================================

/**
 * Extract keywords from code structure
 */
function extractKeywords(node: SMPNode): string[] {
  const keywords = new Set<string>();
  
  // From name (camelCase/snake_case splitting)
  const name = node.structural.name;
  const nameParts = name.split(/(?=[A-Z])|_/).filter(Boolean);
  nameParts.forEach(part => {
    if (part.length > 2) {
      keywords.add(part.toLowerCase());
    }
  });
  
  // From docstring
  if (node.structural.docstring) {
    const docstring = node.structural.docstring
      .replace(/\/\*\*/g, '')
      .replace(/\*\//g, '')
      .replace(/\*/g, '')
      .replace(/@param/g, '')
      .replace(/@returns/g, '')
      .replace(/@throws/g, '');
    
    const words = docstring.split(/\s+/);
    words.forEach(word => {
      const cleaned = word.toLowerCase().replace(/[^a-z]/g, '');
      if (cleaned.length > 3 && !isCommonWord(cleaned)) {
        keywords.add(cleaned);
      }
    });
  }
  
  // From signature
  if (node.structural.signature) {
    const sigParts = node.structural.signature
      .split(/[<>,:\(\)\[\]{}]/)
      .filter(s => s.length > 2);
    sigParts.forEach(part => {
      keywords.add(part.trim().toLowerCase());
    });
  }
  
  // From file path
  const pathParts = node.structural.file.split('/');
  pathParts.forEach(part => {
    if (part && !part.includes('.')) {
      keywords.add(part.toLowerCase());
    }
  });
  
  return Array.from(keywords).slice(0, 10);
}

/**
 * Common words to exclude from keywords
 */
const COMMON_WORDS = new Set([
  'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had',
  'her', 'was', 'one', 'our', 'out', 'has', 'his', 'how', 'its', 'may',
  'new', 'now', 'old', 'see', 'two', 'way', 'who', 'did', 'get', 'let',
  'put', 'say', 'she', 'too', 'use', 'this', 'that', 'with', 'from',
  'have', 'will', 'been', 'when', 'into', 'than', 'them', 'some', 'such',
  'then', 'only', 'over', 'also', 'back', 'after', 'most', 'other',
]);

function isCommonWord(word: string): boolean {
  return COMMON_WORDS.has(word);
}

/**
 * Infer purpose from structure
 */
function inferPurpose(node: SMPNode): string {
  const name = node.structural.name;
  const type = node.structural.type;
  const keywords = extractKeywords(node);
  
  // Common patterns
  const patterns: Array<{ pattern: RegExp; template: (m: RegExpMatchArray) => string }> = [
    // CRUD operations
    { pattern: /^get(\w+)/i, template: (m) => `Retrieves ${m[1].toLowerCase()} data from the system` },
    { pattern: /^fetch(\w+)/i, template: (m) => `Fetches ${m[1].toLowerCase()} from external source or database` },
    { pattern: /^find(\w+)/i, template: (m) => `Searches for ${m[1].toLowerCase()} matching criteria` },
    { pattern: /^create(\w+)/i, template: (m) => `Creates a new ${m[1].toLowerCase()} instance` },
    { pattern: /^add(\w+)/i, template: (m) => `Adds a new ${m[1].toLowerCase()} to the system` },
    { pattern: /^update(\w+)/i, template: (m) => `Updates existing ${m[1].toLowerCase()} with new data` },
    { pattern: /^delete(\w+)/i, template: (m) => `Deletes ${m[1].toLowerCase()} from the system` },
    { pattern: /^remove(\w+)/i, template: (m) => `Removes ${m[1].toLowerCase()} from the collection` },
    { pattern: /^save(\w+)/i, template: (m) => `Persists ${m[1].toLowerCase()} to storage` },
    
    // Validation
    { pattern: /^validate(\w+)/i, template: (m) => `Validates ${m[1].toLowerCase()} input or data` },
    { pattern: /^check(\w+)/i, template: (m) => `Checks ${m[1].toLowerCase()} condition or status` },
    { pattern: /^verify(\w+)/i, template: (m) => `Verifies ${m[1].toLowerCase()} authenticity or validity` },
    { pattern: /^is(\w+)/i, template: (m) => `Returns boolean indicating ${m[1].toLowerCase()} state` },
    { pattern: /^has(\w+)/i, template: (m) => `Checks if ${m[1].toLowerCase()} exists or is present` },
    { pattern: /^can(\w+)/i, template: (m) => `Checks permission or ability to ${m[1].toLowerCase()}` },
    
    // Transformation
    { pattern: /^parse(\w+)/i, template: (m) => `Parses ${m[1].toLowerCase()} into structured format` },
    { pattern: /^format(\w+)/i, template: (m) => `Formats ${m[1].toLowerCase()} for display or output` },
    { pattern: /^convert(\w+)/i, template: (m) => `Converts ${m[1].toLowerCase()} to another format` },
    { pattern: /^transform(\w+)/i, template: (m) => `Transforms ${m[1].toLowerCase()} data` },
    { pattern: /^build(\w+)/i, template: (m) => `Builds or constructs ${m[1].toLowerCase()}` },
    { pattern: /^generate(\w+)/i, template: (m) => `Generates ${m[1].toLowerCase()} programmatically` },
    
    // Events & Handlers
    { pattern: /^on(\w+)/i, template: (m) => `Handles ${m[1].toLowerCase()} event` },
    { pattern: /^handle(\w+)/i, template: (m) => `Handles ${m[1].toLowerCase()} logic or event` },
    { pattern: /^process(\w+)/i, template: (m) => `Processes ${m[1].toLowerCase()} data or request` },
    
    // Rendering
    { pattern: /^render(\w+)/i, template: (m) => `Renders ${m[1].toLowerCase()} UI component` },
    { pattern: /^display(\w+)/i, template: (m) => `Displays ${m[1].toLowerCase()} to user` },
    { pattern: /^show(\w+)/i, template: (m) => `Shows ${m[1].toLowerCase()} in the interface` },
    
    // Initialization
    { pattern: /^init(\w*)/i, template: (m) => `Initializes ${m[1] || 'component'} setup` },
    { pattern: /^setup(\w+)/i, template: (m) => `Sets up ${m[1].toLowerCase()} configuration` },
    { pattern: /^load(\w+)/i, template: (m) => `Loads ${m[1].toLowerCase()} from source` },
    
    // Utilities
    { pattern: /^calculate(\w+)/i, template: (m) => `Calculates ${m[1].toLowerCase()} value` },
    { pattern: /^compute(\w+)/i, template: (m) => `Computes ${m[1].toLowerCase()} result` },
    { pattern: /^encode(\w+)/i, template: (m) => `Encodes ${m[1].toLowerCase()} data` },
    { pattern: /^decode(\w+)/i, template: (m) => `Decodes ${m[1].toLowerCase()} data` },
    { pattern: /^encrypt(\w+)/i, template: (m) => `Encrypts ${m[1].toLowerCase()} for security` },
    { pattern: /^decrypt(\w+)/i, template: (m) => `Decrypts ${m[1].toLowerCase()} data` },
  ];
  
  // Try to match patterns
  for (const { pattern, template } of patterns) {
    const match = name.match(pattern);
    if (match) {
      return template(match);
    }
  }
  
  // Type-based inference
  if (type === 'Class') {
    return `Defines the ${name} class which encapsulates ${keywords.slice(0, 3).join(', ')} functionality`;
  }
  
  if (type === 'Interface') {
    return `Defines the ${name} interface contract for ${keywords.slice(0, 3).join(', ')}`;
  }
  
  if (type === 'Variable') {
    return `Stores ${keywords.includes('const') ? 'constant' : ''} ${name} value`;
  }
  
  // Default
  return `${type} ${name} in ${node.structural.file.split('/').pop()}`;
}

// ============================================================================
// LLM Enrichment
// ============================================================================

/**
 * Generate purpose using LLM
 */
async function generatePurposeWithLLM(node: SMPNode): Promise<string> {
  try {
    const zai = await ZAI.create();
    
    const context = [
      `Type: ${node.structural.type}`,
      `Name: ${node.structural.name}`,
      `File: ${node.structural.file}`,
      node.structural.signature ? `Signature: ${node.structural.signature}` : null,
      node.structural.docstring ? `Documentation: ${node.structural.docstring}` : null,
      node.relationships.CALLS.length > 0 ? `Calls: ${node.relationships.CALLS.slice(0, 5).join(', ')}` : null,
    ].filter(Boolean).join('\n');
    
    const completion = await zai.chat.completions.create({
      messages: [
        {
          role: 'system',
          content: 'You are a code analysis assistant. Describe the purpose of code in one concise sentence. Focus on WHAT the code does, not HOW. Be specific.',
        },
        {
          role: 'user',
          content: `What is the purpose of this code?\n\n${context}`,
        },
      ],
      max_tokens: 100,
      temperature: 0.3,
    });
    
    return completion.choices[0]?.message?.content?.trim() || inferPurpose(node);
  } catch (error) {
    console.error('LLM enrichment failed:', error);
    return inferPurpose(node);
  }
}

/**
 * Generate embedding for node
 */
async function generateEmbedding(node: SMPNode): Promise<number[]> {
  try {
    const zai = await ZAI.create();
    
    // Create text to embed
    const text = [
      node.structural.name,
      node.semantic?.purpose || '',
      node.structural.signature || '',
      node.structural.docstring || '',
    ].filter(Boolean).join(' ');
    
    // Note: The SDK might have an embeddings API
    // For now, we'll use a placeholder or the chat completion
    // In a real implementation, you'd use text-embedding-3-small
    
    // Placeholder: create a simple hash-based vector
    // In production, use actual embeddings API
    const embedding = new Array(384).fill(0);
    for (let i = 0; i < text.length; i++) {
      embedding[i % 384] += text.charCodeAt(i) / 1000;
    }
    
    // Normalize
    const magnitude = Math.sqrt(embedding.reduce((sum, v) => sum + v * v, 0));
    return embedding.map(v => v / magnitude);
  } catch (error) {
    console.error('Embedding generation failed:', error);
    return [];
  }
}

// ============================================================================
// Main Enricher
// ============================================================================

/**
 * Enrich a single node with semantic information
 */
export async function enrichNode(
  node: SMPNode,
  config: Partial<EnrichmentConfig> = {}
): Promise<EnrichmentResult> {
  const finalConfig: EnrichmentConfig = {
    useLLM: config.useLLM ?? false,
    batchSize: config.batchSize ?? 10,
    maxRetries: config.maxRetries ?? 3,
  };
  
  try {
    // Extract keywords (always do this)
    const keywords = extractKeywords(node);
    
    // Generate purpose
    let purpose: string;
    if (finalConfig.useLLM) {
      purpose = await generatePurposeWithLLM(node);
    } else {
      purpose = inferPurpose(node);
    }
    
    // Generate embedding (optional, for semantic search)
    let embedding: number[] = [];
    if (finalConfig.useLLM) {
      embedding = await generateEmbedding(node);
    }
    
    const semantic: SemanticInfo = {
      purpose,
      keywords,
      embedding: embedding.length > 0 ? embedding : undefined,
      last_enriched: new Date().toISOString(),
      confidence: finalConfig.useLLM ? 0.9 : 0.7,
    };
    
    const enrichedNode: SMPNode = {
      ...node,
      semantic,
      updated_at: new Date().toISOString(),
    };
    
    return {
      node: enrichedNode,
      enriched: true,
    };
  } catch (error) {
    return {
      node,
      enriched: false,
      error: error instanceof Error ? error.message : 'Unknown error',
    };
  }
}

/**
 * Enrich multiple nodes
 */
export async function enrichNodes(
  nodes: SMPNode[],
  config: Partial<EnrichmentConfig> = {}
): Promise<EnrichmentResult[]> {
  const results: EnrichmentResult[] = [];
  
  for (const node of nodes) {
    const result = await enrichNode(node, config);
    results.push(result);
  }
  
  return results;
}

/**
 * Batch enrich with progress callback
 */
export async function batchEnrich(
  nodes: SMPNode[],
  config: Partial<EnrichmentConfig> = {},
  onProgress?: (completed: number, total: number) => void
): Promise<EnrichmentResult[]> {
  const batchSize = config.batchSize ?? 10;
  const results: EnrichmentResult[] = [];
  
  for (let i = 0; i < nodes.length; i += batchSize) {
    const batch = nodes.slice(i, i + batchSize);
    const batchResults = await enrichNodes(batch, config);
    results.push(...batchResults);
    
    if (onProgress) {
      onProgress(Math.min(i + batchSize, nodes.length), nodes.length);
    }
  }
  
  return results;
}

export { extractKeywords, inferPurpose };
