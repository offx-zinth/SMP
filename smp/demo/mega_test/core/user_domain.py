"""Core: User Domain — Auth Layer 3 (domain models)."""

from smp.demo.mega_test.infra.database import low_level_query

def get_user_model(email: str):
    """Transforms raw DB record into a business domain model."""
    raw = low_level_query(f"SELECT * FROM users WHERE email='{email}'")
    return {"email": email, "raw": raw}
