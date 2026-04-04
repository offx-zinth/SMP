from smp.demo.chaos2.settings import TIMEOUT

def run_job():
    """Background worker using shared timeout."""
    return {"wait": TIMEOUT}
