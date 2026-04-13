from __future__ import annotations

import re


def validate_email(email: str) -> bool:
    """
    Validates an email address using a regular expression.

    Args:
        email: The email string to validate.

    Returns:
        True if the email is valid, False otherwise.
    """
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, email))


def validate_username(username: str) -> bool:
    """
    Validates a username. Must be alphanumeric and between 3-20 characters.

    Args:
        username: The username to validate.

    Returns:
        True if the username is valid, False otherwise.
    """
    return username.isalnum() and 3 <= len(username) <= 20
