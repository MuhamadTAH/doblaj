"""
admin_velocity.py — Distributed Atomic Sliding-Window Rate Limiter & Tiered Degradation Matrix.

Enforces actor/session-bound limits using Redis Lua script with an explicit degradation matrix:
1. Destructive Actions (Nuke, Ban, Impersonate) -> FAIL-CLOSED (strict block when Redis is down).
2. High-Impact Actions (Refund, Balance) -> Conservative clamped fallback.
3. Read-Only / Telemetry Actions -> FAIL-OPEN with telemetry alert.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_redis_client = None
_redis_last_failure = 0.0
_redis_circuit_breaker_sec = 30.0

_memory_windows: Dict[str, List[Tuple[float, str]]] = {}

SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local event_id = ARGV[4]

local clear_before = now - window
redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)

local current_count = redis.call('ZCARD', key)
if current_count >= limit then
    return {0, current_count}
else
    redis.call('ZADD', key, now, event_id)
    redis.call('PEXPIRE', key, window)
    return {1, current_count + 1}
end
"""

VELOCITY_THRESHOLDS: Dict[str, Dict[str, int]] = {
    "nuke": {"max_events": 10, "window_ms": 60000, "policy": "FAIL_CLOSED"},
    "ban": {"max_events": 10, "window_ms": 60000, "policy": "FAIL_CLOSED"},
    "impersonate": {"max_events": 10, "window_ms": 60000, "policy": "FAIL_CLOSED"},
    "critical_flag_toggle": {"max_events": 5, "window_ms": 60000, "policy": "FAIL_CLOSED"},
    "set_user_role": {"max_events": 10, "window_ms": 60000, "policy": "FAIL_CLOSED"},
    "refund": {"max_events": 5, "window_ms": 60000, "policy": "CONSERVATIVE_FALLBACK", "conservative_limit": 1},
    "balance_adjust": {"max_events": 15, "window_ms": 60000, "policy": "CONSERVATIVE_FALLBACK", "conservative_limit": 3},
    "general": {"max_events": 60, "window_ms": 60000, "policy": "FAIL_OPEN"},
}


def _get_redis():
    global _redis_client, _redis_last_failure
    now = time.time()
    if _redis_client is None and (now - _redis_last_failure > _redis_circuit_breaker_sec):
        redis_url = os.getenv("REDIS_URL") or os.getenv("UPSTASH_REDIS_URL")
        if redis_url:
            try:
                import redis
                _redis_client = redis.from_url(redis_url, decode_responses=True, socket_timeout=1)
                _redis_client.ping()
                logger.info("[VELOCITY] Connected to distributed Redis rate limiter")
            except Exception as e:
                logger.warning(f"[VELOCITY] Redis connection failed, activating circuit breaker: {e}")
                _redis_client = None
                _redis_last_failure = now
    return _redis_client


def check_and_record_velocity(
    admin_id: str, action: str, session_id: Optional[str] = None
) -> Tuple[bool, int, int, str]:
    """
    Check if the admin action is within rate limits according to tiered degradation strategy.
    Returns: (is_allowed: bool, current_count: int, max_limit: int, policy_status: str)
    """
    global _redis_client, _redis_last_failure
    now_ms = int(time.time() * 1000)
    config = VELOCITY_THRESHOLDS.get(action, VELOCITY_THRESHOLDS["general"])
    limit = config["max_events"]
    window_ms = config["window_ms"]
    policy = config.get("policy", "FAIL_OPEN")

    key_suffix = f"{admin_id}:{session_id or 'default'}:{action}"
    rate_key = f"velocity:{key_suffix}"
    event_id = str(uuid.uuid4())

    r = _get_redis()
    if r:
        try:
            res = r.eval(SLIDING_WINDOW_LUA, 1, rate_key, now_ms, window_ms, limit, event_id)
            allowed = bool(res[0] == 1)
            count = int(res[1])
            return allowed, count, limit, "REDIS_ACTIVE"
        except Exception as e:
            logger.error(f"[VELOCITY] Redis cluster eval error: {e}. Activating {policy} degradation policy.")
            _redis_client = None
            _redis_last_failure = time.time()

    # -------------------------------------------------------------
    # TIERED DEGRADATION POLICY EXECUTION (When Redis is unreachable)
    # -------------------------------------------------------------
    if policy == "FAIL_CLOSED":
        logger.critical(
            f"[VELOCITY-FAIL-CLOSED] Action '{action}' by admin {admin_id} blocked: Distributed Redis cluster unreachable."
        )
        return False, 0, limit, "FAIL_CLOSED_CLUSTER_UNAVAILABLE"

    # Conservative In-Memory Fallback
    effective_limit = config.get("conservative_limit", limit)
    window = _memory_windows.setdefault(rate_key, [])
    clear_before = now_ms - window_ms
    _memory_windows[rate_key] = [item for item in window if item[0] > clear_before]
    current_count = len(_memory_windows[rate_key])

    if current_count >= effective_limit:
        return False, current_count, effective_limit, f"{policy}_LIMIT_REACHED"

    _memory_windows[rate_key].append((now_ms, event_id))
    return True, current_count + 1, effective_limit, f"{policy}_DEGRADED_OK"
