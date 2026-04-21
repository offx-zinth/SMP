import msgspec
from smp.core.models import UpdateParams, Language

# Test 1: Dict with language=None
d1 = {"file_path": "test.rs", "content": "code", "change_type": "modified", "language": None}
p1 = msgspec.convert(d1, UpdateParams)
print(f"Test 1 (language=None): {p1.language}")

# Test 2: Dict without language key
d2 = {"file_path": "test.rs", "content": "code", "change_type": "modified"}
p2 = msgspec.convert(d2, UpdateParams)
print(f"Test 2 (no language key): {p2.language}")

# Test 3: Dict with language="rust"
d3 = {"file_path": "test.rs", "content": "code", "change_type": "modified", "language": "rust"}
p3 = msgspec.convert(d3, UpdateParams)
print(f"Test 3 (language='rust'): {p3.language}")
