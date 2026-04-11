"""Core: Security — Smart Home Branch B (security system)."""

from smp.demo.mega_test.infra.hardware import raw_gpio_write


def trigger_alarm(active: bool):
    """Logic to trigger the alarm siren."""
    raw_gpio_write(99, active)
    return {"alarm": active}
