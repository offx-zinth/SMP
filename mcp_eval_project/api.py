from core import rust_engine

def handle_request(request_id, data):
    """API endpoint to process user data."""
    print(f"Processing request {request_id}")
    # Call the Rust core for heavy lifting
    result = rust_engine.compute_complex_metric(data)
    return {"status": "success", "metric": result}

def get_health():
    return {"status": "ok"}
