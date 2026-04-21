from __future__ import annotations
import tree_sitter as ts
import tree_sitter_rust as tsr
from smp.parser.rust_parser import RustParser

def test():
    parser_engine = RustParser()
    code = b"""
pub fn compute_complex_metric(data: f64) -> f64 {
    let scaled = data * 42.0;
    return apply_offset(scaled);
}

fn apply_offset(val: f64) -> f64 {
    return val + 1.5;
}
"""
    # Use the language object from the parser
    lang = parser_engine._language("test.rs")
    parser = ts.Parser()
    parser.language = lang
    tree = parser.parse(code)
    
    nodes, edges, errors = parser_engine._extract(tree.root_node, code, "test.rs")
    print(f"Nodes found: {len(nodes)}")
    for n in nodes:
        print(f"Node: {n.type}, Name: {n.structural.name}")

if __name__ == "__main__":
    test()
