"""Chain step 5 — calls step 6."""

from smp.demo.mega_test.chain.step_06 import step_06
from smp.demo.mega_test.utils.formatter import format_data_value

def step_05():
    """Calls the next step and formats data."""
    result = step_06()
    formatted = format_data_value(result, "step_5")
    return {"step": 5, "next": result, "formatted": formatted}
