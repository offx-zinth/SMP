"""Chain step 1 — calls step 2."""

from smp.demo.chaos2.chain.step_02 import step_02

def step_01():
    """Calls the next step in the chain."""
    result = step_02()
    return {"step": 1, "next": result}
