"""Chain step 2 — calls step 3."""

from smp.demo.mega_test.chain.step_03 import step_03
from smp.demo.mega_test.utils.formatter import format_data_value

def step_02():
    """Calls the next step and formats data."""
    result = step_03()
    formatted = format_data_value(result, "step_2")
    return {"step": 2, "next": result, "formatted": formatted}
