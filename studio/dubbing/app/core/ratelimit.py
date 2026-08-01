"""PIRD-010: per-IP rate limiting for expensive routes.

Shared by `app/api/routes/video.py` and `app/api/routes/internal_jobs.py`.
Lives here rather than in video.py so internal_jobs.py doesn't have to
import a peer route module to get it.

ponytail: in-process token bucket, not Redis-backed. The cap is therefore
per worker — with N uvicorn workers the effective global cap is
`per_minute * N`. If that matters, port the Redis INCR + EXPIRE pattern
already used in `app/api/routes/user_delete.py::_check_rate_limit`.
"""
from __future__ import annotations

import inspect
import time
from functools import wraps
from typing import Dict, List, Union

from fastapi import HTTPException, Request

# "<route qualname>:<client host>" -> monotonic timestamps inside the window.
# Keyed per route as well as per IP so that exhausting the /jobs budget does
# not also lock the caller out of /ingest — they are separate operations and a
# legitimate user hits both in one session.
_rate_buckets: Dict[str, List[float]] = {}
_WINDOW_SEC = 60.0


def _parse_per_minute(value: Union[int, str]) -> int:
    """Accept either `5` or `"5/minute"` and return the integer cap.

    The original PIRD-010 code typed this param `int` but every call site
    passed the string `"5/minute"`, so `len(bucket) >= per_minute` compared
    an int to a str. Accept both forms explicitly instead.
    """
    if isinstance(value, bool):
        raise ValueError(f"rate limit must be an int or 'N/minute', got {value!r}")
    if isinstance(value, int):
        limit = value
    elif isinstance(value, str):
        head, sep, unit = value.partition("/")
        if sep and unit not in ("minute", "min"):
            raise ValueError(
                f"unsupported rate-limit window {value!r}; only per-minute is supported"
            )
        try:
            limit = int(head.strip())
        except ValueError:
            raise ValueError(f"could not parse rate limit {value!r}") from None
    else:
        raise ValueError(f"rate limit must be an int or 'N/minute', got {value!r}")
    if limit < 1:
        raise ValueError(f"rate limit must be >= 1, got {value!r}")
    return limit


def rate_limited(per_minute: Union[int, str] = 5):
    """Cap a route at `per_minute` requests per client IP per 60s.

    The decorated route MUST declare a `request: Request` parameter. Without
    it Starlette never hands us the request and the limit would silently
    never apply — which is exactly how the original PIRD-010 limiter was
    dead code on `/jobs` and `/ingest`. We check the signature at decoration
    time so a mistake is an app-boot crash, not a silent hole in production.
    """
    limit = _parse_per_minute(per_minute)

    def decorator(fn):
        if "request" not in inspect.signature(fn).parameters:
            raise TypeError(
                f"{fn.__module__}.{fn.__qualname__} is decorated with @rate_limited "
                "but declares no `request: Request` parameter, so the rate limit "
                "would silently never apply. Add `request: Request` to its signature."
            )

        @wraps(fn)
        async def wrapper(*args, **kwargs):
            request = kwargs.get("request")
            if request is None:
                request = next((a for a in args if isinstance(a, Request)), None)
            if request is None:
                # Signature said `request` exists, so this is unreachable via
                # FastAPI. Fail closed rather than skipping the limit.
                raise HTTPException(
                    status_code=429, detail="Rate limit could not be evaluated"
                )

            key = f"{fn.__qualname__}:{request.client.host if request.client else 'unknown'}"
            now = time.monotonic()
            bucket = _rate_buckets.setdefault(key, [])
            bucket[:] = [t for t in bucket if now - t < _WINDOW_SEC]
            if len(bucket) >= limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded: {limit}/minute",
                    headers={"Retry-After": str(int(_WINDOW_SEC))},
                )
            bucket.append(now)
            return await fn(*args, **kwargs)

        return wrapper

    return decorator
