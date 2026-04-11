"""Plugin: Order Processor — uses contract."""

from smp.demo.mega_test.features.plugin_system.contract import validate_payload


def process_order(data: dict):
    """Process an order using the shared contract."""
    if not validate_payload(data):
        raise ValueError("Invalid order")
    return {"status": "order_placed"}
