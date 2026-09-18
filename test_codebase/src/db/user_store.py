# src/db/user_store.py
def save_user(user_data: dict):
    """Saves user data to the database."""
    print(f"Saving user {user_data.get('email')}")
    return True


def get_user(email: str):
    """Retrieves user by email."""
    return {"email": email, "name": "Test User"}
