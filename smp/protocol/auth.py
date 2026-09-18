"""Authentication, authorization, and scope policy for the SMP server.

Design goals
------------

* Zero-friction for local development: when no key file is configured the
  server runs in *open* mode and every request is treated as the synthetic
  ``dev`` principal that holds every scope.  Open mode is logged loudly at
  startup so it cannot be confused with a hardened deployment.

* Drop-in for production: pointing ``SMP_API_KEYS_FILE`` at a JSON file
  enables per-key authentication.  Each key declares a name and a list of
  scopes.  Requests must arrive with ``Authorization: Bearer <key>`` (or
  ``X-SMP-Api-Key: <key>``); missing or unknown keys yield ``401`` and the
  scope check yields ``403``.

* Scope policy is **declarative** — every JSON-RPC method maps to a
  required scope (``read`` / ``write`` / ``admin``).  Methods absent from
  the table default to ``admin``, so any new handler that forgets to add a
  scope cannot accidentally be exposed publicly.

* Errors returned to clients never echo internals: they always carry a
  short, fixed message and the actual exception is logged with full
  detail.  This avoids leaking traceback fragments through the JSON-RPC
  envelope.
"""

from __future__ import annotations

import enum
import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

import msgspec

try:
    import redis
except ImportError:  # pragma: no cover - redis is an optional dependency
    redis = None  # type: ignore[assignment]

from smp.logging import get_logger

log = get_logger(__name__)


class Scope(enum.StrEnum):
    """Coarse-grained authorisation scopes."""

    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


# ---------------------------------------------------------------------------
# Method -> scope policy
# ---------------------------------------------------------------------------

# Methods that only inspect graph state.
_READ_METHODS: frozenset[str] = frozenset(
    {
        "smp/navigate",
        "smp/trace",
        "smp/context",
        "smp/impact",
        "smp/locate",
        "smp/search",
        "smp/flow",
        "smp/diff",
        "smp/plan",
        "smp/conflict",
        "smp/why",
        "smp/telemetry",
        "smp/telemetry/hot",
        "smp/telemetry/node",
        "smp/audit/get",
        "smp/community/list",
        "smp/community/get",
        "smp/community/boundaries",
        "smp/sync",
        "smp/integrity/check",
        "smp/dryrun",
        "smp/session/recover",
        "smp/enrich/status",
    }
)

# Methods that mutate state but stay inside the SMP graph.
_WRITE_METHODS: frozenset[str] = frozenset(
    {
        "smp/update",
        "smp/batch_update",
        "smp/reindex",
        "smp/enrich",
        "smp/enrich/batch",
        "smp/enrich/stale",
        "smp/annotate",
        "smp/annotate/bulk",
        "smp/tag",
        "smp/session/open",
        "smp/session/close",
        "smp/checkpoint",
        "smp/rollback",
        "smp/lock",
        "smp/unlock",
        "smp/community/detect",
        "smp/index/import",
        "smp/integrity/baseline",
        "smp/review/create",
        "smp/review/approve",
        "smp/review/reject",
        "smp/review/comment",
    }
)

# Methods that touch the host environment or external systems.
_ADMIN_METHODS: frozenset[str] = frozenset(
    {
        "smp/sandbox/spawn",
        "smp/sandbox/execute",
        "smp/sandbox/kill",
        "smp/pr/create",
    }
)


def required_scope(method: str) -> Scope:
    """Return the scope a caller must hold to invoke ``method``.

    Unknown methods default to :data:`Scope.ADMIN` so a missing entry
    fails closed rather than open.
    """
    if method in _READ_METHODS:
        return Scope.READ
    if method in _WRITE_METHODS:
        return Scope.WRITE
    if method in _ADMIN_METHODS:
        return Scope.ADMIN
    return Scope.ADMIN


# ---------------------------------------------------------------------------
# Principals & key registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """An authenticated caller."""

    key_id: str
    name: str
    scopes: frozenset[Scope]
    created_at: float | None = None
    expires_at: float | None = None

    def has(self, scope: Scope) -> bool:
        return Scope.ADMIN in self.scopes or scope in self.scopes


