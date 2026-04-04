"""Chain step 6 — calls step 7."""

from smp.demo.chaos2.chain.step_07 import step_07

def step_06():
    """Calls the next step in the chain."""
    result = step_07()
    return {"step": 6, "next": result}
