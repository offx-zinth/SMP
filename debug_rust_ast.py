from __future__ import annotations
import tree_sitter as ts
import tree_sitter_rust as tsr

code = b"pub fn compute_complex_metric(data: f64) -> f64 { return 1.0; }"
parser = ts.Parser()
parser.language = ts.Language(tsr.language())
tree = parser.parse(code)
root = tree.root_node
func = root.children[0]
print(f"Node type: {func.type}")
for i, child in enumerate(func.children):
    print(f"  Child {i}: {child.type} - {child.text.decode('utf-8')}")
