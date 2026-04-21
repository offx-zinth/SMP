from smp.parser.python_parser import PythonParser

code = """
pub fn compute_complex_metric(data: f64) -> f64 {
    let scaled = data * 42.0;
    return apply_offset(scaled);
}

fn apply_offset(val: f64) -> f64 {
    return val + 1.5;
}
"""

parser = PythonParser()
result = parser.parse(code, "test.rs")
print(f"Python parser on Rust code: {len(result.nodes)} nodes, {len(result.errors)} errors")
for err in result.errors:
    print(f"  Error: {err}")
