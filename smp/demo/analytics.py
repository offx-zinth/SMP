"""
A system with horizontal dependencies to test SMP's cross-domain awareness.
"""

# ==========================================
# THE UTILITY (The "Spider" in the web)
# ==========================================
def format_data_value(value: float, unit: str, precision: int) -> str:
    """Formats a raw number into a readable string with units."""
    # TEST: If we change this to return a DICT instead of a STR...
    # it should break three different domains.
    return f"{value:.{precision}f} {unit}"


# ==========================================
# DOMAIN A: WEATHER STATION
# ==========================================
def get_temperature_report(celsius: float) -> str:
    """Calculates and formats the local weather report."""
    fahrenheit = (celsius * 9/5) + 32
    return format_data_value(fahrenheit, "°F", 2)


# ==========================================
# DOMAIN B: FINANCE MODULE
# ==========================================
def calculate_account_balance(transactions: list) -> str:
    """Sums up transactions and returns a formatted currency string."""
    total = sum(transactions)
    return format_data_value(total, "USD", 2)


# ==========================================
# DOMAIN C: HARDWARE SENSORS
# ==========================================
def check_cpu_voltage(voltage: float) -> str:
    """Checks the health of the hardware voltage."""
    if voltage > 1.2:
        status = "CRITICAL"
    else:
        status = "STABLE"
    
    formatted_v = format_data_value(voltage, "V", 2)
    return f"Status: {status} | Power: {formatted_v}"


# ==========================================
# SEMANTIC SEARCH TRAP (No names match)
# ==========================================
def hide_sensitive_logs() -> None:
    """This function is responsible for scrubbing private 
    user information like emails and tokens from the system output."""
    # We will test if SMP can find this via 'locate' query
    pass