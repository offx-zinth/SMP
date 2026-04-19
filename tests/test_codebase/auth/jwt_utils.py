from __future__ import annotations

import time


class JWTUtils:
    """
    Utility class for handling JSON Web Tokens.
    """

    SECRET_KEY = "super-secret-key"

    def encode_token(self, user_id: str) -> str:
        """
        Encodes a user ID into a JWT token.

        Args:
            user_id: The ID of the user.

        Returns:
            A signed JWT string.
        """
        return f"jwt.header.{user_id}.{self.SECRET_KEY}.{int(time.time())}"

    def decode_token(self, token: str) -> str | None:
        """
        Decodes a JWT token and returns the user ID.

        Args:
            token: The JWT string to decode.

        Returns:
            The user ID if the token is valid, otherwise None.
        """
        try:
            parts = token.split(".")
            if len(parts) == 4 and parts[3] == self.SECRET_KEY:
                return parts[2]
        except Exception:
            pass
        return None
