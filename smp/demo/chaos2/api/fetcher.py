from smp.demo.chaos2.settings import TIMEOUT


def fetch_data():
    """API fetcher using shared timeout."""
    return {"timeout": TIMEOUT}
