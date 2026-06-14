import json
import os
from decimal import Decimal

try:
    import redis
except ImportError:  # pragma: no cover - optional in minimal local envs
    redis = None

REDIS_URL = os.getenv("REDIS_URL") or os.getenv("CACHE_REDIS_URL")
PRODUCT_CACHE_TTL = int(os.getenv("PRODUCT_CACHE_TTL", "300"))
PAGE_CACHE_TTL = int(os.getenv("PAGE_CACHE_TTL", "120"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "20"))

_client = None
_client_checked = False


def get_redis_client():
    """Return a Redis client when REDIS_URL is configured and reachable."""
    global _client, _client_checked
    if _client_checked:
        return _client

    _client_checked = True
    if not REDIS_URL or redis is None:
        return None

    try:
        client = redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=float(os.getenv("REDIS_CONNECT_TIMEOUT", "0.2")),
            socket_timeout=float(os.getenv("REDIS_SOCKET_TIMEOUT", "0.2")),
            health_check_interval=30,
        )
        client.ping()
    except redis.RedisError:
        _client = None
    else:
        _client = client
    return _client


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def cache_get_json(key):
    client = get_redis_client()
    if client is None:
        return None
    try:
        cached = client.get(key)
        return json.loads(cached) if cached else None
    except (redis.RedisError, json.JSONDecodeError, TypeError):
        return None


def cache_set_json(key, value, ttl=PRODUCT_CACHE_TTL):
    client = get_redis_client()
    if client is None:
        return False
    try:
        client.setex(key, ttl, json.dumps(value, default=_json_default, ensure_ascii=False))
        return True
    except (redis.RedisError, TypeError):
        return False


def cache_get_text(key):
    client = get_redis_client()
    if client is None:
        return None
    try:
        return client.get(key)
    except redis.RedisError:
        return None


def cache_set_text(key, value, ttl=PAGE_CACHE_TTL):
    client = get_redis_client()
    if client is None:
        return False
    try:
        client.setex(key, ttl, value)
        return True
    except redis.RedisError:
        return False


def is_rate_limited(key, limit=RATE_LIMIT_MAX_REQUESTS, window=RATE_LIMIT_WINDOW_SECONDS):
    """Increment a Redis counter and return True when the request is over limit."""
    client = get_redis_client()
    if client is None:
        return False
    try:
        with client.pipeline() as pipe:
            pipe.incr(key)
            pipe.expire(key, window, nx=True)
            current, _ = pipe.execute()
        return int(current) > limit
    except redis.RedisError:
        return False
