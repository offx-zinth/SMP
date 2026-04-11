"""Chain step 10 — the deepest leaf."""

from smp.demo.mega_test.utils.formatter import format_data_value


def step_10():
    """Final function in the chain."""
    formatted = format_data_value({"step": 10, "leaf": True}, "step_10")
    return {"step": 10, "formatted": formatted}
