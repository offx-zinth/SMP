"""Chain step 8 — calls step 9."""

from smp.demo.chaos2.chain.step_09 import step_09


def step_08():
    """Calls the next step in the chain."""
    result = step_09()
    return {"step": 8, "next": result}
