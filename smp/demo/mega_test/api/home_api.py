"""API: Home — Smart Home top-level endpoints."""

from smp.demo.mega_test.core.security import trigger_alarm
from smp.demo.mega_test.services.lighting import set_bulb_state


def api_toggle_lights(request: dict):
    """Top-level API for lighting control."""
    status = request.get("status") == "on"
    brightness = 100 if status else 0
    return set_bulb_state("living_room_1", status, brightness)


def api_security_emergency():
    """Top-level API for security."""
    trigger_alarm(True)
    return {"status": "ALARM_TRIGGERED"}
