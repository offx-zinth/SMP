from __future__ import annotations

from .base_repository import BaseRepository


class User:
    """Represents a user entity."""

    def __init__(self, user_id: str, username: str, email: str):
        self.user_id = user_id
        self.username = username
        self.email = email


class UserRepository(BaseRepository[User]):
    """
    Repository implementation for managing User entities.
    Inherits from BaseRepository.
    """

    async def get_by_id(self, entity_id: str) -> User | None:
        """
        Fetches a user by their user_id.

        Args:
            entity_id: The user ID.

        Returns:
            A User instance if found.
        """
        # Mock implementation
        return User(entity_id, "test_user", "test@example.com")

    async def save(self, entity: User) -> None:
        """
        Persists user data.

        Args:
            entity: The User object to save.
        """
        pass

    async def delete(self, entity_id: str) -> bool:
        """
        Removes a user from the store.

        Args:
            entity_id: The user ID.

        Returns:
            True if successful.
        """
        return True

    async def find_by_username(self, username: str) -> User | None:
        """
        Finds a user by their username.

        Args:
            username: The username to search for.

        Returns:
            A User instance if found.
        """
        # Mock implementation
        return User("123", username, "user@example.com")