class _KeyConfig(msgspec.Struct):
    name: str = ""
    scopes: list[str] = msgspec.field(default_factory=list)
    created_at: float | None = None
    expires_at: float | None = None


class _KeysFile(msgspec.Struct):
    keys: dict[str, _KeyConfig] = msgspec.field(default_factory=dict)


@dataclass
class AuthPolicy:
    """In-memory registry of API keys and the global open-mode flag."""

    keys: dict[str, Principal] = field(default_factory=dict)
    open_mode: bool = False
    rate_limit_per_minute: int = 0
    max_request_bytes: int = 1_048_576  # 1 MiB
    redis_url: str | None = None

    @classmethod
    def from_env(cls) -> AuthPolicy:
        keys_path = os.environ.get("SMP_API_KEYS_FILE")
        open_mode = os.environ.get("SMP_OPEN_MODE") == "1"
        redis_url = os.environ.get("SMP_REDIS_URL")
        try:
            rate = int(os.environ.get("SMP_RATE_LIMIT_PER_MINUTE", "0") or "0")
        except ValueError:
            log.warning("auth_invalid_rate_limit", value=os.environ.get("SMP_RATE_LIMIT_PER_MINUTE"))
            rate = 0
        max_bytes_env = os.environ.get("SMP_MAX_REQUEST_BYTES")
        try:
            max_bytes = int(max_bytes_env) if max_bytes_env else 1_048_576
        except ValueError:
            max_bytes = 1_048_576

        if open_mode:
            log.warning("auth_open_mode_enabled", reason="SMP_OPEN_MODE=1 configured")

        if not keys_path:
            return cls(
                open_mode=open_mode,
                rate_limit_per_minute=rate,
                max_request_bytes=max_bytes,
                redis_url=redis_url,
            )

        path = Path(keys_path)
        if not path.exists():
            log.warning("auth_keys_file_missing", path=str(path))
            return cls(
                open_mode=open_mode,
                rate_limit_per_minute=rate,
                max_request_bytes=max_bytes,
                redis_url=redis_url,
            )

        try:
            data = msgspec.json.decode(path.read_bytes(), type=_KeysFile)
        except (msgspec.ValidationError, msgspec.DecodeError, OSError, json.JSONDecodeError):
            log.exception("auth_keys_file_invalid", path=str(path))
            return cls(
                open_mode=open_mode,
                rate_limit_per_minute=rate,
                max_request_bytes=max_bytes,
                redis_url=redis_url,
            )

        keys: dict[str, Principal] = {}
        for token, cfg in data.keys.items():
            scopes: set[Scope] = set()
            for raw in cfg.scopes:
                try:
                    scopes.add(Scope(raw))
                except ValueError:
                    log.warning("auth_unknown_scope", scope=raw, key=cfg.name or token[:6])
            keys[token] = Principal(
                key_id=token[:8],
                name=cfg.name or "unnamed",
                scopes=frozenset(scopes),
                created_at=cfg.created_at,
                expires_at=cfg.expires_at,
            )

        log.info("auth_loaded", keys=len(keys), rate_limit_per_minute=rate, max_request_bytes=max_bytes)
        return cls(
            keys=keys,
            open_mode=open_mode,
            rate_limit_per_minute=rate,
            max_request_bytes=max_bytes,
            redis_url=redis_url,
        )

    def authenticate(self, token: str | None) -> Principal | None:
        if self.open_mode:
            return Principal(
                key_id="dev",
                name="dev",
                scopes=frozenset({Scope.READ, Scope.WRITE, Scope.ADMIN}),
            )
        if not token:
            return None

        principal = self.keys.get(token)
        if not principal:
            log.warning("auth_failed_unknown_token", token_prefix=token[:6] if token else "none")
            return None

        if principal.expires_at and time.time() > principal.expires_at:
            log.warning("auth_failed_expired_token", principal=principal.name, key_id=principal.key_id)
            return None

        return principal

    def rotate_key(
        self, token: str, new_token: str | None = None, expires_in_seconds: int | None = None
    ) -> Principal | None:
        """Rotate an API key's token or update its expiration."""
        principal = self.keys.get(token)
        if not principal:
            log.warning("rotate_key_failed_not_found", token_prefix=token[:6])
            return None

        now = time.time()
        expires_at = now + expires_in_seconds if expires_in_seconds else principal.expires_at

        updated_principal = Principal(
            key_id=new_token[:8] if new_token else principal.key_id,
            name=principal.name,
            scopes=principal.scopes,
            created_at=now,
            expires_at=expires_at,
        )

        if new_token:
            del self.keys[token]
            self.keys[new_token] = updated_principal
        else:
            self.keys[token] = updated_principal

        log.info("auth_key_rotated", principal=principal.name, new_token_provided=bool(new_token))
        return updated_principal


