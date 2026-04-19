from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Sequence

T = TypeVar("T")


class BaseRepository(ABC, Generic[T]):
    """
    Abstract base class for all repositories.
    Defines standard CRUD operations for entities.
    """

    def __init__(self, connection_string: str):
        """
        Initializes the repository with a database connection string.

        Args:
            connection_string: The URI for the database connection.
        """
        self._connection_string = connection_string

    @abstractmethod
    async def get_by_id(self, entity_id: str) -> T | None:
        """
        Retrieves an entity by its unique identifier.

        Args:
            entity_id: The ID of the entity to retrieve.

        Returns:
            The entity if found, otherwise None.
        """
        pass

    @abstractmethod
    async def save(self, entity: T) -> None:
        """
        Saves or updates an entity in the database.

        Args:
            entity: The entity to persist.
        """
        pass

    @abstractmethod
    async def delete(self, entity_id: str) -> bool:
        """
        Deletes an entity by its ID.

        Args:
            entity_id: The ID of the entity to delete.

        Returns:
            True if the entity was deleted, False otherwise.
        """
        pass
