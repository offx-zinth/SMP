"""Infra: Database — Auth Layer 4 (the deepest layer)."""

def low_level_query(sql: str):
    """Executes a raw SQL query against the database."""
    return {"status": "success", "data": [], "sql": sql}
