"""Features: Plugin System — Interface Contract test."""


def validate_payload(data: dict) -> bool:
    """Shared validation contract used by all plugins."""
    return "id" in data and "type" in data
