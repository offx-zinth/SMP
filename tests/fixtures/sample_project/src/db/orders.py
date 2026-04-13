"""Order model for database operations."""

from __future__ import annotations

from typing import Any


class OrderModel:
    """Order data access object."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def find_by_user(self, user_id: str) -> list[dict[str, Any]]:
        """Find all orders for a user."""
        result = self._db.execute(
            "SELECT * FROM orders WHERE user_id = $1",
            {"user_id": user_id},
        )
        return result

    def create(self, user_id: str, product: str, quantity: int) -> dict[str, Any]:
        """Create a new order."""
        id = self._db.execute(
            "INSERT INTO orders (user_id, product, quantity) VALUES ($1, $2, $3) RETURNING id",
            {"user_id": user_id, "product": product, "quantity": quantity},
        )
        return {"id": id, "user_id": user_id, "product": product, "quantity": quantity}
