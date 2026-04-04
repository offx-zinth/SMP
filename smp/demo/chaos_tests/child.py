"""Child layer — depends on father, transitively on grandfather."""

from smp.demo.chaos_tests.father import mid_func

def top_func():
    """Calls mid_func which calls base_func (grandfather)."""
    data = mid_func()
    data["layer"] = "child"
    return data
