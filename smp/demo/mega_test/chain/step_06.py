"""Chain step 6 — calls step 7."""

from smp.demo.mega_test.chain.step_07 import step_07
from smp.demo.mega_test.utils.formatter import format_data_value


def step_06():
    """Calls the next step and formats data."""
    result = step_07()
    formatted = format_data_value(result, "step_6")
    return {"step": 6, "next": result, "formatted": formatted}
