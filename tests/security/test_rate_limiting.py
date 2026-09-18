from __future__ import annotations

from unittest.mock import MagicMock, patch

from smp.protocol.auth import Principal, RateLimiter, Scope


def test_rate_limiting_disabled():
    """Test that rate limiting is disabled when per_minute <= 0."""
    limiter = RateLimiter(per_minute=0)
    principal = Principal("id", "name", frozenset({Scope.READ}))

    for _ in range(100):
        assert limiter.allow(principal) is True


def test_rate_limiting_local_success():
    """S-007: Test that local rate limiter allows requests within limit."""
    limiter = RateLimiter(per_minute=5)
    principal = Principal("id", "name", frozenset({Scope.READ}))

    for _ in range(5):
        assert limiter.allow(principal) is True

    assert limiter.allow(principal) is False


def test_rate_limiting_local_window():
    """S-007: Test that local rate limiter resets after 60 seconds."""
    limiter = RateLimiter(per_minute=1)
    principal = Principal("id", "name", frozenset({Scope.READ}))

    with patch("time.monotonic") as mock_mono:
        # Start at t=0
        mock_mono.return_value = 0.0
        assert limiter.allow(principal) is True
        assert limiter.allow(principal) is False

        # Move time forward by 61 seconds
        mock_mono.return_value = 61.0
        assert limiter.allow(principal) is True


def test_rate_limiting_redis_success():
    """S-008: Test that Redis rate limiter allows requests within limit."""
    # Mock redis.from_url and the redis client
    with patch("redis.from_url") as mock_from_url:
        mock_redis = MagicMock()
        mock_from_url.return_value = mock_redis

        # Mock pipeline execution
        # pipe.execute() returns [zremrangebyscore, zadd, zcard, expire]
        # We want zcard to return something <= per_minute
        mock_pipe = mock_redis.pipeline.return_value
        mock_pipe.execute.return_value = [0, 0, 1, True]  # zcard = 1

        limiter = RateLimiter(per_minute=5, redis_url="redis://localhost:6379")
        principal = Principal("id", "name", frozenset({Scope.READ}))

        assert limiter.allow(principal) is True


def test_rate_limiting_redis_exceeded():
    """S-008: Test that Redis rate limiter blocks requests exceeding limit."""
    with patch("redis.from_url") as mock_from_url:
        mock_redis = MagicMock()
        mock_from_url.return_value = mock_redis

        mock_pipe = mock_redis.pipeline.return_value
        mock_pipe.execute.return_value = [0, 0, 10, True]  # zcard = 10

        limiter = RateLimiter(per_minute=5, redis_url="redis://localhost:6379")
        principal = Principal("id", "name", frozenset({Scope.READ}))

        assert limiter.allow(principal) is False


def test_rate_limiting_redis_fallback():
    """S-009: Test that Redis failure falls back to local limiting."""
    with patch("redis.from_url") as mock_from_url:
        mock_redis = MagicMock()
        mock_from_url.return_value = mock_redis

        # Simulate Redis connection error during allow()
        mock_pipe = mock_redis.pipeline.return_value
        mock_pipe.execute.side_effect = Exception("Redis connection lost")

        limiter = RateLimiter(per_minute=5, redis_url="redis://localhost:6379")
        principal = Principal("id", "name", frozenset({Scope.READ}))

        # Should fallback to local. First request should be allowed.
        assert limiter.allow(principal) is True
