"""Chain step 4 — calls step 5."""

from smp.demo.mega_test.chain.step_05 import step_05
from smp.demo.mega_test.utils.formatter import format_data_value

def step_04():
    """Calls the next step and formats data."""
    result = step_05()
    formatted = format_data_value(result, "step_4")
    return {"step": 4, "next": result, "formatted": formatted}
