"""Infra: Hardware — Smart Home shared utils."""

def raw_gpio_write(pin: int, signal: bool):
    """Direct hardware communication layer."""
    return {"pin": pin, "signal": signal}
