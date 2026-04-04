"""Main module — uses both save() functions."""

from smp.demo.chaos2.services.user_service import save as save_user
from smp.demo.chaos2.services.product_service import save as save_product

def create_order(user: dict, product: dict):
    """Creates an order using both services."""
    save_user(user)
    save_product(product)
    return {"status": "order_created"}
