from __future__ import annotations

from ..auth.session_handler import SessionHandler
from ..auth.user_manager import UserManager
from ..db.order_repository import OrderRepository
from ..utils.validators import validate_email


class APIRoutes:
    """
    Defines the API routes and their handlers.
    This class acts as a 'Hot Node' as it coordinates multiple services.
    """

    def __init__(
        self, 
        session_handler: SessionHandler, 
        user_manager: UserManager, 
        order_repo: OrderRepository
    ):
        """
        Initializes the APIRoutes with necessary services.
        """
        self._session_handler = session_handler
        self._user_manager = user_manager
        self._order_repo = order_repo

    async def handle_login(self, username: str) -> str:
        """
        Route handler for user login.

        Args:
            username: The username to log in.

        Returns:
            A session token or an error message.
        """
        token = await self._session_handler.login(username)
        return token if token else "Unauthorized"

    async def handle_get_profile(self, token: str) -> str:
        """
        Route handler for retrieving user profile.

        Args:
            token: The authentication token.

        Returns:
            User profile details or an error message.
        """
        if await self._session_handler.validate_session(token):
            user_id = "user_123" # Mocked from token
            user = await self._user_manager.get_user_profile(user_id)
            return f"User: {user.username if user else 'Unknown'}"
        return "Invalid Session"

    async def handle_create_user(self, username: str, email: str) -> str:
        """
        Route handler for user registration.

        Args:
            username: New username.
            email: New email.

        Returns:
            Success or failure message.
        """
        if not validate_email(email):
            return "Invalid Email"
        
        user = await self._user_manager.create_user(username, email)
        return f"User {user.username} created"

    async def handle_get_orders(self, token: str) -> str:
        """
        Route handler for retrieving user orders.

        Args:
            token: The authentication token.

        Returns:
            List of orders or an error message.
        """
        if await self._session_handler.validate_session(token):
            user_id = "user_123" # Mocked from token
            orders = await self._order_repo.get_orders_by_user(user_id)
            return f"Orders: {len(orders)}"
        return "Invalid Session"
