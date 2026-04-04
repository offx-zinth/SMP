"""Utils: Formatter — Analytics spiderweb core."""

def format_data_value(value, value_type: str = "generic"):
    """Format a data value for display. Called by many analytics functions."""
    if isinstance(value, (int, float)):
        return f"{value_type}:{value:.2f}"
    return f"{value_type}:{value}"
