from smp.demo.chaos2.settings import TIMEOUT, VERSION

def health_check():
    """Service health endpoint."""
    return {"version": VERSION, "timeout": TIMEOUT}
