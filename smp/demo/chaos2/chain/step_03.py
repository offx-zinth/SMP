"""Chain step 3 — calls step 4."""

from smp.demo.chaos2.chain.step_04 import step_04

def step_03():
    """Calls the next step in the chain."""
    result = step_04()
    return {"step": 3, "next": result}
