"""Product service — also has a save() function."""

def save(product_data: dict):
    """Save a product record."""
    return {"saved": "product", "data": product_data}
