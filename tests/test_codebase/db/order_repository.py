from __future__ import annotations

from .base_repository import BaseRepository


class Order:
    """Represents an order entity."""

    def __init__(self, order_id: str, user_id: str, amount: float):
        self.order_id = order_id
        self.user_id = user_id
        self.amount = amount


class OrderRepository(BaseRepository[Order]):
    """
    Repository implementation for managing Order entities.
    """

    async def get_by_id(self, entity_id: str) -> Order | None:
        """
        Fetches an order by its order_id.

        Args:
            entity_id: The order ID.

        Returns:
            An Order instance if found.
        """
        return Order(entity_id, "user_123", 99.99)

    async def save(self, entity: Order) -> None:
        """
        Persists order data.

        Args:
            entity: The Order object to save.
        """
        pass

    async def delete(self, entity_id: str) -> bool:
        """
        Removes an order from the store.

        Args:
            entity_id: The order ID.

        Returns:
            True if successful.
        """
        return True

    async def get_orders_by_user(self, user_id: str) -> list[Order]:
        """
        Retrieves all orders belonging to a specific user.

        Args:
            user_id: The user ID.

        Returns:
            A list of orders.
        """
        return [Order("o1", user_id, 10.0), Order("o2", user_id, 20.0)]
