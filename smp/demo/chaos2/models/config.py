from smp.demo.chaos2.settings import MAX_RETRIES

def retry_policy():
    """Return retry configuration."""
    return {"max": MAX_RETRIES}
