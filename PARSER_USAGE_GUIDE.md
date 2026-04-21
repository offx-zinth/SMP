# Multi-Language Parser Quick Start Guide

## Using the Parser Registry

### Parse a Single File

```python
from smp.parser.registry import ParserRegistry

registry = ParserRegistry()

# Parse a Python file
doc = registry.parse_file("src/main.py")
print(f"Nodes: {len(doc.nodes)}")
print(f"Edges: {len(doc.edges)}")
print(f"Errors: {len(doc.errors)}")
```

### Parse Code Content

```python
from smp.parser.registry import ParserRegistry
from smp.core.models import Language

registry = ParserRegistry()

# Parse Python code
python_code = """
def hello(name: str) -> str:
    return f'Hello {name}'
"""
doc = registry.parse_file("example.py", content=python_code)

# Or specify language explicitly
parser = registry.get(Language.PYTHON)
doc = parser.parse(python_code, "example.py")
```

### Supported Languages

```python
from smp.core.models import Language

# All 14 languages available
languages = [
    Language.PYTHON,      # .py
    Language.JAVASCRIPT,  # .js
    Language.TYPESCRIPT,  # .ts, .tsx
    Language.JAVA,        # .java
    Language.C,           # .c, .h
    Language.CPP,         # .cpp, .cc, .h
    Language.CSHARP,      # .cs
    Language.GO,          # .go
    Language.RUST,        # .rs
    Language.PHP,         # .php
    Language.SWIFT,       # .swift
    Language.KOTLIN,      # .kt
    Language.RUBY,        # .rb
    Language.MATLAB,      # .m
]
```

### Automatic Language Detection

```python
registry = ParserRegistry()

# Language detected from file extension
doc = registry.parse_file("src/calculator.java")     # Java
doc = registry.parse_file("lib/utils.go")            # Go
doc = registry.parse_file("src/main.rs")             # Rust
doc = registry.parse_file("src/Calculator.cs")       # C#
```

## Working with Parse Results

### Accessing Nodes

```python
doc = registry.parse_file("example.py")

for node in doc.nodes:
    print(f"{node.type.value}: {node.structural.name}")
    print(f"  File: {node.file_path}")
    print(f"  Lines: {node.structural.start_line}-{node.structural.end_line}")
    if node.semantic and node.semantic.docstring:
        print(f"  Doc: {node.semantic.docstring}")
```

### Accessing Edges

```python
doc = registry.parse_file("example.py")

for edge in doc.edges:
    print(f"{edge.source_id} --[{edge.type.value}]--> {edge.target_id}")
```

### Error Handling

```python
doc = registry.parse_file("buggy.py")

if doc.errors:
    print(f"Parse errors ({len(doc.errors)}):")
    for error in doc.errors:
        print(f"  {error}")
```

## Batch Processing Multiple Languages

```python
from pathlib import Path
from smp.parser.registry import ParserRegistry

registry = ParserRegistry()
results = {}

# Parse all Python and Java files in a directory
for file_path in Path("src").rglob("*.py"):
    doc = registry.parse_file(str(file_path))
    results[file_path.name] = {
        "nodes": len(doc.nodes),
        "edges": len(doc.edges),
        "errors": len(doc.errors),
    }

for file_path in Path("src").rglob("*.java"):
    doc = registry.parse_file(str(file_path))
    results[file_path.name] = {
        "nodes": len(doc.nodes),
        "edges": len(doc.edges),
        "errors": len(doc.errors),
    }

# Print summary
for filename, stats in results.items():
    print(f"{filename}: {stats}")
```

## Integration with SMP Pipeline

### Ingest Parsed Documents

```python
from smp.parser.registry import ParserRegistry
from smp.engine.graph_builder import DefaultGraphBuilder
from smp.store.graph.neo4j_store import Neo4jGraphStore
import asyncio

async def ingest_codebase():
    registry = ParserRegistry()
    store = Neo4jGraphStore()
    builder = DefaultGraphBuilder(store)
    
    await store.connect()
    
    # Parse and ingest files
    doc = registry.parse_file("src/main.java")
    await builder.ingest_document(doc)
    
    doc = registry.parse_file("src/utils.go")
    await builder.ingest_document(doc)
    
    await store.close()

asyncio.run(ingest_codebase())
```

