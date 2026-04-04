"""Chain step 3 — calls step 4."""

from smp.demo.mega_test.chain.step_04 import step_04
from smp.demo.mega_test.utils.formatter import format_data_value

def step_03():
    """Calls the next step and formats data."""
    result = step_04()
    formatted = format_data_value(result, "step_3")
    return {"step": 3, "next": result, "formatted": formatted}
