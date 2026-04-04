from smp.demo.core_db import low_level_query

def get_user_by_id(user_id: int):
    """Fetches a user profile using the low level query engine."""
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return low_level_query(query) # <--- CROSS-FILE CALL