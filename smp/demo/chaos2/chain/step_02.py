"""Chain step 2 — calls step 3."""

from smp.demo.chaos2.chain.step_03 import step_03

def step_02():
    """Calls the next step in the chain."""
    result = step_03()
    return {"step": 2, "next": result}
