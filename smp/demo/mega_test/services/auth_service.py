"""Services: Auth — Auth Layer 2 (business service)."""

from smp.demo.mega_test.core.user_domain import get_user_model


def authenticate_user(email: str, password: str):
    """Core business logic for logging a user in."""
    user = get_user_model(email)
    if user:
        return f"jwt_token_for_{email}"
    raise PermissionError("Invalid credentials")
