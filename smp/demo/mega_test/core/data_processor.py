"""Core: Data Processor — Analytics spiderweb hub."""

from smp.demo.mega_test.utils.formatter import format_data_value
from smp.demo.mega_test.utils.logger import log_event

def analyze_temperature(raw_temp: float):
    """Analytics function that uses formatter and logger."""
    formatted = format_data_value(raw_temp, "temperature")
    log_event("temp_analyzed", value=formatted)
    return formatted


def analyze_voltage(raw_voltage: float):
    """Another analytics function."""
    formatted = format_data_value(raw_voltage, "voltage")
    log_event("voltage_analyzed", value=formatted)
    return formatted


def calculate_balance(account_id: str):
    """Analytics that chains through formatter."""
    raw = {"account": account_id, "balance": 1000}
    formatted = format_data_value(raw, "currency")
    return formatted
