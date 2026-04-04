"""Chain step 9 — calls step 10."""

from smp.demo.mega_test.chain.step_10 import step_10
from smp.demo.mega_test.utils.formatter import format_data_value

def step_09():
    """Calls the next step and formats data."""
    result = step_10()
    formatted = format_data_value(result, "step_9")
    return {"step": 9, "next": result, "formatted": formatted}
