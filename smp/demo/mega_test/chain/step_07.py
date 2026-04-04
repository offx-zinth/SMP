"""Chain step 7 — calls step 8."""

from smp.demo.mega_test.chain.step_08 import step_08
from smp.demo.mega_test.utils.formatter import format_data_value

def step_07():
    """Calls the next step and formats data."""
    result = step_08()
    formatted = format_data_value(result, "step_7")
    return {"step": 7, "next": result, "formatted": formatted}
