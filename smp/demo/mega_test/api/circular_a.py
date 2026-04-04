"""API: Circular A — imports from utils/circular_b (circular dependency)."""

from smp.demo.mega_test.utils.circular_b import beta_func

def alpha_func():
    """Calls beta which calls back to alpha."""
    result = beta_func()
    return {"alpha": True, "beta": result}
