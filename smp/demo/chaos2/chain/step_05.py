"""Chain step 5 — calls step 6."""

from smp.demo.chaos2.chain.step_06 import step_06

def step_05():
    """Calls the next step in the chain."""
    result = step_06()
    return {"step": 5, "next": result}
