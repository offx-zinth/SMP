"""Features: Billing — Polymorphism test (has save())."""

from smp.demo.mega_test.infra.database import low_level_query


def save(billing_data: dict):
    """Save a billing record (same name as inventory.save)."""
    result = low_level_query(f"INSERT INTO billing VALUES ({billing_data})")
    return {"saved": "billing", "result": result}
