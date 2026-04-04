def low_level_query(db_name: str, sql: str):
    """Executes a raw SQL query against the database."""
    print(f"Executing against DB '{db_name}': {sql}")
    return {"status": "success", "data": []}