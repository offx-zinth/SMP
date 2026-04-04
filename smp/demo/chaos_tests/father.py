"""Father layer — depends on grandfather."""

from smp.demo.chaos_tests.grandfather import base_func

def mid_func():
    """Calls base_func from the layer below."""
    data = base_func()
    data["layer"] = "father"
    return data