# ---------------------------------------------------------------------------
# Rate limiting (very small, in-memory token bucket per principal)
# ---------------------------------------------------------------------------


class RateLimiter:
    """Sliding-window rate limiter.

    Uses Redis if ``redis_url`` is provided and available; otherwise falls back
    to an in-memory implementation. Disabled when ``per_minute <= 0``.
    """

    def __init__(self, per_minute: int, redis_url: str | None = None) -> None:
        self.per_minute = max(0, int(per_minute))
        self.redis_url = redis_url
        self._redis: Any | None = None
        self._local_buckets: dict[str, deque[float]] = {}
        self._local_lock = Lock()

        if self.redis_url:
            if redis is None:
                log.warning("rate_limiter_redis_unavailable", fallback="in-memory")
            else:
                try:
                    self._redis = redis.from_url(self.redis_url, decode_responses=True)
                    # Test connection
                    self._redis.ping()
                    log.info("rate_limiter_redis_enabled", url=self.redis_url)
                except Exception as exc:
                    log.warning("rate_limiter_redis_failed", error=str(exc), fallback="in-memory")
                    self._redis = None

    def allow(self, principal: Principal) -> bool:
        if self.per_minute <= 0:
            return True

        if self._redis:
            try:
                return self._allow_redis(principal.key_id)
            except Exception as exc:
                log.error("rate_limiter_redis_error", error=str(exc), fallback="in-memory")

        return self._allow_local(principal.key_id)

    def _allow_redis(self, key_id: str) -> bool:
        now = time.time()
        cutoff = now - 60.0
        # Use a pipeline for atomicity and performance
        if self._redis is None:
            return True
        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(key_id, 0, cutoff)
        pipe.zadd(key_id, {str(now): now})
        pipe.zcard(key_id)
        pipe.expire(key_id, 60)
        result = pipe.execute()
        count: int = result[2]
        return count <= self.per_minute

    def _allow_local(self, key_id: str) -> bool:
        now = time.monotonic()
        cutoff = now - 60.0
        with self._local_lock:
            bucket = self._local_buckets.setdefault(key_id, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.per_minute:
                return False
            bucket.append(now)
            return True


# ---------------------------------------------------------------------------
# JSON-RPC error helpers
# ---------------------------------------------------------------------------


def rpc_error(code: int, message: str, request_id: Any = None, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "error": err, "id": request_id}


def safe_internal_error(request_id: Any) -> dict[str, Any]:
    """Generic internal-error envelope that never echoes traceback text."""
    return rpc_error(-32603, "Internal error", request_id)


def extract_token(headers: Any) -> str | None:
    """Pull the API key out of an HTTP request's headers.

    Accepts either ``Authorization: Bearer <key>`` or
    ``X-SMP-Api-Key: <key>``.  Returns ``None`` if neither is present.
    """
    auth = headers.get("authorization") if hasattr(headers, "get") else None
    if isinstance(auth, str) and auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    api_key = headers.get("x-smp-api-key") if hasattr(headers, "get") else None
    if isinstance(api_key, str) and api_key.strip():
        return api_key.strip()
    return None


__all__ = [
    "AuthPolicy",
    "Principal",
    "RateLimiter",
    "Scope",
    "extract_token",
    "required_scope",
    "rpc_error",
    "safe_internal_error",
]
