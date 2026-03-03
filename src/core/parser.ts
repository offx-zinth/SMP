/**
 * SMP Parser Module
 * Extracts AST-like structure from source code
 */

import {
  ParsedFile,
  FunctionNode,
  ClassNode,
  InterfaceNode,
  VariableNode,
  ImportInfo,
  ExportInfo,
  NodeType,
} from '../types';

// Language detection
function detectLanguage(filePath: string): string {
  const ext = filePath.split('.').pop()?.toLowerCase();
  const languageMap: Record<string, string> = {
    ts: 'typescript',
    tsx: 'typescript',
    js: 'javascript',
    jsx: 'javascript',
    py: 'python',
    rs: 'rust',
    go: 'go',
    java: 'java',
    c: 'c',
    cpp: 'cpp',
    h: 'c',
    hpp: 'cpp',
    rb: 'ruby',
    php: 'php',
    swift: 'swift',
    kt: 'kotlin',
    scala: 'scala',
  };
  return languageMap[ext || ''] || 'unknown';
}

// Generate unique ID for a node
function generateNodeId(type: string, name: string, filePath: string): string {
  const sanitized = filePath.replace(/[^a-zA-Z0-9]/g, '_');
  return `${type}_${name}_${sanitized}`;
}

/**
 * Parse TypeScript/JavaScript files
 */
