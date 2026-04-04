"""Chain step 4 — calls step 5."""

from smp.demo.chaos2.chain.step_05 import step_05

def step_04():
    """Calls the next step in the chain."""
    result = step_05()
    return {"step": 4, "next": result}
