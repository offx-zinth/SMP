from __future__ import annotations

from ..db.user_repository import UserRepository
from .jwt_utils import JWTUtils


class SessionHandler:
    """
    Handles user sessions and authentication state.
    """

    def __init__(self, jwt_utils: JWTUtils, user_repo: UserRepository):
        """
        Initializes the SessionHandler.

        Args:
            jwt_utils: Utility for JWT operations.
            user_repo: Repository for user data.
        """
        self._jwt_utils = jwt_utils
        self._user_repo = user_repo

    async def login(self, username: str) -> str | None:
        """
        Authenticates a user and returns a session token.

        Args:
            username: The username of the user.

        Returns:
            A JWT token if authentication succeeds, otherwise None.
        """
        user = await self._user_repo.find_by_username(username)
        if user:
            return self._jwt_utils.encode_token(user.user_id)
        return None

    async def validate_session(self, token: str) -> bool:
        """
        Validates if a session token is still active and valid.

        Args:
            token: The JWT token to validate.

        Returns:
            True if valid, False otherwise.
        """
        user_id = self._jwt_utils.decode_token(token)
        if user_id:
            user = await self._user_repo.get_by_id(user_id)
            return user is not None
        return False
