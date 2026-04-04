"""Plugin: Notification — uses contract."""

from smp.demo.mega_test.features.plugin_system.contract import validate_payload

def send_notification(data: dict):
    """Send notification using the shared contract."""
    if not validate_payload(data):
        raise ValueError("Invalid notification data")
    return {"status": "notification_sent"}
