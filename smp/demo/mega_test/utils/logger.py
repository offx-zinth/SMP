"""Utils: Logger — shared logging utility."""

def log_event(event_name: str, **kwargs):
    """Log a structured event."""
    return {"event": event_name, "data": kwargs}
