"""File C — also imports the alias."""

from smp.demo.chaos2.file_a import calculate as compute


def batch_process():
    """Uses another alias of the same function."""
    results = [compute(i, i) for i in range(5)]
    return results
