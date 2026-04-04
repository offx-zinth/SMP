"""File B — imports calculate aliased as run_math."""

from smp.demo.chaos2.file_a import calculate as run_math

def process():
    """Uses the aliased import."""
    result = run_math(2, 3)
    return {"result": result}
