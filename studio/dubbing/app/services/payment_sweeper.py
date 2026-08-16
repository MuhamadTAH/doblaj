"""
Defensive Payment Sweeper Service

Periodically reconciles abandoned or delayed webhook events against Wayl's status API.
Enforces:
1. Strict Batching: Querying at most 50 pending records via compound index ["status", "createdAt"].
2. Outbound Throttling: Semaphore concurrency limit (max 3 concurrent requests) + token bucket pacing delay.
3. Circuit Breaking: Immediate batch abort on HTTP 429 (Rate Limit) or HTTP 5xx (Wayl Outage).
4. Zero-Cost Replays: Relies on Convex's read-first atomic recordAndProcessWaylEvent.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from app.core import db as database
from app.core.wayl_client import WaylClient

logger = logging.getLogger(__name__)


class SweeperCircuitBreakerError(Exception):
    """Raised when the circuit breaker trips on 429 or 5xx."""
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class DefensivePaymentSweeper:
    def __init__(
        self,
        batch_size: int = 50,
        older_than_minutes: int = 15,
        max_concurrency: int = 3,
        request_delay_sec: float = 0.15,
        max_age_hours: int = 48,
    ):
        self.batch_size = batch_size
        self.older_than_minutes = older_than_minutes
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.request_delay_sec = request_delay_sec
        self.max_age_hours = max_age_hours
        self.is_circuit_open = False
        self.last_circuit_trip_time = 0.0
        self.cooldown_period_sec = 300.0  # 5 minutes

    def _check_circuit(self) -> bool:
        """Returns True if circuit is open (broken/tripped) and cannot process."""
        if not self.is_circuit_open:
            return False
        if time.time() - self.last_circuit_trip_time > self.cooldown_period_sec:
            logger.info("[DEFENSIVE_SWEEPER] Circuit breaker cooldown elapsed; resetting circuit to closed.")
            self.is_circuit_open = False
            return False
        return True

    def _trip_circuit(self, status_code: int, reason: str):
        """Immediately trip the circuit breaker and record timestamp."""
        self.is_circuit_open = True
        self.last_circuit_trip_time = time.time()
        logger.warning(json.dumps({
            "security_event": "sweeper_circuit_breaker_tripped",
            "service": "payment_sweeper",
            "status_code": status_code,
            "reason": reason,
            "cooldown_seconds": self.cooldown_period_sec,
        }))

    async def check_wayl_link_status(self, wayl: WaylClient, reference_id: str) -> Dict[str, Any]:
        """Fetch link status from Wayl with strict throttling and circuit breaker triggers."""
        async with self.semaphore:
            # Token bucket pacing delay to never spike Wayl's WAF
            await asyncio.sleep(self.request_delay_sec)

            url = f"{wayl._get_base_url()}/api/v1/links/{reference_id}"
            headers = {
                "X-WAYL-AUTHENTICATION": wayl.api_token,
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 429:
                        self._trip_circuit(429, "Wayl API returned 429 Too Many Requests (Rate Limit)")
                        raise SweeperCircuitBreakerError(429, "Wayl API rate limit reached")
                    
                    if resp.status_code >= 500:
                        self._trip_circuit(resp.status_code, f"Wayl upstream server error {resp.status_code}")
                        raise SweeperCircuitBreakerError(resp.status_code, f"Wayl server error: {resp.status_code}")

                    if resp.status_code == 404:
                        return {"status": "NotFound", "referenceId": reference_id}

                    if resp.status_code >= 400:
                        logger.warning(f"[WAYL_SWEEPER] HTTP {resp.status_code} for ref={reference_id}: {resp.text}")
                        return {"status": "Error", "statusCode": resp.status_code}

                    data = resp.json()
                    if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
                        return data["data"]
                    return data
                except (httpx.ConnectError, httpx.TimeoutException) as conn_err:
                    self._trip_circuit(503, f"Wayl connection failure: {conn_err}")
                    raise SweeperCircuitBreakerError(503, f"Wayl connection failed: {conn_err}")

    async def sweep_once(self, client: Any = None) -> Dict[str, Any]:
        """Execute a single defensive sweep run."""
        if self._check_circuit():
            logger.warning("[DEFENSIVE_SWEEPER] Sweep run skipped: Circuit breaker is currently OPEN.")
            return {"status": "skipped", "reason": "circuit_breaker_open"}

        # 1. Clean up stale abandoned charges (>48h) first with circuit safety
        expired_count = await database.expire_stale_pending_charges(
            client, max_age_hours=self.max_age_hours, limit=100, is_circuit_healthy=True
        )

        # 2. Query bounded batch of pending charges (>15m) using compound index
        pending_charges = await database.get_pending_charges_for_sweep(
            client, older_than_minutes=self.older_than_minutes, limit=self.batch_size
        )

        if not pending_charges:
            return {
                "status": "completed",
                "processed": 0,
                "reconciled": 0,
                "expired": expired_count,
                "aborted": False
            }

        logger.info(f"[DEFENSIVE_SWEEPER] Found {len(pending_charges)} pending charges for defensive reconciliation.")
        wayl = WaylClient()

        processed_count = 0
        reconciled_count = 0
        aborted = False

        for charge in pending_charges:
            # Re-check circuit breaker state before each outbound call
            if self.is_circuit_open:
                logger.warning(f"[DEFENSIVE_SWEEPER] Aborting remainder of sweep batch ({len(pending_charges) - processed_count} skipped).")
                aborted = True
                break

            ref_id = charge.get("referenceId")
            amount = charge.get("amount", 1000)
            currency = charge.get("currency", "IQD")

            if not ref_id:
                continue

            try:
                link_data = await self.check_wayl_link_status(wayl, ref_id)
                processed_count += 1
                status = link_data.get("status")

                if status == "Complete":
                    logger.info(f"[DEFENSIVE_SWEEPER] Found completed pending charge ref={ref_id}. Reconciling atomically.")
                    res = await database.record_and_process_wayl_event(
                        client,
                        reference_id=ref_id,
                        amount=int(amount),
                        currency=currency,
                        raw_payload=json.dumps(link_data)
                    )
                    reconciled_count += 1
                    logger.info(f"[DEFENSIVE_SWEEPER] Reconciled ref={ref_id} result={res.get('status')}")
            except SweeperCircuitBreakerError as cb_err:
                logger.error(f"[DEFENSIVE_SWEEPER] Circuit breaker tripped during sweep of ref={ref_id}: {cb_err}")
                aborted = True
                break
            except Exception as e:
                logger.warning(f"[DEFENSIVE_SWEEPER] Error checking link ref={ref_id}: {e}")
                processed_count += 1

        return {
            "status": "completed" if not aborted else "aborted_circuit_breaker",
            "processed": processed_count,
            "reconciled": reconciled_count,
            "expired": expired_count,
            "aborted": aborted
        }
