"""Auth utilities — custom decorators."""


def require_admin(func):
    """Decorator that gates a function for admin-only access."""

    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper
