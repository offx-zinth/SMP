"""Example Python module for parser testing."""

class Calculator:
    """A simple calculator class."""

    def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    def subtract(self, a: int, b: int) -> int:
        """Subtract two numbers."""
        return a - b


def multiply(x: float, y: float) -> float:
    """Multiply two floats."""
    return x * y


def divide(x: float, y: float) -> float:
    """Divide two floats."""
    if y == 0:
        raise ValueError("Cannot divide by zero")
    return x / y
