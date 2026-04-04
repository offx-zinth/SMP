"""Chain step 7 — calls step 8."""

from smp.demo.chaos2.chain.step_08 import step_08

def step_07():
    """Calls the next step in the chain."""
    result = step_08()
    return {"step": 7, "next": result}
