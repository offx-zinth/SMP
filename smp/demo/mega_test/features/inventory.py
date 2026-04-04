"""Features: Inventory — Polymorphism test (has save())."""

from smp.demo.mega_test.infra.database import low_level_query

def save(inventory_data: dict):
    """Save an inventory record (same name as billing.save)."""
    result = low_level_query(f"INSERT INTO inventory VALUES ({inventory_data})")
    return {"saved": "inventory", "result": result}
