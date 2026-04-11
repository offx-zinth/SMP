"""Caller of used_function (NOT orphan_complex_logic)."""

from smp.demo.chaos2.dead_code import used_function


def entry_point():
    """Only uses used_function, not the orphan."""
    return used_function()
