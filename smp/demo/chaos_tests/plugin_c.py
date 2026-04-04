"""Plugin C — uses the shared contract."""

from smp.demo.chaos_tests.contract import validate_payload

def process_shipment(data: dict):
    """Shipping logistics processor."""
    if not validate_payload(data):
        raise ValueError("Invalid shipment")
    return {"status": "shipped"}
