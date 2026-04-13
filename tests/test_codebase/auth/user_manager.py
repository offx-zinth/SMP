from __future__ import annotations

from ..db.user_repository import UserRepository, User


class UserManager:
    """
    Manages user-related business logic.
    """

    def __init__(self, user_repo: UserRepository):
        """
        Initializes the UserManager.

        Args:
            user_repo: An instance of UserRepository for data access.
        """
        self._user_repo = user_repo

    async def create_user(self, username: str, email: str) -> User:
        """
        Creates a new user in the system.

        Args:
            username: Desired username.
            email: User's email address.

        Returns:
            The created User object.
        """
        user = User("new_id", username, email)
        await self._user_repo.save(user)
        return user

    async def get_user_profile(self, user_id: str) -> User | None:
        """
        Retrieves a user's profile.

        Args:
            user_id: The ID of the user.

        Returns:
            The User object if found.
        """
        return await self._user_repo.get_by_id(user_id)
