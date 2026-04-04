"""Utils: Circular B — imports from api/circular_a (circular dependency)."""

from smp.demo.mega_test.api.circular_a import alpha_func

def beta_func():
    """Calls alpha which calls back to beta."""
    result = alpha_func()
    return {"beta": True, "alpha": result}
