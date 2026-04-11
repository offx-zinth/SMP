"""Chain step 9 — calls step 10."""

from smp.demo.chaos2.chain.step_10 import step_10


def step_09():
    """Calls the next step in the chain."""
    result = step_10()
    return {"step": 9, "next": result}
