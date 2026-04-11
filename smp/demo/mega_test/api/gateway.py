"""API: Gateway — Auth Layer 1 (top-level handler)."""

from smp.demo.mega_test.services.auth_service import authenticate_user


def handle_login_request(request: dict):
    """API handler for POST /login."""
    email = request.get("email", "")
    password = request.get("password", "")
    try:
        token = authenticate_user(email, password)
        return {"status": 200, "token": token}
    except Exception as e:
        return {"status": 401, "error": str(e)}
