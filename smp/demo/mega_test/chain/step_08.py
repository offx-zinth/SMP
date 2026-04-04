"""Chain step 8 — calls step 9."""

from smp.demo.mega_test.chain.step_09 import step_09
from smp.demo.mega_test.utils.formatter import format_data_value

def step_08():
    """Calls the next step and formats data."""
    result = step_09()
    formatted = format_data_value(result, "step_8")
    return {"step": 8, "next": result, "formatted": formatted}
