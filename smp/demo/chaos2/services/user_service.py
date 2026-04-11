"""User service — has a save() function."""


def save(user_data: dict):
    """Save a user record."""
    return {"saved": "user", "data": user_data}
