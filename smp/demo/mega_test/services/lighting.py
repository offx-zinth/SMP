"""Services: Lighting — Smart Home Branch A."""

from smp.demo.mega_test.infra.hardware import raw_gpio_write
from smp.demo.mega_test.utils.logger import log_event

def set_bulb_state(bulb_id: str, state: bool, brightness: int):
    """Logic to handle individual smart bulbs."""
    raw_gpio_write(10, state)
    log_event("bulb_changed", bulb=bulb_id, state=state, brightness=brightness)
    return {"bulb": bulb_id, "state": state}
