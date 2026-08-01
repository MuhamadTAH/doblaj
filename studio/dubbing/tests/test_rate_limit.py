"""PIRD-010 regression tests.

Three real bugs are covered here:

1. `_rate_limited("5/minute")` passed a str to a param typed `int`, so the
   comparison `len(bucket) >= per_minute` would raise TypeError.
2. The decorated routes declared no `request: Request` parameter, so the
   limiter silently no-opped on every request instead of failing loudly.
3. `/internal/jobs` carried the PIRD-010 comment but no decorator.
"""
import asyncio
import inspect

import pytest
from fastapi import HTTPException, Request

from app.core.ratelimit import _parse_per_minute, _rate_buckets, rate_limited


def _make_request(host: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "client": (host, 12345),
        }
    )


@pytest.fixture(autouse=True)
def _clear_buckets():
    _rate_buckets.clear()
    yield
    _rate_buckets.clear()


# --- bug 1: the "5/minute" string form must be accepted -------------------


@pytest.mark.parametrize(
    "value,expected",
    [(5, 5), ("5/minute", 5), ("12/min", 12), ("1/minute", 1)],
)
def test_parse_per_minute_accepts_int_and_string(value, expected):
    assert _parse_per_minute(value) == expected


@pytest.mark.parametrize("value", ["5/hour", "5/second", "0", 0, -1, "abc"])
def test_parse_per_minute_rejects_bad_values(value):
    with pytest.raises(ValueError):
        _parse_per_minute(value)


def test_string_limit_enforces_not_typeerrors():
    """The original bug: a str limit blew up on comparison instead of capping."""

    @rate_limited("2/minute")
    async def route(request: Request):
        return "ok"

    req = _make_request("10.0.0.1")
    assert asyncio.run(route(request=req)) == "ok"
    assert asyncio.run(route(request=req)) == "ok"
    with pytest.raises(HTTPException) as exc:
        asyncio.run(route(request=req))
    assert exc.value.status_code == 429


# --- bug 2: a route with no `request` param must fail loudly, at import ---


def test_decorating_route_without_request_param_raises_at_decoration_time():
    with pytest.raises(TypeError, match="request"):

        @rate_limited("5/minute")
        async def bad_route(file: str = "x"):
            return "ok"


def test_limit_is_per_client_ip():
    @rate_limited(1)
    async def route(request: Request):
        return "ok"

    assert asyncio.run(route(request=_make_request("10.0.0.1"))) == "ok"
    # different IP gets its own bucket
    assert asyncio.run(route(request=_make_request("10.0.0.2"))) == "ok"
    with pytest.raises(HTTPException):
        asyncio.run(route(request=_make_request("10.0.0.1")))


def test_429_includes_retry_after_header():
    @rate_limited(1)
    async def route(request: Request):
        return "ok"

    req = _make_request("10.0.0.9")
    asyncio.run(route(request=req))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(route(request=req))
    assert exc.value.headers["Retry-After"] == "60"


def test_budgets_are_independent_per_route():
    """Exhausting one route must not lock the same IP out of another."""

    @rate_limited(1)
    async def route_a(request: Request):
        return "a"

    @rate_limited(1)
    async def route_b(request: Request):
        return "b"

    req = _make_request("10.0.0.7")
    assert asyncio.run(route_a(request=req)) == "a"
    with pytest.raises(HTTPException):
        asyncio.run(route_a(request=req))
    # route_b has its own budget for the same caller
    assert asyncio.run(route_b(request=req)) == "b"


# --- bug 3: the three expensive routes are actually wired -----------------


@pytest.mark.parametrize(
    "module_path,func_name",
    [
        ("app.api.routes.video", "create_job"),
        ("app.api.routes.video", "ingest_video"),
        ("app.api.routes.internal_jobs", "create_internal_job"),
    ],
)
def test_expensive_routes_are_rate_limited(module_path, func_name):
    module = pytest.importorskip(module_path)
    fn = getattr(module, func_name)
    assert getattr(fn, "__wrapped__", None) is not None, f"{func_name} is not decorated"
    # and it must declare `request` or the limiter can never see the caller IP
    assert "request" in inspect.signature(fn).parameters, (
        f"{func_name} lacks a `request: Request` parameter"
    )
