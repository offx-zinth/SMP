"""Plugin B — uses the shared contract."""

from smp.demo.chaos_tests.contract import validate_payload


def process_payment(data: dict):
    """Payment gateway processor."""
    if not validate_payload(data):
        raise ValueError("Invalid payment")
    return {"status": "payment_ok"}