## Node Types Extracted

All parsers extract these node types:
- **FILE** - Source file
- **CLASS** - Class/struct/trait definitions
- **FUNCTION** - Top-level functions
- **METHOD** - Methods in classes
- **INTERFACE** - Interfaces/protocols
- **ENUM** - Enum definitions
- **CONSTANT** - Constants and module-level constants

## Edge Types Created

All parsers create these relationships:
- **DEFINES** - File defines a class/function
- **CONTAINS** - Class contains a method
- **IMPORTS** - File imports another module
- **CALLS** - Function calls another function
- **USES** - Uses a type or interface
- **EXTENDS** - Class extends/inherits from another
- **IMPLEMENTS** - Class implements interface

## Language-Specific Notes

### Python
- Supports decorators on functions/classes
- Extracts type annotations
- Handles async/await syntax

### Java
- Extracts generics
- Handles nested classes
- Supports annotations

### C/C++
- C parser handles .c files
- C++ parser handles .cpp, .cc files
- Supports macros as nodes

### Go
- Extracts interfaces
- Handles methods on types
- Supports goroutines

### Rust
- Extracts traits and implementations
- Handles macros
- Supports generic types

### TypeScript/JavaScript
- Distinguishes between .ts and .tsx
- Handles arrow functions
- Supports class syntax

## Example: Analyzing a Multi-Language Project

```python
from pathlib import Path
from smp.parser.registry import ParserRegistry
from collections import defaultdict

registry = ParserRegistry()
stats = defaultdict(lambda: {"functions": 0, "classes": 0, "files": 0})

# Analyze all supported file types
patterns = [
    "**/*.py",   # Python
    "**/*.java", # Java
    "**/*.go",   # Go
    "**/*.rs",   # Rust
    "**/*.ts",   # TypeScript
    "**/*.cpp",  # C++
    "**/*.cs",   # C#
    "**/*.swift",# Swift
    "**/*.rb",   # Ruby
    "**/*.php",  # PHP
]

for pattern in patterns:
    for file_path in Path("src").glob(pattern):
        try:
            doc = registry.parse_file(str(file_path))
            ext = file_path.suffix
            
            stats[ext]["files"] += 1
            stats[ext]["functions"] += sum(1 for n in doc.nodes if "function" in n.type.value.lower())
            stats[ext]["classes"] += sum(1 for n in doc.nodes if n.type.value == "class")
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")

# Print summary
print("\nCodebase Statistics by Language:")
print("-" * 50)
for ext, data in sorted(stats.items()):
    print(f"{ext:8} Files: {data['files']:3}  Classes: {data['classes']:3}  Functions: {data['functions']:3}")
```

## Performance Tips

1. **Reuse the Registry** - Create one instance per application
2. **Lazy Loading** - Parsers are loaded on first use
3. **Caching** - Parsers are cached after first instantiation
4. **Batch Processing** - Process multiple files in loops for efficiency

## Troubleshooting

### "No module named 'tree_sitter_XXX'"
Install the parser dependencies:
```bash
pip install -e ".[dev]"
```

### "Unknown language"
Check the file extension is correct or specify language explicitly:
```python
from smp.core.models import Language
parser = registry.get(Language.JAVA)
doc = parser.parse(code, "MyFile.java")
```

### "Parse errors"
Check that the syntax is valid for the target language:
```python
doc = registry.parse_file("file.py")
for error in doc.errors:
    print(f"Error: {error}")
```

## API Reference

### ParserRegistry

```python
class ParserRegistry:
    def get(self, language: Language) -> TreeSitterParser
    def parse_file(self, file_path: str) -> ParsedDocument
```

### ParsedDocument

```python
class ParsedDocument:
    file_path: str
    language: Language
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    errors: list[str]
```

### GraphNode

```python
class GraphNode:
    id: str
    type: NodeType  # FILE, CLASS, FUNCTION, METHOD, etc.
    file_path: str
    structural: StructuralProperties
    semantic: SemanticProperties
```

### GraphEdge

```python
class GraphEdge:
    source_id: str
    target_id: str
    type: EdgeType  # DEFINES, CALLS, IMPORTS, etc.
```
