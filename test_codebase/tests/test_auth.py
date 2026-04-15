# tests/test_auth.py
from src.auth.manager import authenticate_user

def test_auth_success():
    assert authenticate_user("test@example.com", "secret") == "token_123"

def test_auth_fail():
    assert authenticate_user("test@example.com", "wrong") is None