function parseTypeScript(content: string, filePath: string): ParsedFile {
  const lines = content.split('\n');
  const nodes: (FunctionNode | ClassNode | InterfaceNode | VariableNode)[] = [];
  const imports: ImportInfo[] = [];
  const exports: ExportInfo[] = [];

  // Track braces for scope
  const openBraces: number[] = [];
  let inMultiLineComment = false;
  let inString: string | null = null;

  // Helper to get docstring before a line
  const getDocstring = (lineNum: number): string | undefined => {
    let docstring = '';
    let i = lineNum - 1;
    
    // Check for JSDoc comment
    while (i >= 0) {
      const line = lines[i].trim();
      if (line.endsWith('*/')) {
        // Find start of JSDoc
        let start = i;
        while (start >= 0 && !lines[start].includes('/**')) {
          start--;
        }
        if (start >= 0) {
          docstring = lines.slice(start, i + 1).join('\n');
        }
        break;
      } else if (line.startsWith('//')) {
        // Single line comment
        docstring = line.slice(2).trim();
        i--;
      } else if (line === '') {
        i--;
      } else {
        break;
      }
    }
    
    return docstring || undefined;
  };

  // Helper to extract function signature
  const extractSignature = (line: string, lineNum: number): string => {
    let sig = line;
    // Find the complete signature (might span multiple lines)
    let openParens = (line.match(/\(/g) || []).length;
    let closeParens = (line.match(/\)/g) || []).length;
    
    if (openParens > closeParens) {
      for (let i = lineNum; i < lines.length && openParens > closeParens; i++) {
        openParens += (lines[i].match(/\(/g) || []).length;
        closeParens += (lines[i].match(/\)/g) || []).length;
        if (i > lineNum) sig += ' ' + lines[i].trim();
      }
    }
    
    // Clean up
    sig = sig.replace(/\s+/g, ' ').trim();
    // Extract just the signature part
    const match = sig.match(/^(?:export\s+)?(?:async\s+)?(?:function\s+)?(?:\w+\s*)?\([^)]*\)(?:\s*:\s*[^{]+)?/);
    return match ? match[0].trim() : sig.split('{')[0].trim();
  };

  // Helper to find function calls within a block
  const findCalls = (startLine: number, endLine: number): string[] => {
    const calls: Set<string> = new Set();
    const callPattern = /(?:^|[^\w.])(\w+)\s*\(/g;
    
    for (let i = startLine - 1; i < endLine && i < lines.length; i++) {
      let match;
      const line = lines[i];
      while ((match = callPattern.exec(line)) !== null) {
        const funcName = match[1];
        // Filter out keywords and common patterns
        if (!['if', 'for', 'while', 'switch', 'catch', 'function', 'return', 'throw', 'new', 'typeof', 'instanceof', 'import', 'export', 'const', 'let', 'var', 'class', 'interface', 'type', 'async', 'await'].includes(funcName)) {
          calls.add(funcName);
        }
      }
    }
    
    return Array.from(calls);
  };

  // Helper to find matching closing brace
  const findClosingBrace = (startLine: number): number => {
    let depth = 0;
    let foundOpen = false;
    
    for (let i = startLine - 1; i < lines.length; i++) {
      for (const char of lines[i]) {
        if (char === '{') {
          depth++;
          foundOpen = true;
        } else if (char === '}') {
          depth--;
          if (foundOpen && depth === 0) {
            return i + 1;
          }
        }
      }
    }
    
    return lines.length;
  };

  // Parse imports
  const importPattern = /import\s+(?:(\w+)|\{([^}]+)\}|\*\s+as\s+(\w+))\s+from\s+['"]([^'"]+)['"]/g;
  let importMatch;
  while ((importMatch = importPattern.exec(content)) !== null) {
    const from = importMatch[4];
    if (importMatch[1]) {
      // Default import
      imports.push({ from, items: [importMatch[1]], is_default: true });
    } else if (importMatch[2]) {
      // Named imports
      const items = importMatch[2].split(',').map(s => s.trim());
      imports.push({ from, items });
    } else if (importMatch[3]) {
      // Namespace import
      imports.push({ from, items: [importMatch[3]], is_namespace: true });
    }
  }

  // Dynamic imports
  const dynamicImportPattern = /import\s*\(\s*['"]([^'"]+)['"]\s*\)/g;
  while ((importMatch = dynamicImportPattern.exec(content)) !== null) {
    imports.push({ from: importMatch[1], items: ['*'] });
  }

  // Parse exports
  const exportPattern = /export\s+(?:default\s+)?(?:(class|function|interface|type|const|let|var)\s+)?(\w+)/g;
  let exportMatch;
  while ((exportMatch = exportPattern.exec(content)) !== null) {
    const type = exportMatch[1] as string;
    const name = exportMatch[2];
    const nodeType: NodeType = type === 'class' ? 'Class' : 
                               type === 'function' ? 'Function' :
                               type === 'interface' ? 'Interface' :
                               type === 'type' ? 'Type' : 'Variable';
    exports.push({ name, type: nodeType });
  }

  // Parse classes
  const classPattern = /(?:export\s+)?(?:abstract\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?(?:\s+implements\s+([\w,\s]+))?/g;
  let classMatch;
  while ((classMatch = classPattern.exec(content)) !== null) {
    const className = classMatch[1];
    const extendsClass = classMatch[2];
    const implementsInterfaces = classMatch[3]?.split(',').map(s => s.trim()) || [];
    
    // Find line number
    let lineNum = 0;
    let pos = 0;
    for (let i = 0; i < lines.length; i++) {
      if (content.substring(pos, pos + lines[i].length).includes(classMatch[0])) {
        lineNum = i + 1;
        break;
      }
      pos += lines[i].length + 1;
    }
    
    const endLine = findClosingBrace(lineNum);
    const methods: string[] = [];
    const properties: string[] = [];
    
    // Extract methods and properties from class body
    const classBody = lines.slice(lineNum - 1, endLine).join('\n');
    const methodPattern = /(?:public|private|protected|static|async\s+)?(\w+)\s*\([^)]*\)/g;
    let methodMatch;
    while ((methodMatch = methodPattern.exec(classBody)) !== null) {
      if (methodMatch[1] !== 'constructor') {
        methods.push(methodMatch[1]);
      }
    }
    
    const propertyPattern = /(?:public|private|protected|static)\s+(\w+)\s*:/g;
    let propMatch;
    while ((propMatch = propertyPattern.exec(classBody)) !== null) {
      properties.push(propMatch[1]);
    }
    
    const node: ClassNode = {
      id: generateNodeId('class', className, filePath),
      type: 'class_declaration',
      name: className,
      start_line: lineNum,
      end_line: endLine,
      docstring: getDocstring(lineNum),
      modifiers: classMatch[0].includes('abstract') ? ['abstract'] : [],
      methods,
      properties,
      extends: extendsClass,
      implements: implementsInterfaces,
    };
    
    nodes.push(node);
    exports.push({ name: className, type: 'Class' });
  }

  // Parse interfaces and types
  const interfacePattern = /(?:export\s+)?(?:interface|type)\s+(\w+)(?:\s+extends\s+([\w,\s]+))?\s*[{=]/g;
  let interfaceMatch;
  while ((interfaceMatch = interfacePattern.exec(content)) !== null) {
    const interfaceName = interfaceMatch[1];
    
    let lineNum = 0;
    let pos = 0;
    for (let i = 0; i < lines.length; i++) {
      if (content.substring(pos, pos + lines[i].length).includes(interfaceMatch[0])) {
        lineNum = i + 1;
        break;
      }
      pos += lines[i].length + 1;
    }
    
    const endLine = findClosingBrace(lineNum);
    
    const node: InterfaceNode = {
      id: generateNodeId('interface', interfaceName, filePath),
      type: 'interface_declaration',
      name: interfaceName,
      start_line: lineNum,
      end_line: endLine,
      docstring: getDocstring(lineNum),
      methods: [],
      properties: [],
      extends: interfaceMatch[2]?.split(',').map(s => s.trim()),
    };
    
    nodes.push(node);
  }

  // Parse functions
  const functionPatterns = [
    // Named function
    /(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)(?:\s*:\s*([^{]+))?/g,
    // Arrow function with const
    /(?:export\s+)?(?:const|let|var)\s+(\w+)\s*(?::\s*[^=]+)?\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=])\s*=>/g,
    // Method in class/object
    /(?:public|private|protected|static|async\s+)*(\w+)\s*\(([^)]*)\)(?:\s*:\s*([^{]+))?\s*\{/g,
  ];

  for (const pattern of functionPatterns) {
    let funcMatch;
    pattern.lastIndex = 0; // Reset regex
    
    while ((funcMatch = pattern.exec(content)) !== null) {
      const funcName = funcMatch[1];
      
      // Skip if it's a keyword or already found
      if (['if', 'for', 'while', 'switch', 'catch', 'function', 'class', 'interface'].includes(funcName)) {
        continue;
      }
      
      // Skip if already processed
      if (nodes.some(n => n.name === funcName && 'parameters' in n)) {
        continue;
      }
      
      let lineNum = 0;
      let pos = 0;
      for (let i = 0; i < lines.length; i++) {
        if (content.substring(pos, pos + lines[i].length + 1).includes(funcMatch[0])) {
          lineNum = i + 1;
          break;
        }
        pos += lines[i].length + 1;
      }
      
      // Skip class methods (they're handled in class parsing)
      const isClassMethod = nodes.some(n => 
        n.type === 'class_declaration' && 
        lineNum >= n.start_line && 
        lineNum <= n.end_line
      );
      
      if (isClassMethod) continue;
      
      const endLine = findClosingBrace(lineNum);
      const signature = extractSignature(funcMatch[0], lineNum - 1);
      const calls = findCalls(lineNum, endLine);
      
      const node: FunctionNode = {
        id: generateNodeId('func', funcName, filePath),
        type: funcMatch[0].includes('=>') ? 'arrow_function' : 'function_declaration',
        name: funcName,
        start_line: lineNum,
        end_line: endLine,
        signature,
        docstring: getDocstring(lineNum),
        modifiers: [
          ...(funcMatch[0].includes('export') ? ['export'] : []),
          ...(funcMatch[0].includes('async') ? ['async'] : []),
        ],
        parameters: funcMatch[2] ? funcMatch[2].split(',').map(p => p.trim().split(':')[0].trim()).filter(Boolean) : [],
        return_type: funcMatch[3]?.trim(),
        calls,
        uses: [],
      };
      
      nodes.push(node);
    }
  }

  // Parse constants and variables
  const variablePattern = /(?:export\s+)?(?:const|let|var)\s+(\w+)\s*(?::\s*([^=;]+))?\s*=\s*([^;,\n]+)/g;
  let varMatch;
  while ((varMatch = variablePattern.exec(content)) !== null) {
    const varName = varMatch[1];
    
    // Skip if it's a function (arrow)
    if (varMatch[3].includes('=>') || varMatch[3].includes('function')) {
      continue;
    }
    
    let lineNum = 0;
    let pos = 0;
    for (let i = 0; i < lines.length; i++) {
      if (content.substring(pos, pos + lines[i].length).includes(varMatch[0])) {
        lineNum = i + 1;
        break;
      }
      pos += lines[i].length + 1;
    }
    
    const node: VariableNode = {
      id: generateNodeId('var', varName, filePath),
      type: 'const_declaration',
      name: varName,
      start_line: lineNum,
      end_line: lineNum,
      type_annotation: varMatch[2]?.trim(),
      initial_value: varMatch[3]?.trim().substring(0, 100),
    };
    
    nodes.push(node);
  }

  return {
    file_path: filePath,
    language: detectLanguage(filePath),
    nodes,
    imports,
    exports,
  };
}

/**
 * Parse Python files
 */
function parsePython(content: string, filePath: string): ParsedFile {
  const lines = content.split('\n');
  const nodes: (FunctionNode | ClassNode | InterfaceNode | VariableNode)[] = [];
  const imports: ImportInfo[] = [];
  const exports: ExportInfo[] = [];

  // Parse imports
  const importPattern = /(?:from\s+(\S+)\s+)?import\s+(.+)/g;
  let importMatch;
  while ((importMatch = importPattern.exec(content)) !== null) {
    const from = importMatch[1] || '';
    const items = importMatch[2].split(',').map(s => s.trim());
    imports.push({ from, items });
  }

  // Parse classes
  const classPattern = /class\s+(\w+)(?:\s*\(\s*([^)]*)\s*\))?:/g;
  let classMatch;
  while ((classMatch = classPattern.exec(content)) !== null) {
    const className = classMatch[1];
    const bases = classMatch[2]?.split(',').map(s => s.trim()).filter(Boolean) || [];
    
    let lineNum = 0;
    let pos = 0;
    for (let i = 0; i < lines.length; i++) {
      if (content.substring(pos, pos + lines[i].length).includes(classMatch[0])) {
        lineNum = i + 1;
        break;
      }
      pos += lines[i].length + 1;
    }
    
    // Find end of class (next class or function at same or lower indentation)
    const classIndent = lines[lineNum - 1].search(/\S/);
    let endLine = lines.length;
    for (let i = lineNum; i < lines.length; i++) {
      const line = lines[i];
      if (line.trim() && line.search(/\S/) <= classIndent && i > lineNum - 1) {
        endLine = i;
        break;
      }
    }
    
    const methods: string[] = [];
    const methodPattern = /def\s+(\w+)\s*\(/g;
    const classContent = lines.slice(lineNum, endLine).join('\n');
    let methodMatch;
    while ((methodMatch = methodPattern.exec(classContent)) !== null) {
      methods.push(methodMatch[1]);
    }
    
    // Get docstring
    let docstring: string | undefined;
    if (lineNum < lines.length) {
      const nextLine = lines[lineNum].trim();
      if (nextLine.startsWith('"""') || nextLine.startsWith("'''")) {
        const quote = nextLine.substring(0, 3);
        if (nextLine.endsWith(quote) && nextLine.length > 6) {
          docstring = nextLine.slice(3, -3);
        } else {
          // Multi-line docstring
          let end = lineNum;
          while (end < lines.length && !lines[end].includes(quote)) {
            end++;
          }
          docstring = lines.slice(lineNum, end + 1).join('\n');
        }
      }
    }
    
    const node: ClassNode = {
      id: generateNodeId('class', className, filePath),
      type: 'class_declaration',
      name: className,
      start_line: lineNum,
      end_line: endLine,
      docstring,
      modifiers: [],
      methods,
      properties: [],
      extends: bases[0],
      implements: bases.slice(1),
    };
    
    nodes.push(node);
  }

  // Parse functions
  const funcPattern = /def\s+(\w+)\s*\(([^)]*)\)(?:\s*->\s*([^:]+))?:/g;
  let funcMatch;
  while ((funcMatch = funcPattern.exec(content)) !== null) {
    const funcName = funcMatch[1];
    
    // Skip if it's a method inside a class
    let isInClass = false;
    for (const node of nodes) {
      if (node.type === 'class_declaration') {
        const classMatch = funcMatch[0];
        // Check if this function is inside the class
        let lineNum = 0;
        let pos = 0;
        for (let i = 0; i < lines.length; i++) {
          if (content.substring(pos, pos + lines[i].length).includes(classMatch)) {
            lineNum = i + 1;
            break;
          }
          pos += lines[i].length + 1;
        }
        if (lineNum >= node.start_line && lineNum <= node.end_line) {
          isInClass = true;
          break;
        }
      }
    }
    
    if (isInClass) continue;
    
    let lineNum = 0;
    let pos = 0;
    for (let i = 0; i < lines.length; i++) {
      if (content.substring(pos, pos + lines[i].length).includes(funcMatch[0])) {
        lineNum = i + 1;
        break;
      }
      pos += lines[i].length + 1;
    }
    
    // Find end of function
    const funcIndent = lines[lineNum - 1].search(/\S/);
    let endLine = lines.length;
    for (let i = lineNum; i < lines.length; i++) {
      const line = lines[i];
      if (line.trim() && line.search(/\S/) <= funcIndent && i > lineNum - 1) {
        endLine = i;
        break;
      }
    }
    
    const node: FunctionNode = {
      id: generateNodeId('func', funcName, filePath),
      type: 'function_declaration',
      name: funcName,
      start_line: lineNum,
      end_line: endLine,
      signature: `def ${funcName}(${funcMatch[2]})${funcMatch[3] ? ' -> ' + funcMatch[3] : ''}`,
      docstring: undefined,
      modifiers: [],
      parameters: funcMatch[2].split(',').map(p => p.trim().split('=')[0].trim()).filter(Boolean),
      return_type: funcMatch[3]?.trim(),
      calls: [],
      uses: [],
    };
    
    nodes.push(node);
  }

  return {
    file_path: filePath,
    language: 'python',
    nodes,
    imports,
    exports,
  };
}

/**
 * Main parser function
 */
export function parseFile(content: string, filePath: string): ParsedFile {
  const language = detectLanguage(filePath);
  
  switch (language) {
    case 'typescript':
    case 'javascript':
      return parseTypeScript(content, filePath);
    case 'python':
      return parsePython(content, filePath);
    default:
      return {
        file_path: filePath,
        language,
        nodes: [],
        imports: [],
        exports: [],
        parse_errors: [`Unsupported language: ${language}`],
      };
  }
}

/**
 * Parse multiple files
 */
export function parseFiles(files: Array<{ path: string; content: string }>): ParsedFile[] {
  return files.map(file => parseFile(file.content, file.path));
}

export { detectLanguage, generateNodeId };
