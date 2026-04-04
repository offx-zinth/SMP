"""Beta module — imports from alpha (circular)."""

from smp.demo.chaos_tests.alpha import alpha_func

def beta_func():
    """Calls alpha_func which calls beta_func (circular)."""
    result = alpha_func()
    return {"beta": True, "alpha_result": result}
