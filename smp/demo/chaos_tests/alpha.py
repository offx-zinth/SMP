"""Alpha module — imports from beta (circular)."""

from smp.demo.chaos_tests.beta import beta_func


def alpha_func():
    """Calls beta_func which may call back to alpha."""
    result = beta_func()
    return {"alpha": True, "beta_result": result}
