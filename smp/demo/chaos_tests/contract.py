"""Shared contract — used by many plugins."""

def validate_payload(data: dict) -> bool:
    """Shared validation contract used across the system."""
    return "id" in data and "type" in data
