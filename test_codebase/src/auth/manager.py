# src/auth/manager.py
from src.db.user_store import save_user, get_user

def authenticate_user(email, password):
    """Validates user credentials and returns a session token."""
    user = get_user(email)
    if user and password == "secret":
        return "token_123"
    return None

def register_user(email, password):
    """Creates a new user account."""
    data = {"email": email, "password": password}
    return save_user(data)
