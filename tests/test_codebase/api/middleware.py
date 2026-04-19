from __future__ import annotations

from collections.abc import Callable


class Middleware:
    """
    Simple middleware for request processing.
    """

    async def process_request(self, request_id: str, handler: Callable) -> str:
        """
        Processes a request by wrapping it with middleware logic.

        Args:
            request_id: The unique ID of the request.
            handler: The handler function to execute.

        Returns:
            The result of the handler as a string.
        """
        print(f"Processing request {request_id}")
        result = await handler()
        print(f"Finished request {request_id}")
        return result
