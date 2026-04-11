"""
Smart Home OS: Testing branch isolation and precision impact analysis.
"""


# ==========================================
# SHARED UTILS (Bottom Layer)
# ==========================================
def raw_gpio_write(pin: int, signal: bool):
    """Direct hardware communication layer."""
    print(f"Writing {signal} to pin {pin}")


def system_logger(message: str):
    """Generic system-wide logger."""
    print(f"[LOG]: {message}")


# ==========================================
# BRANCH A: LIGHTING SYSTEM
# ==========================================
def set_bulb_state(bulb_id: str, state: bool, brightness: int):
    """Logic to handle individual smart bulbs."""
    system_logger(f"Bulb {bulb_id} setting to {state} with brightness {brightness}")
    raw_gpio_write(10, state)  # Assuming raw_gpio_write doesn't directly handle brightness in this abstraction


def api_toggle_lights(request: dict):
    """Top-level API for lighting."""
    status = request.get("status") == "on"
    # Default brightness: 100 if on, 0 if off
    brightness = 100 if status else 0
    set_bulb_state("living_room_1", status, brightness)
    return {"result": "success"}


# ==========================================
# BRANCH B: SECURITY SYSTEM
# ==========================================
def trigger_alarm_siren(active: bool):
    """Logic to scream if there's an intruder."""
    system_logger(f"Siren active: {active}")
    raw_gpio_write(99, active)


def api_security_emergency():
    """Top-level API for security."""
    trigger_alarm_siren(True)
    return {"status": "ALARM_TRIGGERED"}


# ==========================================
# ISOLATED BRANCH: ANALYTICS (Should NEVER be affected)
# ==========================================
def calculate_uptime(boot_time: float) -> float:
    """Pure math logic. No hardware calls."""
    import time

    return time.time() - boot_time


def get_about_info():
    """Simple metadata return. Isolated from everything."""
    return {"version": "2.0.1", "author": "Senthil"}
