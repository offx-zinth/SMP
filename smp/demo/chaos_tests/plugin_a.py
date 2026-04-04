"""Plugin A — uses the shared contract."""

from smp.demo.chaos_tests.contract import validate_payload

def process_order(data: dict):
    """E-commerce order processor."""
    if not validate_payload(data):
        raise ValueError("Invalid order")
    return {"status": "order_placed"}
